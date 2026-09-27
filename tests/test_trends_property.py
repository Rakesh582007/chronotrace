"""Property test: 200 random patients built from analytes.yaml and drugs.yaml (fixed seeds).

For every patient: no exceptions; every flag has a rule and a source report; no flag uses a censored
value; and the results are identical whatever order the reports (and events) arrive in.
"""

import datetime as dt
import json
import random

import pytest

from backend.trends import catalogue
from backend.trends import engine as E
from backend.trends.dictionary import analyte_infos, infos_by_id
from data import validate_analytes as va

ANALYTES = va.load()["analytes"]
INFO = infos_by_id()
DRUGS = [g for c in catalogue.catalogue()["classes"] for g in c["generics"]] + ["Atorvastatin", "Aspirin", "Tab XYZ 5"]


def typical(a) -> float:
    lo, hi = next(((r.get("low"), r.get("high")) for r in a["reference_ranges"]), (None, None))
    lo = lo if lo is not None else (hi or 10) * 0.3
    hi = hi if hi is not None else lo * 2
    return (lo + hi) / 2


def random_patient(seed: int):
    rng = random.Random(seed)
    n_reports = rng.choice([0, 1, 2, 3, 4, 6, 9, 14])
    start = dt.date(2015, 1, 1) + dt.timedelta(days=rng.randint(0, 3000))
    dates = sorted(start + dt.timedelta(days=rng.randint(0, 2200)) for _ in range(n_reports))
    chosen = rng.sample(ANALYTES, rng.randint(1, len(ANALYTES)))
    points: dict[str, list[E.Point]] = {}
    oid = 0
    for rid, d in enumerate(dates, 1):
        for a in chosen:
            if rng.random() < 0.2:
                continue                                   # not every test on every report
            for _ in range(2 if rng.random() < 0.05 else 1):      # sometimes two values on one date
                oid += 1
                v = round(typical(a) * rng.uniform(0.4, 1.9), 3)
                comp = rng.choice(["<", ">"]) if rng.random() < 0.15 else None
                points.setdefault(a["id"], []).append(E.Point(oid, rid, d, v, comp, page=1, line=oid))
    events = []
    for i in range(rng.randint(0, 5)):
        drug = rng.choice(DRUGS)
        cid, generic = catalogue.resolve(drug)
        d = start + dt.timedelta(days=rng.randint(-200, 2400))
        events.append(E.Event(i + 1, drug, rng.choice(["start", "start", "stop", "dose_change"]), d, cid, generic))
    return points, events


def run(points, events):
    trends, flags = E.analyse_patient(list(analyte_infos()), points, events)
    responses = [E.response(e, INFO, points, events) for e in sorted(events, key=lambda e: e.id)]
    return json.loads(json.dumps({"trends": trends, "flags": flags, "responses": responses}, default=str))


SEEDS = range(200)


@pytest.mark.parametrize("seed", SEEDS)
def test_random_patient(seed):
    points, events = random_patient(seed)
    out = run(points, events)                              # 1. no exceptions

    censored = {p.observation_id for ps in points.values() for p in ps if p.censored}
    all_ids = {p.observation_id for ps in points.values() for p in ps}
    report_of = {p.observation_id: p.report_id for ps in points.values() for p in ps}
    for f in out["flags"]:                                 # 2. every flag has a rule and a source report
        assert f["rule_id"] in {"RCV_PREV", "RCV_BASELINE", "KDIGO_RAPID_EGFR"}
        assert f["report_ids"] and f["observation_ids"] and f["dates"]
        assert set(f["observation_ids"]) <= all_ids
        assert set(f["report_ids"]) == {report_of[i] for i in f["observation_ids"]}
        assert not set(f["observation_ids"]) & censored   # 3. no flag uses a censored value
        if f["rule_id"] != "KDIGO_RAPID_EGFR":
            assert f["threshold"]["value"] is not None and abs(f["change_percent"]) > f["threshold"]["value"]
    for r in out["responses"]:
        for a in r["analytes"]:
            for side in ("before", "after"):
                if a[side]:
                    assert not set(a[side]["observation_ids"]) & censored

    rng = random.Random(10_000 + seed)                     # 4. same results in any upload order
    shuffled = {k: rng.sample(v, len(v)) for k, v in rng.sample(list(points.items()), len(points))}
    assert run(shuffled, rng.sample(events, len(events))) == out


def test_the_random_patients_cover_the_edge_cases():
    """The generator above actually produces the situations the property is meant to cover."""
    seen = set()
    for seed in SEEDS:
        points, events = random_patient(seed)
        out = run(points, events)
        seen |= {t["status"] for t in out["trends"]}
        seen |= {f["rule_id"] for f in out["flags"]}
        seen |= {"expected_effect" for f in out["flags"] if f["expected_effect"]}
        seen |= {"unknown drug" for e in events if e.drug_class == "unknown"}
        seen |= {"no rcv" for t in out["trends"] if t["rcv_percent"] is None}
        seen |= {"no patient data" for _ in [0] if not points}
        seen |= {a["status"] for r in out["responses"] for a in r["analytes"]}
    assert {"ok", "insufficient data", "censored values only", "RCV_PREV", "RCV_BASELINE", "expected_effect",
            "unknown drug", "no rcv", "no patient data", "assessed", "too early to assess", "no baseline"} <= seen
