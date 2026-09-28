"""Body systems: the dictionary's `systems` list, its validator, and GET /patients/{id}/systems (step 7)."""

import copy
import datetime as dt

import pytest
from backend.demo import data as demo
from backend.demo.reports import write_pdf
from backend.demo.seed import seed
from backend.main import app
from backend.trends import systems as body
from backend.trends.dictionary import infos_by_id
from data import validate_analytes as va
from tests.conftest import signed_in_client, use_fresh_database

SPEC = {
    "kidney": ("Kidney", "egfr", {"egfr", "creatinine", "urea", "uacr"}),
    "glucose": ("Glucose control", "hba1c", {"hba1c", "fasting_glucose", "pp_glucose"}),
    "electrolytes": ("Electrolytes", "potassium", {"sodium", "potassium"}),
    "lipids": ("Lipids", "ldl", {"total_cholesterol", "ldl", "hdl", "triglycerides"}),
    "liver": ("Liver", "alt", {"alt", "ast"}),
    "thyroid": ("Thyroid", "tsh", {"tsh", "free_t4"}),
    "blood_count": ("Blood count", "haemoglobin", {"haemoglobin", "platelets", "wbc"}),
}


# ---------------------------------------------------------------- dictionary

def test_systems_match_the_spec():
    got = body.body_systems()
    assert [s.id for s in got] == list(SPEC)                     # in card order
    assert {s.id: (s.name, s.headline, set(s.analytes)) for s in got} == SPEC


@pytest.mark.parametrize("change,error", [
    (lambda d: d.pop("systems"), "top-level 'systems' list is missing"),
    (lambda d: d["analytes"][0].update(system="bones"), "system 'bones' is not in the systems list"),
    (lambda d: d["analytes"][0].pop("system"), "missing field 'system'"),
    (lambda d: d["systems"][0].update(headline="hba1c"), "headline 'hba1c' is not one of its analytes"),
    (lambda d: d["systems"].append({"id": "bones", "name": "Bones", "order": 8, "headline": "x"}), "has no analytes"),
    (lambda d: d["systems"][1].update(order=1), "order must be a whole number"),
    (lambda d: d["systems"][1].update(id="kidney"), "duplicate id"),
], ids=["no-list", "unknown-system", "no-system", "foreign-headline", "empty-system", "same-order", "duplicate"])
def test_validator_rejects_bad_systems(change, error):
    data = copy.deepcopy(va.load())
    assert va.validate(data) == []
    change(data)
    assert any(error in e for e in va.validate(data)), va.validate(data)


# ---------------------------------------------------------------- status rules (pure)

def trend(analyte_id, values, baseline_dates=(), baseline=None, censored_last=False):
    points = [{"date": dt.date(2025, 1, 1) + dt.timedelta(days=30 * i), "value": v, "value_text": str(v),
               "comparator": None, "censored": False, "report_id": 100 + i} for i, v in enumerate(values)]
    if censored_last:
        points[-1].update(comparator="<", censored=True, value_text="<5")
    return {"analyte_id": analyte_id, "points": points, "baseline": baseline, "slope": None,
            "baseline_dates": [points[i]["date"] for i in baseline_dates]}


def flag(analyte_id, level, expected=False):
    return {"analyte_id": analyte_id, "level": level, "expected_effect": {"note": "x"} if expected else None}


def statuses(trends, flags):
    return {s["id"]: s["status"] for s in body.summarise(body.body_systems(), infos_by_id(), trends, flags)}


def test_status_precedence():
    trends = [trend("egfr", [80, 70]), trend("hba1c", [8, 7]), trend("potassium", [4.5, 4.6]), trend("tsh", [2, 3])]
    flags = [flag("creatinine", "change"), flag("egfr", "guideline"), flag("hba1c", "change", expected=True)]
    got = statuses(trends, flags)
    assert got == {"kidney": "guideline", "glucose": "changed", "electrolytes": "stable", "lipids": "no_data",
                   "liver": "no_data", "thyroid": "stable", "blood_count": "no_data"}


def test_headline_without_data_and_other_analytes_with_data():
    (kidney, *_) = body.summarise(body.body_systems(), infos_by_id(), [trend("creatinine", [1.0, 1.1])], [])
    assert kidney["status"] == "stable" and kidney["headline"]["latest"] is None
    assert kidney["headline"]["unit"] == infos_by_id()["egfr"].unit
    assert kidney["analytes_with_data"] == [{"analyte_id": "creatinine", "name": infos_by_id()["creatinine"].name}]


def test_change_vs_baseline_only_after_the_baseline_and_not_for_a_censored_value():
    t = trend("egfr", [80, 60], baseline_dates=[0], baseline=80.0)
    assert body.change_vs_baseline(t) == -25.0
    assert body.change_vs_baseline(trend("egfr", [80, 60], baseline_dates=[0, 1], baseline=70.0)) is None
    censored = trend("egfr", [80, 70, 5], baseline_dates=[0], baseline=80.0, censored_last=True)
    assert body.change_vs_baseline(censored) == -12.5              # the latest non-censored result
    head = body.headline(infos_by_id()["egfr"], censored)
    assert head["latest"]["censored"] is True and head["latest"]["value_text"] == "<5"


# ---------------------------------------------------------------- API

@pytest.fixture(scope="module")
def pdf_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    for r in demo.REPORTS:
        write_pdf(r, out)
    return out


@pytest.fixture
def seeded(pdf_dir, tmp_path):
    use_fresh_database(tmp_path / "uploads")
    c = signed_in_client()
    ids = seed(c, pdf_dir)
    yield c, ids
    app.dependency_overrides.clear()


def get_systems(c, pid):
    r = c.get(f"/patients/{pid}/systems")
    assert r.status_code == 200
    return {s["id"]: s for s in r.json()["systems"]}


def test_systems_agree_with_trends_and_flags(seeded):
    c, ids = seeded
    pid = ids["patient_id"]
    got = get_systems(c, pid)
    trends = {t["analyte_id"]: t for t in c.get(f"/patients/{pid}/trends").json()["analytes"]}
    flags = c.get(f"/patients/{pid}/flags").json()["flags"]
    assert list(got) == list(SPEC)
    assert sum(sum(s["flag_counts"].values()) for s in got.values()) == len(flags)
    for sid, s in got.items():
        h = s["headline"]
        t = trends.get(h["analyte_id"])
        assert {a["analyte_id"] for a in s["analytes_with_data"]} == SPEC[sid][2] & set(trends)
        if t is None:
            assert h["latest"] is None and h["slope"] is None
            continue
        assert (h["latest"]["value"], h["latest"]["date"], h["latest"]["report_id"]) == (
            t["points"][-1]["value"], t["points"][-1]["date"], t["points"][-1]["report_id"])
        assert h["baseline"] == t["baseline"] and h["slope"] == t["slope"]
    assert {sid: s["status"] for sid, s in got.items()} == {
        "kidney": "changed", "glucose": "changed", "electrolytes": "stable", "lipids": "no_data",
        "liver": "no_data", "thyroid": "no_data", "blood_count": "no_data"}


def test_r10_makes_kidney_a_guideline_alert(seeded, pdf_dir):
    c, ids = seeded
    pid = ids["patient_id"]
    r10 = next(pdf_dir.glob("selvam_R10_*.pdf"))
    with open(r10, "rb") as f:
        rid = c.post(f"/patients/{pid}/reports", files={"file": (r10.name, f, "application/pdf")}).json()["report"]["id"]
    assert c.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    kidney = get_systems(c, pid)["kidney"]
    assert kidney["status"] == "guideline" and kidney["flag_counts"]["guideline"] == 1
    h = kidney["headline"]
    assert h["latest"]["report_id"] == rid and h["latest"]["date"] == "2026-03-02"
    assert round(h["latest"]["value"], 1) == 54.1 and round(h["slope"]["per_year"], 1) == -7.1   # as in the design


def test_systems_scoping_and_empty_patient(client, other_doctor):
    pid = client.post("/patients", json={"name": "New", "sex": "male", "birth_year": 1970}).json()["id"]
    got = get_systems(client, pid)
    assert all(s["status"] == "no_data" and s["headline"]["latest"] is None for s in got.values())
    assert other_doctor.get(f"/patients/{pid}/systems").status_code == 404
    assert client.get("/patients/9999/systems").status_code == 404
