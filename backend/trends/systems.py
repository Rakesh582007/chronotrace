"""Body systems for the patient page: analytes grouped as in data/analytes.yaml (`systems`), each system
summarised from the trend engine's output. Presentation only: every number and flag comes from the engine.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from functools import lru_cache

from data import validate_analytes as va

from .engine import AnalyteInfo, pct_change

GUIDELINE, CHANGED, STABLE, NO_DATA = "guideline", "changed", "stable", "no_data"


@dataclass(frozen=True)
class BodySystem:
    id: str
    name: str
    order: int
    headline: str                     # analyte id shown on the system's card
    analytes: tuple[str, ...]         # dictionary order


@lru_cache(maxsize=1)
def body_systems() -> tuple[BodySystem, ...]:
    data = va.load()
    members: dict[str, list[str]] = {}
    for a in data["analytes"]:
        members.setdefault(a["system"], []).append(a["id"])
    return tuple(sorted((BodySystem(s["id"], s["name"], s["order"], s["headline"], tuple(members.get(s["id"], ())))
                         for s in data["systems"]), key=lambda s: s.order))


def flag_counts(flags: list[dict]) -> dict[str, int]:
    """guideline flags; change flags without an expected drug effect; change flags explained by one."""
    change = [f for f in flags if f["level"] == "change"]
    return {"guideline": sum(f["level"] == "guideline" for f in flags),
            "change": sum(f["expected_effect"] is None for f in change),
            "expected": sum(f["expected_effect"] is not None for f in change)}


def change_vs_baseline(trend: dict) -> float | None:
    """Latest result against the baseline, as RCV_BASELINE compares them: the mean of the latest date's
    non-censored results, only when that date is after the baseline period."""
    values = [p for p in trend["points"] if not p["censored"]]
    if trend["baseline"] is None or not values or not trend["baseline_dates"]:
        return None
    latest = max(p["date"] for p in values)
    if latest <= max(trend["baseline_dates"]):
        return None
    return pct_change(statistics.mean(p["value"] for p in values if p["date"] == latest), trend["baseline"])


def headline(info: AnalyteInfo, trend: dict | None) -> dict:
    out = {"analyte_id": info.id, "name": info.name, "unit": info.unit, "latest": None, "baseline": None,
           "change_vs_baseline_percent": None, "slope": None}
    if trend is None or not trend["points"]:
        return out
    last = trend["points"][-1]                          # points are sorted by date
    out["latest"] = {k: last[k] for k in ("date", "value", "value_text", "comparator", "censored", "report_id")}
    out.update(baseline=trend["baseline"], change_vs_baseline_percent=change_vs_baseline(trend),
               slope=trend["slope"])
    return out


def summarise(systems: tuple[BodySystem, ...], infos: dict[str, AnalyteInfo], trends: list[dict],
              flags: list[dict]) -> list[dict]:
    """One entry per system, in order. Status: guideline if any guideline flag, changed if any change flag
    (with or without an expected drug effect), stable when there are results but no flag, no_data otherwise.
    Flags cover the patient's whole history, like GET /patients/{id}/flags."""
    trend_by_id = {t["analyte_id"]: t for t in trends}
    out = []
    for s in systems:
        counts = flag_counts([f for f in flags if f["analyte_id"] in s.analytes])
        with_data = [a for a in s.analytes if trend_by_id.get(a, {}).get("points")]
        if not with_data:
            status = NO_DATA
        elif counts["guideline"]:
            status = GUIDELINE
        elif counts["change"] or counts["expected"]:
            status = CHANGED
        else:
            status = STABLE
        out.append({"id": s.id, "name": s.name, "order": s.order, "status": status,
                    "headline": headline(infos[s.headline], trend_by_id.get(s.headline)),
                    "analytes_with_data": [{"analyte_id": a, "name": infos[a].name} for a in with_data],
                    "flag_counts": counts})
    return out
