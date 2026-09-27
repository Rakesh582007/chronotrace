import copy
import datetime as dt

import pytest

from backend import normalise as nm
from backend.extraction.assemble import Result
from backend.normalise.names import NameIndex, loose_words, name_index
from backend.normalise.values import find_conversion, parse_value
from data import validate_analytes as va


def obs(test, value, unit="", rng="") -> nm.Observation:
    return nm.Observation(test_text=test, value_text=value, unit_text=unit, range_text=rng, flag_text="",
                          row_text=f"{test} {value} {unit} {rng}", page=1, line=1)


def result(test, value, unit="", rng="", line=1) -> Result:
    return Result(test, value, unit, rng, "", 1, line, f"{test} {value} {unit} {rng}")


# ---------------------------------------------------------------- names

REAL_NAMES = {
    "GLUCOSE (FASTING)": "fasting_glucose", "CREATININE - SERUM": "creatinine", "UREA - SERUM": "urea",
    "CHOLESTEROL - SERUM": "total_cholesterol", "HDL CHOLESTEROL (DIRECT)": "hdl",
    "LDL CHOLESTEROL (DIRECT)": "ldl", "TRIGLYCERIDES": "triglycerides", "HB A1C": "hba1c",
}


@pytest.mark.parametrize("name, aid", REAL_NAMES.items())
def test_real_report_names_match_exactly(name, aid):
    m = name_index().match(name)
    assert (m.analyte_id, m.method) == (aid, "exact")


@pytest.mark.parametrize("name, aid", REAL_NAMES.items())
def test_real_report_names_also_match_loosely_without_report_synonyms(name, aid):
    data = copy.deepcopy(va.load())
    for a in data["analytes"]:
        a.pop("report_synonyms", None)
    assert NameIndex(data).match(name).analyte_id == aid


@pytest.mark.parametrize("name", ["TOTAL CHO / HDL RATIO", "VLDL CHOLESTEROL", "C.R.P.", "A.S.O. TITRE",
                                  "GLUCOSE", "GLUCOSE (RANDOM)", "CALCIUM -SERUM", "Age / Sex :52 Y"])
def test_must_stay_not_tracked(name):
    m = name_index().match(name)
    assert m.analyte_id is None and not m.ambiguous


def test_fasting_is_a_qualifier_except_for_glucose():
    assert loose_words("TRIGLYCERIDES (FASTING)") == ["triglycerides"]
    assert loose_words("GLUCOSE (FASTING)") == ["glucose", "fasting"]
    assert name_index().match("Serum Triglycerides (Fasting)").analyte_id == "triglycerides"


def test_two_candidates_need_review_never_a_guess():
    data = copy.deepcopy(va.load())
    for a in data["analytes"]:
        if a["id"] == "hdl":
            a["synonyms"].append("Lipid Marker (Serum)")
        if a["id"] == "ldl":
            a["synonyms"].append("Lipid Marker (Plasma)")
    m = NameIndex(data).match("LIPID MARKER")
    assert m.analyte_id is None and m.ambiguous and set(m.candidates) == {"hdl", "ldl"}
    o = nm.normalise_value(obs("LIPID MARKER", "50", "mg/dl"), NameIndex(data))
    assert o.status == nm.NEEDS_REVIEW and "more than one test" in o.status_reason and o.canonical_value is None


def test_bun_is_converted_to_urea():
    o = nm.normalise_value(obs("BUN", "14", "mg/dL"))
    assert o.analyte_id == "urea" and o.canonical_value == pytest.approx(14 * 2.1437)


# ---------------------------------------------------------------- values and units

@pytest.mark.parametrize("text, number, comparator", [
    ("92", 92.0, None), ("0.60", 0.6, None), ("1,50,000", 150000.0, None), ("6,370", 6370.0, None),
    ("<0.5", 0.5, "<"), ("< 0.5", 0.5, "<"), (">1000", 1000.0, ">"), (">= 60", 60.0, ">="),
    ("less than 5", 5.0, "<"), ("Upto 40", 40.0, "<"), ("12.9*", 12.9, None),
    ("Negative", None, None), ("Nil", None, None), ("Reactive", None, None), ("Non Reactive", None, None),
    ("", None, None), ("--", None, None), ("5,1", None, None), ("1.2.3", None, None),
])
def test_parse_value_never_crashes(text, number, comparator):
    pv = parse_value(text)
    assert (pv.number, pv.comparator) == (number, comparator)


@pytest.mark.parametrize("unit", ["mIU/L", "miu/l", "uIU/mL", "uIU/ml", "µIU/mL", "μIU/ml", "µU/mL", " uIU / ml "])
def test_tsh_units_are_equivalent(unit):
    o = nm.normalise_value(obs("TSH", "3.2", unit))
    assert (o.status, o.canonical_value, o.canonical_unit) == (nm.EXTRACTED, 3.2, "mIU/L")


@pytest.mark.parametrize("aid, unit", [("haemoglobin", "GM/DL"), ("wbc", "Cells/cu.mm"), ("platelets", "Lakhs/cu.mm"),
                                       ("creatinine", "MG/DL")])
def test_units_match_case_and_dots(aid, unit):
    assert find_conversion(nm.analyte(aid), unit) is not None


def test_platelets_in_lakhs():
    assert nm.normalise_value(obs("PLATELET COUNT", "2.41", "Lakhs/cu.mm")).canonical_value == pytest.approx(241)


def test_unknown_unit_needs_review_without_conversion():
    o = nm.normalise_value(obs("SERUM SODIUM", "138", "mmol/xx"))
    assert o.status == nm.NEEDS_REVIEW and o.canonical_value is None and "mmol/xx" in o.status_reason
    o = nm.normalise_value(obs("SERUM SODIUM", "138", ""))
    assert o.status == nm.NEEDS_REVIEW and "no unit" in o.status_reason


@pytest.mark.parametrize("value", ["Negative", "Nil", "Reactive", "Haemolysed"])
def test_non_numeric_tracked_value_needs_review(value):
    o = nm.normalise_value(obs("Serum Potassium", value, "mmol/L"))
    assert o.status == nm.NEEDS_REVIEW and o.canonical_value is None and o.value_text == value


def test_comparator_is_kept_with_the_number():
    o = nm.normalise_value(obs("TRIGLYCERIDES", ">1000", "mg/dl"))
    assert (o.status, o.comparator, o.canonical_value) == (nm.EXTRACTED, ">", 1000.0)
    o = nm.normalise_value(obs("Triglycerides", "<0.5", "mmol/L"))
    assert o.comparator == "<" and o.canonical_value == pytest.approx(0.5 * 88.57)


# ---------------------------------------------------------------- eGFR

def test_egfr_is_recomputed_from_creatinine():
    patient, date = nm.Patient("male", 1966), dt.date(2024, 1, 16)
    observations, _ = nm.normalise([result("SERUM CREATININE", "1.62", "mg/dl", "0.7 - 1.3", line=10),
                                    result("eGFR (CKD-EPI 2021)", "99", "mL/min/1.73m2", "> 90", line=11)], patient, date)
    egfr = observations[1]
    want = va.egfr_ckd_epi_2021(1.62, 58, "male", nm.analyte("egfr")["formula"])
    assert egfr.status == nm.EXTRACTED and egfr.canonical_value == pytest.approx(want, abs=0.01)
    assert egfr.value_text == "99" and "printed eGFR '99' kept as text" in egfr.status_reason


@pytest.mark.parametrize("results, date, reason", [
    ([result("eGFR", "60", "mL/min/1.73m2", "> 90")], dt.date(2024, 1, 1), "no usable creatinine"),
    ([result("Creatinine", "1.1", "mg/dL", "0.7-1.3"), result("eGFR", "60", "mL/min/1.73m2", "> 90")], None,
     "report date needed"),
    ([result("Creatinine", "1.1", "mg/xx", "0.7-1.3"), result("eGFR", "60", "mL/min/1.73m2", "> 90")],
     dt.date(2024, 1, 1), "no usable creatinine"),
])
def test_egfr_needs_review_when_it_cannot_be_computed(results, date, reason):
    observations, _ = nm.normalise(results, nm.Patient("female", 1970), date)
    egfr = [o for o in observations if o.analyte_id == "egfr"][0]
    assert egfr.status == nm.NEEDS_REVIEW and reason in egfr.status_reason and egfr.canonical_value is None


# ---------------------------------------------------------------- what is kept

def test_unmapped_without_unit_or_range_is_skipped_not_an_observation():
    observations, skipped = nm.normalise([result("Age / Sex :52 Y", "52"), result("VLDL CHOLESTEROL", "20.8", "mg/dl"),
                                          result("TOTAL CHO / HDL RATIO", "3.38", "", "Less than 3.5")],
                                         nm.Patient("male", 1972), dt.date(2024, 1, 15))
    assert [o.test_text for o in observations] == ["VLDL CHOLESTEROL", "TOTAL CHO / HDL RATIO"]
    assert all(o.status == nm.NOT_TRACKED for o in observations)
    assert skipped == [(1, 1, "Age / Sex :52 Y 52  ", nm.NOT_A_RESULT)]


# ---------------------------------------------------------------- review findings (regressions)

@pytest.mark.parametrize("name, aid", [("F.B.S.", "fasting_glucose"), ("T.S.H.", "tsh"), ("P.P.B.S.", "pp_glucose"),
                                       ("S. Creatinine", "creatinine"), ("S.Creatinine", "creatinine"),
                                       ("Sr Creatinine", "creatinine"), ("Hb S", None)])
def test_serum_s_is_only_a_prefix_qualifier(name, aid):
    assert name_index().match(name).analyte_id == aid


@pytest.mark.parametrize("text", ["0,60", "4,25", "10,50", "00,60", "1,5,000"])
def test_decimal_comma_is_not_digit_grouping(text):
    assert parse_value(text).number is None
    o = nm.normalise_value(obs("CREATININE - SERUM", text, "mg/dl"))
    assert o.status == nm.NEEDS_REVIEW and o.canonical_value is None


@pytest.mark.parametrize("printed", [">90", "<60", "49"])
def test_recomputed_egfr_never_carries_the_printed_comparator(printed):
    observations, _ = nm.normalise([result("CREATININE - SERUM", "0.74", "mg/dl", line=1),
                                    result("eGFR", printed, "mL/min/1.73m2", "> 90", line=2)],
                                   nm.Patient("male", 1972), dt.date(2024, 1, 15))
    egfr = observations[1]
    assert egfr.comparator is None and egfr.value_text == printed and egfr.status == nm.EXTRACTED


@pytest.mark.parametrize("creat, date, reason", [
    ("0", dt.date(2024, 1, 15), "creatinine must be above 0"),
    ("1.1", dt.date(1980, 1, 15), "outside 18-120"),
])
def test_egfr_needs_review_for_zero_creatinine_or_non_adult_age(creat, date, reason):
    observations, _ = nm.normalise([result("Creatinine", creat, "mg/dL"), result("eGFR", "60", "mL/min/1.73m2", "> 90")],
                                   nm.Patient("male", 1972), date)
    assert observations[1].status == nm.NEEDS_REVIEW and reason in observations[1].status_reason


@pytest.mark.parametrize("name, basis, value", [("BUN", "alternate", 14 * 2.1437),
                                                ("UREA NITROGEN (BUN)", "alternate", 14 * 2.1437),
                                                ("UREA - SERUM", "primary", 14.0)])
def test_doctor_chosen_urea_keeps_the_basis_of_the_printed_name(name, basis, value):
    o = nm.normalise_value(obs(name, "14", "mg/dL"), analyte_id="urea")
    assert (o.basis, o.match) == (basis, "doctor") and o.canonical_value == pytest.approx(value)


def test_unmapped_row_with_range_on_the_next_lines_is_kept():
    r = result("LDL / HDL RATIO", "1.74")
    r.range_lines = ["Desirable : 0.5 - 3.0", "Borderline : 3.0 - 6.0"]
    observations, skipped = nm.normalise([r], nm.Patient("male", 1972), dt.date(2024, 1, 15))
    assert skipped == [] and observations[0].status == nm.NOT_TRACKED and observations[0].range_lines == r.range_lines
