"""Step 9c: KDIGO grid, guideline criteria, codes and nutrition figures (backend/clinical)."""

import datetime as dt
import json

import pytest

from backend import clinical as C
from backend.trends import catalogue
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
    return C.clinical(trends, list(conditions), weight, infos_by_id(), RAW, events, "male", dt.date(2026, 9, 29))


@pytest.mark.parametrize("egfr, g", [(95, "G1"), (90, "G1"), (75, "G2"), (59.9, "G3a"), (45, "G3a"), (44, "G3b"),
                                     (29, "G4"), (14.9, "G5")])
def test_g_category(egfr, g):
    assert C.g_category(egfr) == g


@pytest.mark.parametrize("acr, a", [(10, "A1"), (29.9, "A1"), (30, "A2"), (300, "A2"), (301, "A3")])
def test_a_category(acr, a):
    assert C.a_category(acr) == a


def test_selvam_grid_and_ckd_criterion():
    out = selvam()
    cur = out["kdigo"]["current"]
    assert (cur["g"], cur["a"]) == ("G3a", "A2") and "risk" not in cur
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


def groups(out):
    return {g["id"]: {i["id"]: i for i in g["items"]} | {"_group": g} for g in out["nutrition"]["groups"]}


def test_selvam_nutrition_is_tied_to_his_results_and_medicines():
    g = groups(selvam())
    assert list(g) == ["kidney", "glucose"]
    kidney, glucose = g["kidney"], g["glucose"]
    assert kidney["_group"]["basis"].startswith("KDIGO G3a A2: eGFR 54.06 on 02 Mar 2026, from 79.28 on 12 Jun 2023")
    assert kidney["protein_ckd"]["amount"] == 58 and "G3a" in kidney["protein_ckd"]["applies_because"]
    assert "KDIGO 2022" in kidney["protein_ckd"]["source"]          # diabetes with CKD adds the 2022 source
    assert (kidney["energy_ckd"]["amount"], kidney["energy_ckd"]["amount_high"]) == (1800, 2520)
    k = kidney["potassium_ckd"]
    assert "5.0 mmol/L on 02 Mar 2026, from 4.5 mmol/L" in k["applies_because"] and "ramipril since" in k["applies_because"]
    assert k["note"].startswith("A potassium rise is expected after starting an ACE inhibitor")
    assert "7.1% on 02 Mar 2026, from 8.9%" in glucose["_group"]["basis"] and "above the ADA goal" in glucose["_group"]["basis"]
    assert "metformin since 02 Oct 2023" in glucose["_group"]["basis"]
    assert (glucose["fibre"]["amount"], glucose["fibre"]["amount_high"]) == (25, 35)   # 14 g per 1,000 kcal
    assert "potassium" in glucose["fibre"]["note"]
    assert "about 3 years" in glucose["b12_metformin"]["applies_because"]


def test_nutrition_without_weight_has_no_amounts():
    g = groups(selvam(weight=None))
    assert g["kidney"]["protein_ckd"]["amount"] is None and "energy_ckd" not in g["kidney"]
    assert g["glucose"]["fibre"]["amount"] is None


def other(name, conditions=None, weight=None, sex=None):
    """A demo patient other than Selvam, through the same engine."""
    from backend.demo import patients as P
    p = {"rani": P.RANI, "arul": P.ARUL, "priya": P.PRIYA}[name]
    points, oid = {}, 1
    for rid, v in enumerate(p.visits, 1):
        for aid, value in P.with_egfr(p, v).items():
            points.setdefault(aid, []).append(E.Point(oid, rid, v.date, value, lab=v.lab))
            oid += 1
    events = [E.Event(i, e["drug"], e["change"], dt.date.fromisoformat(e["date"]), *catalogue.resolve(e["drug"]))
              for i, e in enumerate(p.events, 1)]
    trends, _ = E.analyse_patient(list(analyte_infos()), points, events)
    trends = json.loads(json.dumps(trends, default=str))
    rec = p.record
    return C.clinical(trends, conditions if conditions is not None else rec["conditions"],
                      weight if weight is not None else rec["weight_kg"], infos_by_id(), RAW, events,
                      sex or rec["sex"], dt.date(2026, 9, 29))


def test_rani_levothyroxine_timing():
    g = groups(other("rani"))
    assert list(g) == ["thyroid"]
    t = g["thyroid"]
    assert "TSH 8.1 mIU/L on 15 Dec 2025, above 0.4–4.0 mIU/L" in t["_group"]["basis"]
    assert "levothyroxine since 04 Nov 2024" in t["levo_timing"]["applies_because"]
    assert "4 hours" in t["levo_supplements"]["figure"]


def test_arul_lipids_from_his_values():
    g = groups(other("arul"))
    assert list(g) == ["glucose", "lipids"]
    assert g["lipids"]["_group"]["recorded"] is False
    assert "LDL 118 mg/dL" in g["lipids"]["sat_fat"]["applies_because"]
    assert "180 mg/dL" in g["lipids"]["triglycerides"]["applies_because"]
    assert g["glucose"]["fibre"]["amount"] is None          # no CKD energy range to scale from


def test_priya_hypertension_potassium_is_superseded_by_ckd():
    g = groups(other("priya"))
    assert list(g) == ["kidney", "pressure"]
    assert "hypertension" in g["kidney"]["sodium"]["applies_because"] and "1.5 g" in g["kidney"]["sodium"]["note"]
    assert "sodium" not in g["pressure"]                    # one sodium figure, in the kidney group
    k = g["pressure"]["potassium_htn"]
    assert k["superseded_by"] == "kidney" and "CKD is recorded" in k["note"]
    assert g["pressure"]["alcohol"]["amount"] == 1          # sex recorded as female
    assert "potassium" in g["pressure"]["dash"]["note"]


def test_hypertension_alone_keeps_the_potassium_figure():
    g = groups(other("priya", conditions=["hypertension"]))
    # the KDIGO CKD criterion is still met from her urine ACR, so the kidney group stays (not recorded)
    assert g["kidney"]["_group"]["recorded"] is False
    male = groups(other("arul", conditions=["hypertension"], sex="male"))
    assert male["pressure"]["alcohol"]["amount"] == 2 and male["pressure"]["potassium_htn"]["superseded_by"] is None
    assert male["pressure"]["sodium"]["amount"] == 1.5


def test_unknown_condition_has_no_codes():
    out = selvam(conditions=("gout",))
    assert out["codes"]["conditions"][0]["icd10"] is None


def test_no_advice_or_diagnosis_words():
    out = selvam()
    texts = [c[k] for c in out["criteria"] for k in ("title", "evidence")] + \
            [n[k] or "" for g in out["nutrition"]["groups"] for n in g["items"]
             for k in ("title", "figure", "applies_because", "note")] + \
            [g[k] for g in out["nutrition"]["groups"] for k in ("label", "basis")]
    assert texts and [t for t in texts if BANNED.search(t)] == []


@pytest.mark.parametrize("name", ["rani", "arul", "priya"])
def test_no_advice_words_in_other_patients_nutrition(name):
    out = other(name)
    texts = [n[k] or "" for g in out["nutrition"]["groups"] for n in g["items"]
             for k in ("title", "figure", "applies_because", "note")] + \
            [g[k] for g in out["nutrition"]["groups"] for k in ("label", "basis")]
    assert texts and [t for t in texts if BANNED.search(t)] == []
