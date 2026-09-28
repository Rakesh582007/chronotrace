"""Step 9b: eGFR projection to the next KDIGO category, and the time since the last test."""

import datetime as dt

from backend.trends import engine as E
from backend.trends.dictionary import analyte_infos, infos_by_id
from tests.test_trends_engine import demo_patient

INFO = infos_by_id()


def egfr_trend(upto):
    points, events = demo_patient(upto)
    trends, _ = E.analyse_patient(list(analyte_infos()), points, events)
    return next(t for t in trends if t["analyte_id"] == "egfr")


def test_projection_appears_with_the_kdigo_slope_after_r10():
    assert egfr_trend("R9")["projection"] is None             # slope span < 365 days before R10
    p = egfr_trend("R10")["projection"]
    assert (p["threshold"], p["category"], p["n_points"]) == (45, "G3b", 4)
    assert p["date_earliest"] < p["date"] < p["date_latest"]
    assert p["date"] == dt.date(2027, 6, 23) and p["per_year"] == -7.081
    assert "not a forecast" in p["note"]


def test_no_projection_for_rising_or_other_analytes():
    points, events = demo_patient("R10")
    trends, _ = E.analyse_patient(list(analyte_infos()), points, events)
    assert all(t["projection"] is None for t in trends if t["analyte_id"] != "egfr")


def test_t_values():
    assert E.t95(2) == 4.303 and E.t95(11) == 2.179 and E.t95(100) == 2.0


def test_last_test_against_the_interval():
    trend = egfr_trend("R10")
    hba1c = {"points": [{"date": dt.date(2026, 3, 2)}]}
    got = E.last_test(INFO["hba1c"], hba1c, dt.date(2026, 9, 28))
    assert got["days_since"] == 210 and got["interval_months"] == 6 and got["longer_than_interval"] is True
    assert E.last_test(INFO["egfr"], trend, dt.date(2026, 9, 28))["longer_than_interval"] is False
    assert E.last_test(INFO["potassium"], trend, dt.date(2026, 9, 28)) is None      # no interval listed
