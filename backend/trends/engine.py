"""Trend engine: baseline, reference-change-value flags, slope and medication response.

Pure functions on plain data (no database): the API passes one patient's confirmed values and
medication events, and everything is recomputed on every request.

Patient-agnostic: every threshold comes from data/analytes.yaml (rcv.percent) and data/drugs.yaml
(expected effects and windows). The only analyte-specific rule is KDIGO_RAPID_EGFR, which is about
eGFR by definition. Flags describe observed change; they never say what to do.

Rules
- A value with a comparator (">300", "<0.5") is shown in the series as `censored` and is never used
  in a calculation (baseline, change, slope, before/after).
- Several values on one date: the calculations use their mean; every point stays in the series.
- Baseline: median of the first up to 3 results before the first medication event whose class affects
  the analyte. Fewer than 2 such results: median of the first 3 results overall, noted as including
  on-treatment results. Fewer than 2 results in all: no baseline ("insufficient data").
- RCV_PREV: change from the previous result beyond the analyte's RCV. RCV_BASELINE: change from the
  baseline beyond the RCV, for results after those that formed the baseline.
- Expected effect: a flag whose later result lies inside the window of a drug START whose class moves
  this analyte in that direction carries the drug's note (for ACEi/ARB and creatinine, a rise above the
  class's max_expected_percent gets a different note).
- Slope: least squares in units per year, only on results after the end of the last expected-effect
  window for the analyte. >= 3 results spanning >= 365 days, else status "not enough span" and no
  guideline flag. KDIGO_RAPID_EGFR: eGFR slope below -5 mL/min/1.73 m2 per year.
- Medication response: last result <= event date (within 180 days) against the first result inside the
  class's window; confounders are other medication events from 90 days before the event to that result.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .catalogue import UNKNOWN, DrugClass, drug_class

BASELINE_N = 3
BEFORE_LOOKBACK_DAYS = 180
CONFOUNDER_LOOKBACK_DAYS = 90
SLOPE_MIN_POINTS = 3
SLOPE_MIN_SPAN_DAYS = 365
DAYS_PER_YEAR = 365.25
KDIGO_RAPID_EGFR_PER_YEAR = -5.0
KDIGO_SOURCE = ("KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD: a sustained "
                "eGFR decline of more than 5 mL/min/1.73 m2 per year is a rapid decline.")

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient data"
STATUS_CENSORED_ONLY = "censored values only"
SLOPE_OK, SLOPE_SHORT, SLOPE_FEW = "ok", "not enough span", "not enough points"
RESP_ASSESSED, RESP_TOO_EARLY, RESP_NO_BASELINE, RESP_NO_RESULT = (
    "assessed", "too early to assess", "no baseline", "no result in window")
ON_TREATMENT_NOTE = "includes on-treatment results"


# ---------------------------------------------------------------- inputs

@dataclass(frozen=True)
class Point:
    """One confirmed value, in the analyte's canonical unit."""
    observation_id: int
    report_id: int
    date: dt.date
    value: float
    comparator: str | None = None
    value_text: str = ""
    unit_text: str = ""
    lab: str | None = None
    page: int = 0
    line: int = 0

    @property
    def censored(self) -> bool:
        return self.comparator is not None


@dataclass(frozen=True)
class Event:
    id: int
    drug: str
    change: str                    # "start" | "stop" | "dose_change"
    date: dt.date
    drug_class: str = UNKNOWN      # class id from drugs.yaml, or "unknown"
    generic: str | None = None
    dose_text: str = ""

    @property
    def klass(self) -> DrugClass | None:
        return drug_class(self.drug_class)


@dataclass(frozen=True)
class AnalyteInfo:
    id: str
    name: str
    unit: str
    rcv_percent: float | None
    rcv_status: str                # verified | unverified | not established
    rcv_source: str = ""


# ---------------------------------------------------------------- derived values

@dataclass(frozen=True)
class DayValue:
    """The value used in calculations for one date: the mean of that date's non-censored results."""
    date: dt.date
    value: float
    points: tuple[Point, ...]

    @property
    def observation_ids(self) -> list[int]:
        return [p.observation_id for p in self.points]

    @property
    def report_ids(self) -> list[int]:
        return sorted({p.report_id for p in self.points})

    def ref(self) -> dict:
        return {"date": self.date, "value": round(self.value, 4), "observation_ids": self.observation_ids,
                "report_ids": self.report_ids}


def day_values(points: list[Point]) -> list[DayValue]:
    by_date: dict[dt.date, list[Point]] = defaultdict(list)
    for p in points:
        if not p.censored:
            by_date[p.date].append(p)
    return [DayValue(d, statistics.mean(p.value for p in ps), tuple(sorted(ps, key=lambda p: p.observation_id)))
            for d, ps in sorted(by_date.items())]


def pct_change(new: float, ref: float) -> float | None:
    """Percent change, rounded to 1 decimal: the value shown is the value compared with the RCV
    (which the dictionary gives to 1 decimal), so a flag never shows "15.0% beyond an RCV of 15.0%"."""
    return None if ref == 0 else round((new - ref) / ref * 100, 1)


@dataclass(frozen=True)
class Window:
    event: Event
    effect_direction: str
    note: str
    max_expected_percent: float | None
    start: dt.date
    end: dt.date
    source: str

    def contains(self, d: dt.date) -> bool:
        return self.start <= d <= self.end


def windows_for(analyte_id: str, events: list[Event]) -> list[Window]:
    """Expected-effect windows of drug STARTS whose class moves this analyte."""
    out = []
    for e in events:
        c = e.klass
        eff = c.effect_on(analyte_id) if c else None
        if eff is None or e.change != "start":
            continue
        out.append(Window(e, eff.direction, eff.note, eff.max_expected_percent,
                          e.date + dt.timedelta(days=c.window_start), e.date + dt.timedelta(days=c.window_end),
                          c.source))
    return out


def affecting_events(analyte_id: str, events: list[Event]) -> list[Event]:
    """Events (any change) whose class moves this analyte."""
    return [e for e in events if e.klass is not None and e.klass.effect_on(analyte_id) is not None]


def event_ref(e: Event) -> dict:
    return {"event_id": e.id, "drug": e.drug, "drug_class": e.drug_class, "change": e.change, "date": e.date}


# ---------------------------------------------------------------- baseline

@dataclass
class Baseline:
    value: float | None
    note: str | None
    days: list[DayValue]


def baseline(days: list[DayValue], analyte_id: str, events: list[Event]) -> Baseline:
    if len(days) < 2:
        return Baseline(None, None, [])
    first_event = min((e.date for e in affecting_events(analyte_id, events)), default=None)
    before = [d for d in days if first_event is None or d.date < first_event][:BASELINE_N]
    if len(before) >= 2:
        return Baseline(statistics.median(d.value for d in before), None, before)
    chosen = days[:BASELINE_N]
    return Baseline(statistics.median(d.value for d in chosen), ON_TREATMENT_NOTE, chosen)


# ---------------------------------------------------------------- expected effect

def expected_effect(windows: list[Window], later: dt.date, direction: str, change_percent: float | None) -> dict | None:
    for w in windows:
        if w.contains(later) and w.effect_direction == direction:
            note, short = w.note, w.event.klass.short_name
            if w.max_expected_percent is not None and change_percent is not None \
                    and abs(change_percent) > w.max_expected_percent:
                note = f"above the {direction} usually expected after {short} start (up to {w.max_expected_percent:g}%)"
            elif w.max_expected_percent is not None:
                note = f"within the ≤{w.max_expected_percent:g}% {direction} expected after {short} start"
            return {"event_id": w.event.id, "drug": w.event.drug, "drug_class": w.event.drug_class,
                    "note": note, "source": w.source, "window": {"start": w.start, "end": w.end}}
    return None


# ---------------------------------------------------------------- flags

def _from(ref_days: list[DayValue], value: float, label: str, note: str | None = None) -> dict:
    return {"label": label, "value": round(value, 4), "dates": [d.date for d in ref_days],
            "observation_ids": [i for d in ref_days for i in d.observation_ids],
            "report_ids": sorted({i for d in ref_days for i in d.report_ids}), "note": note}


def _flag(rule_id: str, a: AnalyteInfo, later: DayValue, ref_value: float, ref_label: str,
          ref_days: list[DayValue], windows: list[Window], ref_note: str | None = None) -> dict | None:
    change = pct_change(later.value, ref_value)
    if change is None or a.rcv_percent is None or abs(change) <= a.rcv_percent:   # both 1 decimal
        return None
    direction = "rise" if change > 0 else "fall"
    obs_ids = [i for d in ref_days for i in d.observation_ids] + later.observation_ids
    rep_ids = sorted({i for d in ref_days for i in d.report_ids} | set(later.report_ids))
    dates = sorted({d.date for d in ref_days} | {later.date})
    word = "rose" if direction == "rise" else "fell"
    return {
        "rule_id": rule_id, "level": "change", "analyte_id": a.id, "analyte_name": a.name, "unit": a.unit,
        "direction": direction, "date": later.date,
        "threshold": {"type": "rcv_percent", "value": a.rcv_percent, "rcv_status": a.rcv_status},
        "compared": {"from": _from(ref_days, ref_value, ref_label, ref_note), "to": later.ref(), "slope": None},
        "change_abs": round(later.value - ref_value, 4), "change_percent": change,
        "observation_ids": obs_ids, "report_ids": rep_ids, "dates": dates,
        "message": (f"{a.name} {word} {abs(change):.1f}% from the {ref_label} ({ref_value:.4g} → "
                    f"{later.value:.4g} {a.unit}), more than its reference change value of {a.rcv_percent:g}%."),
        "expected_effect": expected_effect(windows, later.date, direction, change),
        "drug_events_since_baseline": [], "source": a.rcv_source or None,
    }


def rcv_flags(a: AnalyteInfo, days: list[DayValue], base: Baseline, events: list[Event]) -> list[dict]:
    if a.rcv_percent is None:
        return []
    windows = windows_for(a.id, events)
    flags = []
    for prev, cur in zip(days, days[1:]):
        f = _flag("RCV_PREV", a, cur, prev.value, "previous result", [prev], windows)
        if f:
            flags.append(f)
    if base.value is not None and base.days:
        last_base = base.days[-1].date
        affecting = affecting_events(a.id, events)
        for cur in days:
            if cur.date <= last_base:
                continue
            f = _flag("RCV_BASELINE", a, cur, base.value, "baseline", base.days, windows, base.note)
            if f:
                f["drug_events_since_baseline"] = [event_ref(e) for e in affecting if last_base < e.date <= cur.date]
                flags.append(f)
    return flags


# ---------------------------------------------------------------- slope

def fit(days: list[DayValue]) -> float:
    t0 = days[0].date
    xs = [(d.date - t0).days / DAYS_PER_YEAR for d in days]
    ys = [d.value for d in days]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def slope(a: AnalyteInfo, days: list[DayValue], events: list[Event]) -> dict:
    windows = windows_for(a.id, events)
    cutoff = max((w.end for w in windows), default=None)
    last = max(windows, key=lambda w: w.end) if windows else None
    used = [d for d in days if cutoff is None or d.date > cutoff]
    excluded = [{"date": d.date, "observation_ids": d.observation_ids,
                 "reason": (f"on or before the end of the expected-effect window of {last.event.drug} "
                            f"started {last.event.date.isoformat()} (window ends {cutoff.isoformat()})")}
                for d in days if cutoff is not None and d.date <= cutoff]
    out = {"per_year": None, "unit": f"{a.unit} per year", "n_points": len(used), "span_days": 0,
           "first_date": used[0].date if used else None, "last_date": used[-1].date if used else None,
           "observation_ids": [i for d in used for i in d.observation_ids], "excluded_points": excluded,
           "status": SLOPE_FEW}
    if len(used) < SLOPE_MIN_POINTS:
        return out
    out["span_days"] = (used[-1].date - used[0].date).days
    out["per_year"] = round(fit(used), 3)
    out["status"] = SLOPE_OK if out["span_days"] >= SLOPE_MIN_SPAN_DAYS else SLOPE_SHORT
    return out


def slope_flags(a: AnalyteInfo, s: dict, days: list[DayValue]) -> list[dict]:
    if a.id != "egfr" or s["status"] != SLOPE_OK or s["per_year"] >= KDIGO_RAPID_EGFR_PER_YEAR:
        return []
    used = [d for d in days if d.date >= s["first_date"]]
    return [{
        "rule_id": "KDIGO_RAPID_EGFR", "level": "guideline", "analyte_id": a.id, "analyte_name": a.name,
        "unit": a.unit, "direction": "fall", "date": s["last_date"],
        "threshold": {"type": "slope_per_year", "value": KDIGO_RAPID_EGFR_PER_YEAR, "rcv_status": None},
        "compared": {"from": None, "to": None,
                     "slope": {"per_year": s["per_year"], "n_points": s["n_points"], "span_days": s["span_days"],
                               "first_date": s["first_date"], "last_date": s["last_date"]}},
        "change_abs": None, "change_percent": None,
        "observation_ids": s["observation_ids"], "report_ids": sorted({i for d in used for i in d.report_ids}),
        "dates": [d.date for d in used],
        "message": (f"eGFR fell by {abs(s['per_year']):.1f} {a.unit} per year over {s['span_days']} days "
                    f"({s['n_points']} results since the last drug window), faster than the KDIGO threshold "
                    f"of 5 per year."),
        "expected_effect": None, "drug_events_since_baseline": [], "source": KDIGO_SOURCE,
    }]


# ---------------------------------------------------------------- one analyte

def analyse(a: AnalyteInfo, points: list[Point], events: list[Event]) -> tuple[dict, list[dict]]:
    """(trend for the analyte, its flags). `points` in any order."""
    points = sorted(points, key=lambda p: (p.date, p.report_id, p.page, p.line, p.observation_id))
    windows = windows_for(a.id, events)
    days = day_values(points)
    trend = {
        "analyte_id": a.id, "name": a.name, "canonical_unit": a.unit, "rcv_percent": a.rcv_percent,
        "rcv_status": a.rcv_status, "baseline": None, "baseline_note": None, "baseline_dates": [],
        "baseline_observation_ids": [],
        "points": [{**_point_json(p), "censored": p.censored,
                    "in_window": [w.event.id for w in windows if w.contains(p.date)]} for p in points],
        "slope": None, "status": STATUS_OK,
    }
    if points and not days:
        trend["status"] = STATUS_CENSORED_ONLY
        return trend, []
    if len(days) < 2:
        trend["status"] = STATUS_INSUFFICIENT
        return trend, []
    base = baseline(days, a.id, events)
    trend.update(baseline=round(base.value, 4), baseline_note=base.note, baseline_dates=[d.date for d in base.days],
                 baseline_observation_ids=[i for d in base.days for i in d.observation_ids])
    s = slope(a, days, events)
    trend["slope"] = s
    return trend, rcv_flags(a, days, base, events) + slope_flags(a, s, days)


def _point_json(p: Point) -> dict:
    return {"observation_id": p.observation_id, "report_id": p.report_id, "date": p.date, "value": p.value,
            "comparator": p.comparator, "value_text": p.value_text, "unit_text": p.unit_text, "lab": p.lab,
            "page": p.page, "line": p.line}


def analyse_patient(analytes: list[AnalyteInfo], points_by_analyte: dict[str, list[Point]],
                    events: list[Event]) -> tuple[list[dict], list[dict]]:
    """(trends for analytes with data, in dictionary order; all flags newest first)."""
    events = sorted(events, key=lambda e: (e.date, e.id))
    trends, flags = [], []
    for a in analytes:
        pts = points_by_analyte.get(a.id) or []
        if not pts:
            continue
        t, f = analyse(a, pts, events)
        trends.append(t)
        flags.extend(f)
    flags.sort(key=lambda f: (f["date"], f["rule_id"], f["analyte_id"]), reverse=True)
    for f in flags:
        f["id"] = f"{f['rule_id']}:{f['analyte_id']}:{f['date'].isoformat()}"
    return trends, flags


# ---------------------------------------------------------------- medication response

def response(event: Event, analytes: dict[str, AnalyteInfo], points_by_analyte: dict[str, list[Point]],
             events: list[Event]) -> dict:
    c = event.klass
    events = sorted(events, key=lambda e: (e.date, e.id))
    out = {"event": event_ref(event) | {"generic": event.generic, "dose_text": event.dose_text,
                                         "drug_class_name": c.name if c else None},
           "analytes": [],
           "note": None if c else "drug not in the ChronoTrace catalogue: no expected effect is shown"}
    if c is None:
        return out
    ws, we = event.date + dt.timedelta(days=c.window_start), event.date + dt.timedelta(days=c.window_end)
    for eff in c.effects:
        a = analytes.get(eff.analyte_id)
        if a is None:
            continue
        days = day_values(points_by_analyte.get(eff.analyte_id) or [])
        before = next((d for d in reversed(days)
                       if d.date <= event.date and (event.date - d.date).days <= BEFORE_LOOKBACK_DAYS), None)
        after = next((d for d in days if ws <= d.date <= we), None)
        entry = {"analyte_id": a.id, "name": a.name, "unit": a.unit,
                 "expected": {"direction": eff.direction, "note": eff.note, "source": c.source,
                              "status": c.status, "applies": event.change == "start"},
                 "window": {"start": ws, "end": we}, "before": before.ref() if before else None,
                 "after": after.ref() if after else None, "change_abs": None, "change_percent": None,
                 "rcv_percent": a.rcv_percent, "rcv_status": a.rcv_status, "beyond_rcv": None,
                 "expected_effect": None, "confounders": [], "status": None}
        if not any(d.date >= ws for d in days):
            entry["status"] = RESP_TOO_EARLY
        elif before is None:
            entry["status"] = RESP_NO_BASELINE
        elif after is None:
            entry["status"] = RESP_NO_RESULT
        else:
            change = pct_change(after.value, before.value)
            entry.update(status=RESP_ASSESSED, change_abs=round(after.value - before.value, 4),
                         change_percent=change,
                         beyond_rcv=None if a.rcv_percent is None or change is None else abs(change) > a.rcv_percent)
            direction = "rise" if after.value > before.value else "fall"
            if event.change == "start" and change is not None and direction == eff.direction:
                win = [Window(event, eff.direction, eff.note, eff.max_expected_percent, ws, we, c.source)]
                entry["expected_effect"] = expected_effect(win, after.date, direction, change)
        until = after.date if after else we
        entry["confounders"] = [
            event_ref(o) | {"days_from_event": (o.date - event.date).days}
            for o in events if o.id != event.id and event.date - dt.timedelta(days=CONFOUNDER_LOOKBACK_DAYS) <= o.date <= until]
        out["analytes"].append(entry)
    return out
