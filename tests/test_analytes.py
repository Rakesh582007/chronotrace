import copy

import pytest

import validate_analytes as va


@pytest.fixture(scope="module")
def data():
    return va.load()


def analyte(data, aid):
    return next(a for a in data["analytes"] if a["id"] == aid)


# ---------------------------------------------------------------- dictionary is valid

def test_dictionary_is_valid(data):
    assert va.validate(data) == []


def test_has_the_twenty_step1_analytes(data):
    assert {a["id"] for a in data["analytes"]} == {
        "hba1c", "fasting_glucose", "pp_glucose", "creatinine", "urea", "egfr", "uacr",
        "sodium", "potassium", "tsh", "free_t4", "total_cholesterol", "ldl", "hdl",
        "triglycerides", "alt", "ast", "haemoglobin", "platelets", "wbc",
    }


def test_every_rcv_has_a_status_and_source(data):
    for a in data["analytes"]:
        assert a["rcv"]["status"] in va.RCV_STATUSES, a["id"]
        assert a["rcv"]["source"], a["id"]


# ---------------------------------------------------------------- validator catches mistakes

@pytest.mark.parametrize("code, ok", [
    ("2160-0", True), ("4548-4", True), ("98979-8", True), ("13457-7", True),
    ("2160-1", False), ("4548-7", False), ("2160", False), ("abc-1", False),
])
def test_loinc_check_digit(code, ok):
    assert va.loinc_check_digit_ok(code) is ok


def test_validator_rejects_shared_synonym(data):
    bad = copy.deepcopy(data)
    analyte(bad, "ldl")["synonyms"].append("SGPT")
    assert any("also used by" in e for e in va.validate(bad))


def test_validator_rejects_wrong_rcv(data):
    bad = copy.deepcopy(data)
    analyte(bad, "creatinine")["rcv"]["percent"] = 10.0
    assert any("does not match" in e for e in va.validate(bad))


def test_validator_rejects_bad_loinc(data):
    bad = copy.deepcopy(data)
    analyte(bad, "tsh")["loinc"] = "3016-4"
    assert any("check digit" in e for e in va.validate(bad))


def test_validator_rejects_missing_sex_coverage(data):
    bad = copy.deepcopy(data)
    analyte(bad, "hdl")["reference_ranges"] = [{"sex": "male", "low": 40, "high": None}]
    assert any("must cover" in e for e in va.validate(bad))


def test_validator_rejects_rcv_without_source(data):
    bad = copy.deepcopy(data)
    analyte(bad, "sodium")["rcv"]["source"] = ""
    assert any("rcv.source" in e for e in va.validate(bad))


# ---------------------------------------------------------------- synonym lookup

@pytest.mark.parametrize("name, aid", [
    ("SGPT", "alt"), ("sgot", "ast"), ("  Fasting   Blood Sugar ", "fasting_glucose"),
    ("PPBS", "pp_glucose"), ("S. Creatinine", "creatinine"), ("TLC", "wbc"),
    ("Glycosylated Hemoglobin", "hba1c"), ("Urine ACR", "uacr"), ("BUN", "urea"),
])
def test_find_analyte_by_indian_lab_synonym(data, name, aid):
    assert va.find_analyte(data, name)["id"] == aid


def test_unknown_name_returns_none(data):
    assert va.find_analyte(data, "Serum Ferritin") is None


# ---------------------------------------------------------------- unit conversion

@pytest.mark.parametrize("aid, value, unit, expected", [
    ("creatinine", 88.42, "µmol/L", 1.0),
    ("creatinine", 88.42, "umol/l", 1.0),           # typed without micro sign
    ("fasting_glucose", 5.5, "mmol/L", 99.1),
    ("hba1c", 48, "mmol/mol", 6.54),                # IFCC -> NGSP
    ("total_cholesterol", 5.17, "mmol/L", 199.9),
    ("triglycerides", 1.69, "mmol/L", 149.7),
    ("free_t4", 16.0, "pmol/L", 1.24),
    ("haemoglobin", 135, "g/L", 13.5),
    ("platelets", 2.5, "lakh/cumm", 250),
    ("platelets", 250000, "/cumm", 250),
    ("wbc", 7800, "cells/cumm", 7.8),
    ("uacr", 3.4, "mg/mmol", 30.1),
    ("urea", 5.0, "mmol/L", 30.0),
    ("alt", 0.5, "µkat/L", 30),
    ("tsh", 2.1, "µIU/mL", 2.1),
])
def test_to_canonical(data, aid, value, unit, expected):
    assert va.to_canonical(analyte(data, aid), value, unit) == pytest.approx(expected, abs=0.1)


def test_unknown_unit_raises(data):
    with pytest.raises(ValueError):
        va.to_canonical(analyte(data, "creatinine"), 1.0, "g/L")


def test_bun_basis_factor(data):
    # BUN 14 mg/dL is about 30 mg/dL urea
    assert 14 * analyte(data, "urea")["alternate_basis"]["mass_factor"] == pytest.approx(30.0, abs=0.1)


# ---------------------------------------------------------------- eGFR (CKD-EPI 2021)

@pytest.mark.parametrize("scr, age, sex, expected", [
    (1.0, 50, "male", 92),     # 142 * (1/0.9)^-1.2 * 0.9938^50
    (0.8, 60, "female", 84),   # above kappa branch
    (0.6, 40, "female", 116),  # below kappa branch uses alpha
    (2.0, 65, "male", 36),
])
def test_egfr_ckd_epi_2021(data, scr, age, sex, expected):
    formula = analyte(data, "egfr")["formula"]
    assert round(va.egfr_ckd_epi_2021(scr, age, sex, formula)) == expected


def test_egfr_rejects_unknown_sex(data):
    with pytest.raises(ValueError):
        va.egfr_ckd_epi_2021(1.0, 50, "unknown", analyte(data, "egfr")["formula"])
