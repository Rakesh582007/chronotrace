"""Trend engine on hand-built data (no model, no database). Expected numbers are computed by hand."""

import datetime as dt
import math

import pytest

from backend.demo import data as demo
from backend.trends import catalogue
from backend.trends import engine as E
from backend.trends.dictionary import analyte_infos, infos_by_id
from data import validate_analytes as va

D = dt.date.fromisoformat
INFO = infos_by_id()


def pts(analyte_values, start_id=1):
    """[(date, value[, comparator])] -> Points, one report per date."""
    out = []
    for i, item in enumerate(analyte_values):
        d, v, *c = item
        out.append(E.Point(start_id + i, 100 + i, D(d), v, c[0] if c else None))
    return out


def ev(i, drug, date, change="start"):
    cid, generic = catalogue.resolve(drug)
    return E.Event(i, drug, change, D(date), cid, generic)


def trend(aid, points, events=()):
    return E.analyse(INFO[aid], points, list(events))


# ---------------------------------------------------------------- formulas

@pytest.mark.parametrize("sex, age, creat, egfr", [
    ("male", 50, 1.0, 91.7), ("female", 60, 0.8, 84.3), ("male", 70, 2.0, 35.2), ("male", 40, 0.6, 125.1)])
def test_ckd_epi_2021(sex, age, creat, egfr):
    formula = next(a for a in va.load()["analytes"] if a["id"] == "egfr")["formula"]
    assert va.egfr_ckd_epi_2021(creat, age, sex, formula) == pytest.approx(egfr, abs=0.1)


def test_rcv_percent_matches_the_formula():
    checked = 0
    for a in va.load()["analytes"]:
        r = a["rcv"]
        if r.get("cv_i") and r.get("cv_a") and r.get("method") != "derived_from_creatinine":
            assert r["percent"] == pytest.approx(1.96 * math.sqrt(2) * math.hypot(r["cv_i"], r["cv_a"]), abs=0.1), a["id"]
            checked += 1
    assert checked >= 15
    assert INFO["hba1c"].rcv_percent == 6.3


# ---------------------------------------------------------------- baseline

def test_baseline_is_the_median_of_the_first_three_before_the_drug():
    t, _ = trend("hba1c", pts([("2023-01-01", 9.0), ("2023-02-01", 8.0), ("2023-03-01", 8.6), ("2023-04-01", 7.0),
                               ("2023-06-01", 6.8)]), [ev(1, "Metformin", "2023-05-01")])
    assert (t["baseline"], t["baseline_note"], t["baseline_dates"]) == (
        8.6, None, [D("2023-01-01"), D("2023-02-01"), D("2023-03-01")])


def test_fewer_than_two_before_the_drug_uses_the_first_three_with_a_note():
    t, _ = trend("hba1c", pts([("2023-01-01", 9.0), ("2023-06-01", 8.0), ("2023-07-01", 7.6)]),
                 [ev(1, "Metformin", "2023-03-01")])
    assert (t["baseline"], t["baseline_note"]) == (8.0, "includes on-treatment results")


def test_one_result_is_insufficient_and_censored_values_are_ignored():
    t, f = trend("hba1c", pts([("2023-01-01", 9.0)]))
    assert (t["status"], t["baseline"], t["slope"], f) == ("insufficient data", None, None, [])
    t, _ = trend("uacr", pts([("2023-01-01", 300, ">"), ("2023-02-01", 40), ("2023-03-01", 44), ("2023-04-01", 60)]))
    assert t["baseline"] == 44 and t["baseline_dates"] == [D("2023-02-01"), D("2023-03-01"), D("2023-04-01")]
    assert t["points"][0]["censored"] is True and t["points"][1]["censored"] is False


def test_censored_only_series():
    t, f = trend("uacr", pts([("2023-01-01", 300, ">"), ("2023-05-01", 300, ">")]))
    assert (t["status"], t["baseline"], f) == ("censored values only", None, []) and len(t["points"]) == 2


def test_same_date_values_are_averaged_for_calculations_but_all_kept():
    t, f = trend("creatinine", [E.Point(1, 10, D("2023-01-01"), 1.0), E.Point(2, 11, D("2023-01-01"), 1.2),
                                E.Point(3, 12, D("2023-02-01"), 1.1), E.Point(4, 13, D("2023-03-01"), 1.1)])
    assert len(t["points"]) == 4 and t["baseline"] == pytest.approx(1.1)
    assert f == []


# ---------------------------------------------------------------- report counts

def test_report_counts():
    series = [("2023-01-01", 1.0), ("2023-03-01", 1.3), ("2023-06-01", 1.35), ("2024-02-01", 1.6)]
    assert E.analyse_patient(list(analyte_infos()), {}, []) == ([], [])                         # 0 reports
    assert trend("creatinine", pts(series[:1]))[0]["status"] == "insufficient data"             # 1
    t, f = trend("creatinine", pts(series[:2]))                                                  # 2
    assert t["baseline"] == pytest.approx(1.15) and t["slope"]["per_year"] is None
    assert t["slope"]["status"] == "not enough points" and [x["rule_id"] for x in f] == ["RCV_PREV"]
    t, f = trend("creatinine", pts(series))                                                      # 3+
    assert t["slope"]["per_year"] is not None and t["slope"]["status"] == "ok"
    assert {x["rule_id"] for x in f} == {"RCV_PREV", "RCV_BASELINE"}


# ---------------------------------------------------------------- RCV flags

def test_rcv_prev_and_baseline_flags_carry_their_source():
    _, f = trend("creatinine", pts([("2023-01-01", 1.0), ("2023-02-01", 1.02), ("2023-03-01", 1.0),
                                    ("2023-06-01", 1.3)]))
    prev = next(x for x in f if x["rule_id"] == "RCV_PREV")
    assert (prev["direction"], prev["change_percent"], prev["threshold"]) == (
        "rise", 30.0, {"type": "rcv_percent", "value": 15.0, "rcv_status": "unverified"})
    assert prev["observation_ids"] == [3, 4] and prev["report_ids"] == [102, 103]
    assert prev["dates"] == [D("2023-03-01"), D("2023-06-01")] and prev["expected_effect"] is None
    base = next(x for x in f if x["rule_id"] == "RCV_BASELINE")
    assert base["compared"]["from"]["value"] == 1.0 and base["compared"]["from"]["observation_ids"] == [1, 2, 3]
    assert base["drug_events_since_baseline"] == []


def test_no_rcv_flags_without_an_established_rcv():
    t, f = trend("pp_glucose", pts([("2023-01-01", 140), ("2023-02-01", 260), ("2023-03-01", 150)]))
    assert (t["rcv_percent"], t["rcv_status"], f) == (None, "not established", [])
    assert t["baseline"] == 150 and t["slope"] is not None


def test_expected_effect_note_and_the_acei_threshold():
    ramipril = ev(7, "Ramipril", "2024-03-04")
    _, f = trend("creatinine", pts([("2024-01-01", 1.0), ("2024-02-01", 1.0), ("2024-02-20", 1.0),
                                    ("2024-04-01", 1.2)]), [ramipril])
    e = next(x for x in f if x["rule_id"] == "RCV_PREV")["expected_effect"]
    assert e["event_id"] == 7 and e["note"] == "within the ≤30% rise expected after ACEi/ARB start"
    assert e["source"].startswith("KDIGO 2024")
    _, f = trend("creatinine", pts([("2024-01-01", 1.0), ("2024-02-01", 1.0), ("2024-02-20", 1.0),
                                    ("2024-04-01", 1.4)]), [ramipril])
    assert next(x for x in f if x["rule_id"] == "RCV_PREV")["expected_effect"]["note"] == \
        "above the rise usually expected after ACEi/ARB start (up to 30%)"
    _, f = trend("creatinine", pts([("2024-01-01", 1.0), ("2024-02-01", 1.0), ("2024-02-20", 1.0),
                                    ("2024-04-01", 0.8)]), [ramipril])       # a fall is not the expected rise
    assert next(x for x in f if x["rule_id"] == "RCV_PREV")["expected_effect"] is None


def test_unknown_drugs_get_no_expected_effect_but_are_confounders():
    statin, ramipril = ev(1, "Atorvastatin", "2024-02-01"), ev(2, "Ramipril", "2024-03-04")
    assert statin.drug_class == "unknown"
    _, f = trend("creatinine", pts([("2023-10-01", 1.0), ("2023-12-01", 1.0), ("2024-02-10", 1.3)]), [statin])
    assert all(x["expected_effect"] is None for x in f)
    points = {"creatinine": pts([("2024-02-20", 1.0), ("2024-04-01", 1.2)])}
    r = E.response(ramipril, INFO, points, [statin, ramipril])
    cre = next(a for a in r["analytes"] if a["analyte_id"] == "creatinine")
    assert [(c["drug"], c["days_from_event"]) for c in cre["confounders"]] == [("Atorvastatin", -32)]
    assert E.response(statin, INFO, points, [statin, ramipril])["analytes"] == []


def test_analytes_not_affected_by_any_drug_ignore_drug_events():
    t, _ = trend("tsh", pts([("2023-01-01", 2.0), ("2023-06-01", 2.6), ("2023-09-01", 2.2), ("2024-01-01", 2.5)]),
                 [ev(1, "Ramipril", "2023-02-01")])
    assert t["baseline"] == 2.2 and t["baseline_note"] is None and t["slope"]["excluded_points"] == []


# ---------------------------------------------------------------- slope

def test_slope_is_exact_on_a_straight_line():
    start = D("2020-01-01")
    line = [((start + dt.timedelta(days=d)).isoformat(), 80 - 4 * d / 365.25) for d in (0, 200, 400, 800)]
    t, f = trend("egfr", pts(line))
    assert t["slope"]["per_year"] == pytest.approx(-4.0, abs=1e-6) and t["slope"]["status"] == "ok"
    assert not any(x["rule_id"] == "KDIGO_RAPID_EGFR" for x in f)       # -4 is not below -5


def test_short_span_gives_a_slope_but_no_guideline_flag():
    t, f = trend("egfr", pts([("2024-01-01", 70), ("2024-04-01", 66), ("2024-08-01", 60)]))
    assert t["slope"]["status"] == "not enough span" and t["slope"]["per_year"] < -5
    assert not any(x["rule_id"] == "KDIGO_RAPID_EGFR" for x in f)


def test_slope_excludes_points_up_to_the_end_of_the_drug_window():
    t, _ = trend("egfr", pts([("2024-01-01", 80), ("2024-03-01", 70), ("2024-06-01", 69), ("2025-01-01", 68),
                              ("2025-06-01", 67)]), [ev(3, "Ramipril", "2024-02-15")])
    s = t["slope"]
    assert [x["date"] for x in s["excluded_points"]] == [D("2024-01-01"), D("2024-03-01")]
    assert "Ramipril started 2024-02-15" in s["excluded_points"][0]["reason"]
    assert s["n_points"] == 3 and s["first_date"] == D("2024-06-01")


# ---------------------------------------------------------------- the second patient (addendum)

def test_female_patient_two_reports_censored_uacr_unknown_drug():
    # Hand-computed CKD-EPI 2021, female, age 49 (2024 - 1975): 142 x (Scr/0.7)^-1.200 x 0.9938^49 x 1.012
    e1, e2 = 78.3693, 65.1343                               # Scr 0.90 and 1.05
    formula = next(a for a in va.load()["analytes"] if a["id"] == "egfr")["formula"]
    assert va.egfr_ckd_epi_2021(0.90, 49, "female", formula) == pytest.approx(e1, abs=1e-4)
    assert va.egfr_ckd_epi_2021(1.05, 49, "female", formula) == pytest.approx(e2, abs=1e-4)
    points = {
        "creatinine": pts([("2024-01-10", 0.90), ("2024-07-15", 1.05)], 1),
        "egfr": pts([("2024-01-10", e1), ("2024-07-15", e2)], 3),
        "hba1c": pts([("2024-01-10", 6.1), ("2024-07-15", 6.3)], 5),
        "uacr": pts([("2024-01-10", 30, "<"), ("2024-07-15", 45)], 7),
    }
    statin = ev(1, "Atorvastatin", "2024-03-01")
    trends, flags = E.analyse_patient(list(analyte_infos()), points, [statin])
    by = {t["analyte_id"]: t for t in trends}
    assert by["creatinine"]["baseline"] == pytest.approx(0.975) and by["creatinine"]["baseline_note"] is None
    assert by["uacr"]["status"] == "insufficient data" and by["uacr"]["points"][0]["censored"] is True
    assert by["hba1c"]["status"] == "ok" and by["creatinine"]["slope"]["status"] == "not enough points"
    got = sorted((f["rule_id"], f["analyte_id"], f["direction"], f["change_percent"]) for f in flags)
    assert got == [("RCV_PREV", "creatinine", "rise", 16.7), ("RCV_PREV", "egfr", "fall", -16.9)]
    assert all(f["expected_effect"] is None for f in flags)
    assert E.response(statin, INFO, points, [statin])["note"].startswith("drug not in the ChronoTrace catalogue")


# ---------------------------------------------------------------- the demo patient (K. Selvam)

def demo_patient(upto: str):
    ids = [r.id for r in demo.REPORTS]
    points, oid = {}, 1
    for rid, r in enumerate(demo.REPORTS[:ids.index(upto) + 1], 1):
        for aid, v in demo.values(r).items():
            points.setdefault(aid, []).append(E.Point(oid, rid, r.date, v, lab=demo.LABS[r.lab]))
            oid += 1
    events = [ev(i, e["drug"], e["date"]) for i, e in enumerate(demo.EVENTS, 1)]
    return points, events


def by_drug(points, events, drug):
    e = next(x for x in events if x.drug == drug)
    return {a["analyte_id"]: a for a in E.response(e, INFO, points, events)["analytes"]}


@pytest.mark.parametrize("r", demo.REPORTS, ids=lambda r: r.id)
def test_demo_egfr_column_matches_ckd_epi(r):
    assert demo.computed_egfr(r) == pytest.approx(r.egfr, abs=0.05)


def test_demo_metformin_response():
    points, events = demo_patient("R9")
    h = by_drug(points, events, "Metformin")["hba1c"]
    # before = mean(R1 8.9, R2 8.7) = 8.8 (the last 2-3 results within 180 days before the start)
    assert h["status"] == "assessed" and (h["before"]["value"], h["after"]["value"]) == (8.8, 7.4)
    assert [v["date"] for v in h["before_values"]] == [D("2023-06-12"), D("2023-09-14")] and h["before_note"] is None
    assert h["after"]["date"] == D("2024-02-15")
    assert h["change_percent"] == -15.9 and h["beyond_rcv"] is True and h["confounders"] == []
    assert h["cross_lab"] is True and h["cross_lab_note"] == E.CROSS_LAB_NOTE          # labs A, B -> C
    assert h["expected_effect"]["note"] == "an HbA1c fall is expected about 3 months after starting metformin"
    points, events = demo_patient("R3")
    assert by_drug(points, events, "Metformin")["hba1c"]["status"] == "too early to assess"


def test_demo_ramipril_response():
    points, events = demo_patient("R9")
    r = by_drug(points, events, "Ramipril")
    c = r["creatinine"]
    # before = mean(R2 1.13, R3 1.11, R4 1.11) = 1.1167 -> R5 1.29: +15.5%, still beyond the 15.0% RCV
    assert (c["before"]["value"], c["after"]["value"], c["change_percent"], c["beyond_rcv"]) == (1.1167, 1.29, 15.5, True)
    assert c["rcv_percent"] == 15.0 and c["confounders"] == [] and c["cross_lab"] is True
    assert c["expected_effect"]["note"] == "within the ≤30% rise expected after ACEi/ARB start"
    e = r["egfr"]
    assert e["change_percent"] == -16.2 and e["expected_effect"] is not None      # mean(76.76, 78.42, 77.94) -> 65.08
    assert r["potassium"]["beyond_rcv"] is False


def test_demo_empagliflozin_response():
    points, events = demo_patient("R9")
    r = by_drug(points, events, "Empagliflozin")
    e = r["egfr"]
    # only R5 is after ramipril (an earlier drug affecting eGFR): a single prior value
    assert (round(e["before"]["value"], 1), round(e["after"]["value"], 1)) == (65.1, 61.6)
    assert e["before_note"] == "single prior value" and len(e["before_values"]) == 1
    # -5.3% from the stored eGFRs (65.08 -> 61.62); the spec's -5.4% used the 1-decimal table (65.1 -> 61.6).
    assert e["change_percent"] == -5.3 and e["beyond_rcv"] is False
    assert "dip" in e["expected_effect"]["note"]
    assert [(c["drug"], c["days_from_event"]) for c in e["confounders"]] == [("Ramipril", -63)]
    cr = r["creatinine"]                                                  # the SGLT2 inhibitor creatinine effect
    assert (cr["before"]["value"], cr["after"]["value"], cr["change_percent"]) == (1.29, 1.35, 4.7)
    assert "creatinine rise" in cr["expected_effect"]["note"]


def test_demo_egfr_slope_before_r10_is_too_short_for_the_guideline_flag():
    points, events = demo_patient("R9")
    trends, flags = E.analyse_patient(list(analyte_infos()), points, events)
    s = next(t for t in trends if t["analyte_id"] == "egfr")["slope"]
    assert s["n_points"] == 3 and s["first_date"] == D("2024-10-15") and s["span_days"] == 321
    assert s["per_year"] == pytest.approx(-6.6, abs=0.05) and s["status"] == "not enough span"
    assert len(s["excluded_points"]) == 6                                  # R1-R6
    assert not any(f["rule_id"] == "KDIGO_RAPID_EGFR" for f in flags)
    assert not any(f["analyte_id"] in ("potassium", "fasting_glucose", "uacr") for f in flags)


def test_demo_after_r10_the_trend_fires_the_kdigo_flag():
    points, events = demo_patient("R10")
    trends, flags = E.analyse_patient(list(analyte_infos()), points, events)
    s = next(t for t in trends if t["analyte_id"] == "egfr")["slope"]
    assert (round(s["per_year"], 1), s["span_days"], s["status"]) == (-7.1, 503, "ok")
    k = [f for f in flags if f["rule_id"] == "KDIGO_RAPID_EGFR"]
    assert len(k) == 1 and k[0]["level"] == "guideline" and k[0]["threshold"]["value"] == -5.0
    assert k[0]["dates"] == [D("2024-10-15"), D("2025-03-10"), D("2025-09-01"), D("2026-03-02")]
    steps = [f for f in flags if f["rule_id"] == "RCV_PREV" and f["analyte_id"] == "egfr" and f["date"] >= D("2024-10-15")]
    assert steps == []                                                    # no single step beyond RCV 15.4%
    egfr = [v["value"] for v in next(t for t in trends if t["analyte_id"] == "egfr")["points"]][6:]
    assert [round((b / a - 1) * 100, 1) for a, b in zip(egfr, egfr[1:])] == [-4.1, -5.1, -7.0]


def test_demo_engine_does_not_report_the_naive_slope():
    points, events = demo_patient("R10")
    naive = E.fit(E.day_values(points["egfr"]))
    assert naive == pytest.approx(-9.8, abs=0.05)                         # driven by the planned ACEi dip
    trends, _ = E.analyse_patient(list(analyte_infos()), points, events)
    s = next(t for t in trends if t["analyte_id"] == "egfr")["slope"]
    assert s["per_year"] != pytest.approx(naive, abs=0.5)


# ---------------------------------------------------------------- guardrail review (cross-lab, before, baseline)

def test_demo_flag_counts_with_baseline_flags_only_for_the_latest_result():
    for upto, n in (("R9", 6), ("R10", 7)):
        points, events = demo_patient(upto)
        trends, flags = E.analyse_patient(list(analyte_infos()), points, events)
        assert len(flags) == n, upto
        base = [f for f in flags if f["rule_id"] == "RCV_BASELINE"]
        assert sorted(f["analyte_id"] for f in base) == ["creatinine", "egfr", "hba1c"]
        assert {f["date"] for f in base} == {demo.REPORTS[len(points["egfr"]) - 1].date}
        assert next(t for t in trends if t["analyte_id"] == "egfr")["baseline"] == pytest.approx(78.42)
        assert all(f["cross_lab"] is True for f in flags)                 # the demo's labs alternate


def lab_points(values):
    """[(date, value, lab)] -> Points."""
    return [E.Point(i + 1, 100 + i, D(d), v, lab=lab) for i, (d, v, lab) in enumerate(values)]


def test_cross_lab_is_labelled_only_when_labs_differ():
    same = lab_points([("2023-01-01", 1.0, "A"), ("2023-02-01", 1.3, "A")])
    f = trend("creatinine", same)[1][0]
    assert (f["cross_lab"], f["cross_lab_note"]) == (False, None)
    mixed = lab_points([("2023-01-01", 1.0, "A"), ("2023-02-01", 1.3, "B")])
    f = trend("creatinine", mixed)[1][0]
    assert f["cross_lab"] is True
    assert f["cross_lab_note"] == "values from different labs; between-lab variation is larger than the RCV assumes"
    assert f["compared"]["from"]["labs"] == ["A"] and f["compared"]["to"]["labs"] == ["B"]


def test_before_is_the_mean_of_the_last_three_after_an_earlier_drug():
    points = {"creatinine": lab_points([("2023-10-01", 0.9, "A"), ("2023-11-01", 1.0, "A"), ("2023-12-01", 1.1, "A"),
                                        ("2024-01-01", 1.2, "A"), ("2024-01-20", 1.3, "A"), ("2024-02-20", 1.5, "A")])}
    ram = ev(2, "Ramipril", "2024-02-01")
    c = next(a for a in E.response(ram, INFO, points, [ram])["analytes"] if a["analyte_id"] == "creatinine")
    assert c["before"]["value"] == pytest.approx(1.2) and len(c["before_values"]) == 3    # mean(1.1, 1.2, 1.3)
    empa = ev(3, "Empagliflozin", "2024-02-10")       # ramipril (earlier, affects creatinine) limits the look-back
    c = next(a for a in E.response(empa, INFO, points, [ram, empa])["analytes"] if a["analyte_id"] == "creatinine")
    assert c["status"] == "no baseline" and c["before"] is None


def test_every_start_carries_the_regression_to_the_mean_caveat():
    points = {"hba1c": lab_points([("2023-01-01", 9.0, "A"), ("2023-05-01", 7.5, "A")])}
    start, stop = ev(1, "Metformin", "2023-01-10"), ev(2, "Metformin", "2023-03-01", change="stop")
    assert E.response(start, INFO, points, [start, stop])["caveat"] == (
        "Some change is expected after a treatment started for a high value (regression to the mean); "
        "adherence is not recorded.")
    assert E.response(stop, INFO, points, [start, stop])["caveat"] is None
    h = E.response(start, INFO, points, [start])["analytes"][0]
    assert h["before_note"] == "single prior value"
