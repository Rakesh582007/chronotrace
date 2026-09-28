"""Step 9: position against a guideline target, expected-vs-observed verdicts, and changes of lab."""

import datetime as dt

import pytest

from backend.trends import engine as E
from backend.trends.dictionary import infos_by_id
from tests.test_trends_engine import by_drug, demo_patient, ev

INFO = infos_by_id()
T = E.Target(low=0.4, high=4.0, label="0.4–4.0", source="s", status="unverified")


@pytest.mark.parametrize("before, after, want", [
    (9.0, 8.4, "toward"), (8.4, 9.2, "away"), (2.0, 3.0, "within"), (9.0, 9.0, "unchanged"),
    (9.0, 3.9, "toward"), (3.0, 4.6, "away"), (0.3, 0.2, "away"), (None, 2.0, None)])
def test_target_direction(before, after, want):
    assert T.direction(before, after) == want


def test_one_sided_targets_from_the_dictionary():
    assert INFO["hba1c"].target.high == 7.0 and INFO["hba1c"].target.low is None
    assert INFO["egfr"].target_direction(58.1, 54.1) == "away"
    assert INFO["hba1c"].target_direction(8.8, 6.9) == "toward"
    assert INFO["creatinine"].target is None and INFO["creatinine"].target_direction(1.1, 1.5) is None


def test_selvam_flags_and_trends_carry_the_target():
    points, events = demo_patient("R10")
    trends, flags = E.analyse_patient(list(INFO.values()), points, events)
    egfr = next(t for t in trends if t["analyte_id"] == "egfr")
    assert egfr["target"]["label"] == "≥ 60" and egfr["target"]["status"] == "verified"
    kdigo = next(f for f in flags if f["rule_id"] == "KDIGO_RAPID_EGFR")
    assert kdigo["target_direction"] == "away"
    hba1c = next(f for f in flags if f["rule_id"] == "RCV_BASELINE" and f["analyte_id"] == "hba1c")
    assert hba1c["target_direction"] == "toward"


def test_selvam_expected_changes_are_all_seen():
    points, events = demo_patient("R9")
    assert by_drug(points, events, "Metformin")["hba1c"]["verdict"] == "seen"
    ram = by_drug(points, events, "Ramipril")
    assert ram["creatinine"]["verdict"] == "seen" and "beyond its reference change value" in ram["creatinine"]["verdict_note"]
    assert ram["egfr"]["verdict"] == "seen"                      # small effect: within noise still counts
    emp = by_drug(points, events, "Empagliflozin")
    assert emp["egfr"]["verdict"] == "seen" and "(a small change is expected)" in emp["egfr"]["verdict_note"]


def _series(aid, values):
    """(points, labs) with one result per ~90 days: values as (value, lab)."""
    d0 = dt.date(2024, 1, 1)
    return {aid: [E.Point(i, i, d0 + dt.timedelta(days=90 * i), v, lab=lab) for i, (v, lab) in enumerate(values, 1)]}


def test_levothyroxine_not_seen_and_opposite():
    d0 = dt.date(2024, 1, 1)
    start = d0 + dt.timedelta(days=200)
    base = [E.Point(1, 1, d0 + dt.timedelta(days=100), 9.0, lab="A"), E.Point(2, 2, d0 + dt.timedelta(days=180), 9.0, lab="A")]
    for after, want in [(8.4, "not seen"), (3.0, "seen"), (15.0, "opposite")]:
        pts = {"tsh": base + [E.Point(3, 3, start + dt.timedelta(days=60), after, lab="A")]}
        e = ev(1, "Levothyroxine", start.isoformat())
        r = {a["analyte_id"]: a for a in E.response(e, INFO, pts, [e])["analytes"]}
        assert r["tsh"]["verdict"] == want, after


def test_dose_changes_get_no_verdict():
    d0 = dt.date(2024, 1, 1)
    pts = {"tsh": [E.Point(1, 1, d0, 9.0, lab="A"), E.Point(2, 2, d0 + dt.timedelta(days=60), 3.0, lab="A")]}
    e = ev(1, "Levothyroxine", (d0 + dt.timedelta(days=1)).isoformat(), change="dose_change")
    tsh = next(a for a in E.response(e, INFO, pts, [e])["analytes"] if a["analyte_id"] == "tsh")
    assert tsh["verdict"] is None


def test_lab_change_when_the_same_lab_agrees():
    points = _series("tsh", [(8.8, "A"), (8.4, "A"), (3.9, "B"), (8.1, "A")])
    _, flags = E.analyse_patient(list(INFO.values()), points, [])
    prev = sorted((f for f in flags if f["rule_id"] == "RCV_PREV"), key=lambda f: f["date"])
    assert [(f["lab_change"]["from_lab"], f["lab_change"]["to_lab"], f["lab_change"]["same_lab_agrees"]) for f in prev] == [
        ("A", "B", True), ("B", "A", True)]
    assert prev[0]["lab_change"]["same_lab_report_ids"] == [4]      # the next lab A result
    assert prev[1]["lab_change"]["same_lab_report_ids"] == [2]      # the previous lab A result
    assert "may reflect the difference between the labs" in prev[0]["lab_change"]["note"]


def test_lab_change_when_the_same_lab_shows_a_change_too():
    points = _series("tsh", [(8.4, "A"), (3.9, "B"), (3.5, "A")])
    _, flags = E.analyse_patient(list(INFO.values()), points, [])
    step = next(f for f in flags if f["rule_id"] == "RCV_PREV")
    assert step["lab_change"]["same_lab_agrees"] is False
    assert "show a change as well" in step["lab_change"]["note"]


def test_no_lab_change_within_one_lab_or_for_baseline_flags():
    points = _series("tsh", [(8.8, "A"), (8.4, "A"), (3.9, "A")])
    _, flags = E.analyse_patient(list(INFO.values()), points, [])
    assert flags and all(f["lab_change"] is None for f in flags)
