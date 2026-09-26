"""Tests that appear on Indian CBC, LFT, KFT and lipid reports but are not in the dictionary.

They are printed as ordinary rows and tagged TEST/VALUE/UNIT/RANGE like any other test, with
analyte_id = null, so the model learns report structure rather than a list of 20 names.
Values come from the same patient state as the dictionary tests (clinical.py).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import dictionary as d
from . import values as v

Range = tuple[float | None, float | None]


@dataclass(frozen=True)
class ExtraTest:
    id: str
    panel: str
    names: tuple[str, ...]
    unit: str            # "" for unitless ratios
    decimals: int
    methods: tuple[str, ...]
    male: Range
    female: Range

    def reference_range(self, sex: str) -> Range:
        return self.male if sex == "male" else self.female

    @property
    def sex_specific(self) -> bool:
        return self.male != self.female


def _t(id, panel, names, unit, decimals, methods, rng=None, male=None, female=None) -> ExtraTest:
    return ExtraTest(id, panel, tuple(names), unit, decimals, tuple(methods), male or rng, female or rng)


_CBC = ("Electrical Impedance", "Calculated", "Flow Cytometry")

EXTRA_TESTS: dict[str, ExtraTest] = {t.id: t for t in [
    # CBC
    _t("rbc", "CBC", ["RBC Count", "Total RBC Count", "Red Blood Cell Count", "R.B.C."], "million/cumm", 2,
       _CBC, male=(4.5, 5.5), female=(3.8, 4.8)),
    _t("pcv", "CBC", ["PCV", "Haematocrit (PCV)", "Packed Cell Volume", "HCT"], "%", 1,
       ("Calculated", "Electrical Impedance"), male=(40.0, 50.0), female=(36.0, 46.0)),
    _t("mcv", "CBC", ["MCV", "Mean Corpuscular Volume"], "fL", 1, _CBC, (83.0, 101.0)),
    _t("mch", "CBC", ["MCH", "Mean Corpuscular Hemoglobin"], "pg", 1, ("Calculated",), (27.0, 32.0)),
    _t("mchc", "CBC", ["MCHC", "Mean Corpuscular Hb Conc."], "g/dL", 1, ("Calculated",), (31.5, 34.5)),
    _t("neutrophils", "CBC", ["Neutrophils", "Polymorphs", "Neutrophils %"], "%", 0, _CBC, (40, 80)),
    _t("lymphocytes", "CBC", ["Lymphocytes", "Lymphocytes %"], "%", 0, _CBC, (20, 40)),
    _t("eosinophils", "CBC", ["Eosinophils", "Eosinophils %"], "%", 0, _CBC, (1, 6)),
    _t("monocytes", "CBC", ["Monocytes", "Monocytes %"], "%", 0, _CBC, (2, 10)),
    # LFT
    _t("total_bilirubin", "LFT", ["Total Bilirubin", "Bilirubin, Total", "S. Bilirubin (Total)"], "mg/dL", 2,
       ("Diazo", "DPD"), (0.3, 1.2)),
    _t("direct_bilirubin", "LFT", ["Direct Bilirubin", "Bilirubin, Direct", "Conjugated Bilirubin"], "mg/dL", 2,
       ("Diazo", "DPD"), (None, 0.3)),
    _t("alp", "LFT", ["Alkaline Phosphatase", "ALP", "S. Alkaline Phosphatase"], "U/L", 0,
       ("IFCC", "PNPP-AMP"), (44, 147)),
    _t("total_protein", "LFT", ["Total Protein", "Protein, Total", "S. Total Proteins"], "g/dL", 1,
       ("Biuret",), (6.4, 8.3)),
    _t("albumin", "LFT", ["Albumin", "S. Albumin", "Albumin, Serum"], "g/dL", 1, ("BCG",), (3.5, 5.2)),
    _t("globulin", "LFT", ["Globulin", "S. Globulin"], "g/dL", 1, ("Calculated",), (2.3, 3.5)),
    _t("ag_ratio", "LFT", ["A/G Ratio", "Albumin/Globulin Ratio"], "", 1, ("Calculated",), (1.0, 2.1)),
    # KFT
    _t("uric_acid", "RENAL FUNCTION", ["Uric Acid", "S. Uric Acid", "Serum Uric Acid"], "mg/dL", 1,
       ("Uricase-POD",), male=(3.5, 7.2), female=(2.6, 6.0)),
    _t("calcium", "RENAL FUNCTION", ["Calcium", "S. Calcium", "Calcium, Total"], "mg/dL", 1,
       ("Arsenazo III", "OCPC"), (8.6, 10.2)),
    _t("chloride", "RENAL FUNCTION", ["Chloride", "S. Chloride", "Cl-"], "mmol/L", 0,
       ("ISE Indirect",), (98, 107)),
    # Lipid profile
    _t("vldl", "LIPID PROFILE", ["VLDL Cholesterol", "VLDL", "Cholesterol, VLDL"], "mg/dL", 0,
       ("Calculated",), (None, 30)),
    _t("non_hdl", "LIPID PROFILE", ["Non-HDL Cholesterol", "Non HDL Cholesterol"], "mg/dL", 0,
       ("Calculated",), (None, 130)),
    _t("tc_hdl_ratio", "LIPID PROFILE", ["Total Cholesterol/HDL Ratio", "CHOL/HDL Ratio", "TC/HDL Ratio"], "", 1,
       ("Calculated",), (None, 5.0)),
    _t("ldl_hdl_ratio", "LIPID PROFILE", ["LDL/HDL Ratio", "LDL-C/HDL-C Ratio"], "", 1,
       ("Calculated",), (None, 3.5)),
]}

# Print order within each panel, dictionary tests and extras together.
PANEL_ORDER: dict[str, list[str]] = {
    "BIOCHEMISTRY": ["fasting_glucose", "pp_glucose", "hba1c"],
    "RENAL FUNCTION": ["urea", "creatinine", "egfr", "uric_acid", "calcium", "sodium", "potassium",
                       "chloride", "uacr"],
    "LIPID PROFILE": ["total_cholesterol", "triglycerides", "hdl", "ldl", "vldl", "non_hdl",
                      "tc_hdl_ratio", "ldl_hdl_ratio"],
    "LFT": ["total_bilirubin", "direct_bilirubin", "alt", "ast", "alp", "total_protein", "albumin",
            "globulin", "ag_ratio"],
    "CBC": ["haemoglobin", "rbc", "pcv", "mcv", "mch", "mchc", "wbc", "neutrophils", "lymphocytes",
            "eosinophils", "monocytes", "platelets"],
    "THYROID PROFILE": ["tsh", "free_t4"],
}

# CBC and LFT: extras make up about 30-40% of the panel's rows. Other panels: each extra
# appears with this probability.
SHARE_PANELS = ("CBC", "LFT")
P_OTHER_EXTRA = 0.3


def choose_extras(rng: random.Random, panel: str, n_dictionary_rows: int) -> list[str]:
    pool = [t for t in PANEL_ORDER[panel] if t in EXTRA_TESTS]
    if not pool:
        return []
    if panel in SHARE_PANELS:
        k = max(1, round(n_dictionary_rows * rng.uniform(0.43, 0.67)))
        return rng.sample(pool, min(k, len(pool)))
    return [t for t in pool if rng.random() < P_OTHER_EXTRA]


def flag_for(test: ExtraTest, value: float, sex: str) -> str:
    return v.flag_from_range(*test.reference_range(sex), value)


def format_value(test: ExtraTest, value: float) -> str:
    return v.format_number(value, test.decimals)


def format_range(rng: random.Random, test: ExtraTest, sex: str, two_sided_style: str, high_style: str,
                 p_sex_format: float) -> tuple[str, str]:
    return v.render_range(rng, test.reference_range, test.sex_specific, v.dictionary_number, sex,
                          two_sided_style, high_style, p_sex_format)


def names_clashing_with_dictionary() -> list[str]:
    """Extra-test names that equal a dictionary synonym (must be empty)."""
    taken = {d.va.norm_text(n) for a in d.analytes().values()
             for n in d.name_pool(a) + d.basis_synonyms(a)}
    return [n for t in EXTRA_TESTS.values() for n in t.names if d.va.norm_text(n) in taken]
