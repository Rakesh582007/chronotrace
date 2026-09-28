"""Facts for an LLM summary: everything a summary may say, computed by the trend engine.

In: the patient's code, sex, age and recorded conditions; the period; report labels (R1, R2, ... over the
whole history), dates and labs; flags; trends (results, baseline, change vs baseline, slope); medication
events and the lab response after each; data notes. Out: never the patient's name, a PDF, or any text
printed on a report (test names, value text, rows) — values are the engine's numbers.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from ..trends import engine
from ..trends.systems import BodySystem, change_vs_baseline

SINCE_LAST_VISIT, RANGE, ALL = "since_last_visit", "range", "all"

RULES = {
    "RCV_PREV": "change from the previous result larger than the reference change value",
    "RCV_BASELINE": "change from the patient's own baseline larger than the reference change value",
    "KDIGO_RAPID_EGFR": "eGFR falling faster than the KDIGO 2012 threshold of 5 mL/min/1.73 m² per year",
}
CHANGE_WORDS = {"start": "started", "stop": "ended", "dose_change": "dose changed"}
ADHERENCE = "Adherence is not recorded."
REGRESSION = ("If a treatment was started because of a high value, some change is expected anyway "
              "(regression to the mean).")


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class ReportRef:
    id: int
    date: dt.date | None
    lab: str | None


@dataclass(frozen=True)
class Period:
    kind: str
    start: dt.date
    end: dt.date


@dataclass
class Facts:
    data: dict                                   # what the LLM sees
    label_to_id: dict[str, int]                  # "R7" -> report id, for every label in data["reports"]
    counts: dict[str, int] = field(default_factory=dict)
    allowed_phrases: tuple[str, ...] = ()        # names the wording check skips: recorded conditions, lab names

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical(self.data).encode("utf-8")).hexdigest()


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def resolve_period(kind: str, reports: list[ReportRef], start: dt.date | None = None,
                   end: dt.date | None = None) -> Period:
    """since_last_visit: the second-latest confirmed report date to the latest; all: first to latest;
    range: the given dates, which must hold at least one confirmed report."""
    dates = sorted({r.date for r in reports if r.date})
    if not dates:
        raise PeriodError("the patient has no confirmed report yet")
    if kind == ALL:
        return Period(kind, dates[0], dates[-1])
    if kind == SINCE_LAST_VISIT:
        if len(dates) < 2:
            raise PeriodError("since_last_visit needs confirmed reports on two dates")
        return Period(kind, dates[-2], dates[-1])
    if start is None or end is None:
        raise PeriodError("a range needs both from and to")
    if start > end:
        raise PeriodError("from is after to")
    if not any(start <= d <= end for d in dates):
        raise PeriodError("there is no confirmed report in this range")
    return Period(kind, start, end)


def report_labels(reports: list[ReportRef]) -> dict[int, str]:
    """R1, R2, ... in date order over the patient's whole history (so labels do not change with the period)."""
    ordered = sorted(reports, key=lambda r: (r.date or dt.date.min, r.id))
    return {r.id: f"R{i}" for i, r in enumerate(ordered, 1)}


def num(x: float | None, places: int = 2):
    """A number as the summary may quote it: at most `places` decimals, whole numbers without ".0"."""
    if x is None:
        return None
    v = round(float(x), places)
    return int(v) if v == int(v) else v


def _day_value(points: list[engine.Point], date: dt.date) -> float | None:
    return next((d.value for d in engine.day_values(points) if d.date == date), None)


def build_facts(patient: dict, today: dt.date, reports: list[ReportRef], period: Period,
                points_by_analyte: dict[str, list[engine.Point]], events: list[engine.Event],
                infos: dict[str, engine.AnalyteInfo], systems: tuple[BodySystem, ...]) -> Facts:
    """`patient`: code, sex, birth_year, conditions (the name is not passed in at all)."""
    trends, flags = engine.analyse_patient(list(infos.values()), points_by_analyte, events)
    label = report_labels(reports)
    by_id = {r.id: r for r in reports}
    system_of = {a: s.name for s in systems for a in s.analytes}
    used: set[int] = set()

    def labels(ids) -> list[str]:
        ids = sorted({i for i in ids if i in label}, key=lambda i: int(label[i][1:]))
        used.update(ids)
        return [label[i] for i in ids]

    def in_period(d: dt.date) -> bool:
        return period.start <= d <= period.end

    def flag_in_period(d: dt.date) -> bool:
        # Since the last visit: flags on the previous visit's date were already there at that visit.
        after_start = d > period.start if period.kind == SINCE_LAST_VISIT else d >= period.start
        return after_start and d <= period.end

    period_reports = [r for r in reports if r.date and in_period(r.date)]
    labels(r.id for r in period_reports)

    # ---- flags
    flag_facts = []
    for f in (f for f in flags if flag_in_period(f["date"])):
        item = {"analyte": f["analyte_name"], "system": system_of.get(f["analyte_id"]), "level": f["level"],
                "rule": RULES[f["rule_id"]], "date": f["date"].isoformat(), "direction": f["direction"],
                "unit": f["unit"], "reports": labels(f["report_ids"])}
        c = f["compared"]
        if c["from"] is not None:
            item.update(change_percent=f["change_percent"], compared_with=c["from"]["label"],
                        from_value=num(c["from"]["value"]), from_dates=[d.isoformat() for d in c["from"]["dates"]],
                        to_value=num(c["to"]["value"]), to_date=c["to"]["date"].isoformat(),
                        threshold_percent=f["threshold"]["value"], threshold_status=f["threshold"]["rcv_status"])
        if c["slope"] is not None:
            s = c["slope"]
            pts = points_by_analyte.get(f["analyte_id"]) or []
            item.update(slope_per_year=num(s["per_year"]), results_used=s["n_points"], span_days=s["span_days"],
                        first_date=s["first_date"].isoformat(), last_date=s["last_date"].isoformat(),
                        first_value=num(_day_value(pts, s["first_date"])),
                        last_value=num(_day_value(pts, s["last_date"])),
                        threshold_per_year=abs(f["threshold"]["value"]))
        item["expected_effect"] = f["expected_effect"]["note"] if f["expected_effect"] else None
        item["values_from_different_labs"] = f["cross_lab"]
        flag_facts.append(item)

    # ---- trends
    trend_facts, unverified, not_established, censored = [], [], [], False
    for t in trends:
        aid = t["analyte_id"]
        pts = points_by_analyte.get(aid) or []
        if not any(in_period(p.date) for p in pts):
            continue
        obs_report = {p.observation_id: p.report_id for p in pts}
        results = [{"date": d.date.isoformat(), "value": num(d.value), "reports": labels(d.report_ids)}
                   for d in engine.day_values(pts) if in_period(d.date)]
        limits = [{"date": p.date.isoformat(), "comparator": p.comparator, "limit": num(p.value),
                   "reports": labels([p.report_id])} for p in pts if p.censored and in_period(p.date)]
        censored = censored or bool(limits)
        item = {"analyte": t["name"], "system": system_of.get(aid), "unit": t["canonical_unit"],
                "results_in_period": results}
        if limits:
            item["results_printed_as_a_limit"] = limits
        if t["baseline"] is not None:
            item["baseline"] = {"value": num(t["baseline"]), "dates": [d.isoformat() for d in t["baseline_dates"]],
                                "reports": labels(obs_report[i] for i in t["baseline_observation_ids"]),
                                "note": t["baseline_note"]}
            change = change_vs_baseline(t)
            item["latest_change_vs_baseline_percent"] = change
            item["latest_change_beyond_threshold"] = (None if change is None or t["rcv_percent"] is None
                                                      else abs(change) > t["rcv_percent"])
        s = t["slope"]
        if s is not None and s["per_year"] is not None:
            item["slope"] = {"per_year": num(s["per_year"]), "unit": s["unit"], "status": s["status"],
                             "results_used": s["n_points"], "span_days": s["span_days"],
                             "first_date": s["first_date"].isoformat(), "last_date": s["last_date"].isoformat(),
                             "first_value": num(_day_value(pts, s["first_date"])),
                             "last_value": num(_day_value(pts, s["last_date"])),
                             "results_left_out": len(s["excluded_points"]),
                             "left_out_because": ("inside a drug's expected-effect window"
                                                  if s["excluded_points"] else None)}
        item["change_threshold_percent"] = t["rcv_percent"]
        item["threshold_status"] = t["rcv_status"]
        if t["rcv_status"] == "unverified":
            unverified.append((t["name"], t["rcv_percent"]))
        elif t["rcv_percent"] is None:
            not_established.append(t["name"])
        trend_facts.append(item)

    # ---- medication events and the lab response after each
    event_facts, response_facts, with_response = [], [], 0
    for e in sorted((e for e in events if in_period(e.date)), key=lambda e: (e.date, e.id)):
        klass = e.klass
        event_facts.append({"date": e.date.isoformat(), "drug": e.drug, "change": CHANGE_WORDS.get(e.change, e.change),
                            "dose": e.dose_text or None, "drug_class": klass.name if klass else None})
        r = engine.response(e, infos, points_by_analyte, events)
        if r["note"]:
            response_facts.append({"event": f"{e.drug} {CHANGE_WORDS.get(e.change, e.change)} {e.date.isoformat()}",
                                   "note": r["note"]})
            continue
        with_response += 1
        for a in r["analytes"]:
            item = {"event": f"{e.drug} {CHANGE_WORDS.get(e.change, e.change)} {e.date.isoformat()}",
                    "analyte": a["name"], "unit": a["unit"], "status": a["status"]}
            if a["before"] is not None:
                item.update(before_mean=num(a["before"]["value"]),
                            before_dates=[d.isoformat() for d in a["before"]["dates"]],
                            before_reports=labels(a["before"]["report_ids"]))
            if a["after"] is not None:
                item.update(after_value=num(a["after"]["value"]), after_date=a["after"]["date"].isoformat(),
                            after_reports=labels(a["after"]["report_ids"]))
            if a["status"] == engine.RESP_ASSESSED:
                item.update(change_percent=a["change_percent"], threshold_percent=a["rcv_percent"],
                            beyond_threshold=a["beyond_rcv"], values_from_different_labs=a["cross_lab"])
            if a["expected"]["applies"]:
                item["expected_direction"] = a["expected"]["direction"]
            item["expected_effect"] = a["expected_effect"]["note"] if a["expected_effect"] else None
            if a["confounders"]:
                item["other_drug_changes_nearby"] = [
                    {"drug": o["drug"], "change": CHANGE_WORDS.get(o["change"], o["change"]),
                     "days_from_this_event": o["days_from_event"]} for o in a["confounders"]]
            response_facts.append(item)

    # ---- data notes (computed, not written by the LLM)
    labs = sorted({r.lab or engine.UNKNOWN_LAB for r in period_reports})
    notes = []
    if len(labs) > 1:
        notes.append(f"Reports in this period come from {len(labs)} labs; between-lab variation is larger "
                     "than the change thresholds assume.")
    # Threshold notes only for analytes the summary can talk about as a change (a flag or a drug response).
    talked_about = {f["analyte"] for f in flag_facts} | {r["analyte"] for r in response_facts if "analyte" in r}
    notes += [f"The {name} change threshold ({pct:g}%) is not yet verified against a published source."
              for name, pct in unverified if name in talked_about]
    notes += [f"{name} has no established change threshold, so its changes are not flagged."
              for name in not_established]
    if censored:
        notes.append("Some results were printed as a limit (such as \"<5\"); they are not used in calculations.")
    if any(e["change"] == "started" for e in event_facts):
        notes.append(REGRESSION)
    notes.append(ADHERENCE)

    age = today.year - patient["birth_year"]
    data = {
        "patient": {"code": patient["code"], "sex": patient["sex"], "age": age,
                    "recorded_conditions": list(patient["conditions"])},
        "period": {"kind": period.kind, "from": period.start.isoformat(), "to": period.end.isoformat(),
                   "reports_in_period": len(period_reports), "labs_in_period": len(labs)},
        "reports": [{"label": label[i], "date": by_id[i].date.isoformat() if by_id[i].date else None,
                     "lab": by_id[i].lab or engine.UNKNOWN_LAB, "in_period": by_id[i] in period_reports}
                    for i in sorted(used, key=lambda i: int(label[i][1:]))],
        "body_systems": [s.name for s in systems if any(t["system"] == s.name for t in trend_facts)],
        "flags": flag_facts,
        "trends": trend_facts,
        "medication_events": event_facts,
        "medication_responses": response_facts,
        "data_notes": notes,
    }
    counts = {"flags": len(flag_facts), "medication_responses": with_response, "reports": len(period_reports),
              "labs": len(labs)}
    names = tuple(patient["conditions"]) + tuple(sorted({r["lab"] for r in data["reports"]}))
    return Facts(data, {label[i]: i for i in used}, counts, names)
