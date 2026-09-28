"""Step 9c: KDIGO grid, guideline criteria, codes and nutrition figures (backend/clinical)."""

import json

import pytest

from backend import clinical as C
from backend.trends import engine as E
from backend.trends.dictionary import analyte_infos, infos_by_id
from backend.trends.wording import BANNED
from data import validate_analytes as va
from tests.test_trends_engine import demo_patient

RAW = {a["id"]: a for a in va.load()["analytes"]}


def selvam(upto="R10", conditions=("type 2 diabetes", "chronic kidney disease"), weight=72):
    points, events = demo_patient(upto)
    trends, _ = E.analyse_patient(list(analyte_infos()), points, events)
    trends = json.loads(json.dumps(trends, default=str))
    return C.clinical(trends, list(conditions), weight, infos_by_id(), RAW)


@pytest.mark.parametrize("egfr, g", [(95, "G1"), (90, "G1"), (75, "G2"), (59.9, "G3a"), (45, "G3a"), (44, "G3b"),
                                     (29, "G4"), (14.9, "G5")])
def test_g_category(egfr, g):
    assert C.g_category(egfr) == g


@pytest.mark.parametrize("acr, a", [(10, "A1"), (29.9, "A1"), (30, "A2"), (300, "A2"), (301, "A3")])
def test_a_category(acr, a):
    assert C.a_category(acr) == a


def test_kdigo_heat_map():
    assert C.risk("G2", "A1") == "low" and C.risk("G3a", "A2") == "high" and C.risk("G3b", "A2") == "very high"


def test_selvam_grid_and_ckd_criterion():
    out = selvam()
    cur = out["kdigo"]["current"]
    assert (cur["g"], cur["a"], cur["risk"]) == ("G3a", "A2", "high")
    assert len(out["kdigo"]["history"]) == 10
    ckd = next(c for c in out["criteria"] if c["id"] == "ckd_kdigo")
    assert ckd["status"] == "met" and ckd["recorded"] is True
    assert "eGFR below 60 from 58.12 on 01 Sep 2025 to 54.06 on 02 Mar 2026 (182 days)" in ckd["evidence"]
    assert [c["code"] for c in ckd["codes"]] == ["N18.31", "709044004"]


def test_criterion_met_but_not_recorded():
    out = selvam(conditions=("type 2 diabetes",))
    ckd = next(c for c in out["criteria"] if c["id"] == "ckd_kdigo")
    assert ckd["status"] == "met" and ckd["recorded"] is False


def test_diabetes_criterion_and_codes():
    out = selvam()
    dm = next(c for c in out["criteria"] if c["id"] == "diabetes_ada")
    assert dm["status"] == "met" and dm["title"] == "Diabetes (ADA criteria)"
    assert "first 8.9% on 12 Jun 2023 and 8.7% on 14 Sep 2023" in dm["evidence"]
    codes = {c["text"]: c for c in out["codes"]["conditions"]}
    assert codes["type 2 diabetes"]["icd10"] == "E11" and codes["chronic kidney disease"]["snomed"] == "709044004"
    assert {t["analyte_id"]: t["loinc"] for t in out["codes"]["tests"]}["hba1c"] == "4548-4"


def test_nutrition_figures_use_the_weight():
    out = selvam()
    n = {x["id"]: x for x in out["nutrition"]}
    assert n["protein_ckd"]["per_day"] == 58 and n["sodium_ckd"]["per_day"] == 2.0
    assert "mnt_diabetes" in n
    assert selvam(weight=None)["nutrition"][0]["per_day"] is None


def test_unknown_condition_has_no_codes():
    out = selvam(conditions=("gout",))
    assert out["codes"]["conditions"][0]["icd10"] is None


def test_no_advice_or_diagnosis_words():
    out = selvam()
    texts = [c[k] for c in out["criteria"] for k in ("title", "evidence")] + \
            [n[k] for n in out["nutrition"] for k in ("title", "figure", "applies_because")]
    assert texts and [t for t in texts if BANNED.search(t)] == []
