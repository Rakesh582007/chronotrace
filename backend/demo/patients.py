"""The other demo patients (synthetic), seeded after K. Selvam through the same upload + confirm API.

M. Rani     F 1962, hypothyroidism: 4 reports from 2 labs, exactly 2 change flags.
            TSH 2.4 -> 2.6 -> 4.5 -> 3.4 mIU/L: only R3 is beyond its RCV (51%) of the previous result
            (+73%); R4 is -24% from R3 and +31% from the baseline (median of R1-R3 = 2.6).
            Free T4 1.30 -> 1.25 -> 1.20 -> 0.97 ng/dL: each step is within its RCV (21%); R4 is -22.4%
            from the baseline (1.25), so only the baseline rule fires.
J. Arul     M 1979, type 2 diabetes: one report (trends start from the second).
S. Priya    F 1974, hypertension + CKD: 3 reports from one lab, every change within its RCV (no flags).

Patient codes follow the order of creation: CT-0001 Selvam, CT-0002 Rani, CT-0003 Arul, CT-0004 Priya.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from data import validate_analytes as va

from .reports import Header

EGFR_FORMULA = next(a for a in va.load()["analytes"] if a["id"] == "egfr")["formula"]


@dataclass(frozen=True)
class Visit:
    id: str
    date: dt.date
    lab: str                                       # "A" or "B" (backend/demo/reports.py)
    values: dict[str, float]                       # analyte id -> value


@dataclass(frozen=True)
class OtherPatient:
    slug: str                                      # file names
    record: dict                                   # POST /patients body
    header: Header
    visits: tuple[Visit, ...]


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


RANI = OtherPatient("rani", {"name": "M. Rani", "sex": "female", "birth_year": 1962, "conditions": ["hypothyroidism"]},
                    Header("Mrs M. RANI", "Mrs M. Rani", "Female", 1962, "7000005318"), (
    Visit("R1", _d("2024-07-08"), "A", {"tsh": 2.4, "free_t4": 1.30}),
    Visit("R2", _d("2025-01-20"), "B", {"tsh": 2.6, "free_t4": 1.25}),
    Visit("R3", _d("2025-07-15"), "A", {"tsh": 4.5, "free_t4": 1.20}),
    Visit("R4", _d("2026-01-14"), "B", {"tsh": 3.4, "free_t4": 0.97}),
))

ARUL = OtherPatient("arul", {"name": "J. Arul", "sex": "male", "birth_year": 1979, "conditions": ["type 2 diabetes"]},
                    Header("Mr J. ARUL", "Mr J. Arul", "Male", 1979, "7000006077"), (
    Visit("R1", _d("2025-08-05"), "A", {"fasting_glucose": 142, "hba1c": 7.8, "creatinine": 0.98,
                                        "total_cholesterol": 196, "ldl": 118, "hdl": 42, "triglycerides": 180}),
))

PRIYA = OtherPatient("priya", {"name": "S. Priya", "sex": "female", "birth_year": 1974,
                               "conditions": ["hypertension", "chronic kidney disease"]},
                     Header("Ms S. PRIYA", "Ms S. Priya", "Female", 1974, "7000006452"), (
    Visit("R1", _d("2024-11-18"), "B", {"creatinine": 1.24, "sodium": 139, "potassium": 4.6, "uacr": 210}),
    Visit("R2", _d("2025-05-19"), "B", {"creatinine": 1.28, "sodium": 140, "potassium": 4.8, "uacr": 245}),
    Visit("R3", _d("2025-11-20"), "B", {"creatinine": 1.26, "sodium": 138, "potassium": 4.7, "uacr": 228}),
))

OTHERS = (RANI, ARUL, PRIYA)                        # creation order after Selvam (CT-0002, CT-0003, CT-0004)

# How each lab prints a test: layout A (section, name, unit, range, decimals), layout B (name, unit, range, decimals).
A_ROWS = {
    "fasting_glucose": ("BLOOD - BIOCHEMISTRY", "GLUCOSE (FASTING)", "mg/dl", "74 - 99 mg/dl", 0),
    "hba1c": ("", "HB A1C", "%", "Nondiabetic : Less than 5.7 %", 1),
    "creatinine": ("RENAL FUNCTION", "CREATININE - SERUM", "mg/dl", "0.7 - 1.3", 2),
    "egfr": ("", "eGFR (CKD-EPI 2021)", "mL/min/1.73m2", "> 90", 0),
    "total_cholesterol": ("LIPID PROFILE", "CHOLESTEROL - SERUM", "mg/dl", "Less than 200", 0),
    "ldl": ("", "LDL CHOLESTEROL (DIRECT)", "mg/dl", "Less than 100", 0),
    "hdl": ("", "HDL CHOLESTEROL (DIRECT)", "mg/dl", "More than 40", 0),
    "triglycerides": ("", "TRIGLYCERIDES", "mg/dl", "Less than 150", 0),
    "tsh": ("THYROID PROFILE", "TSH (ULTRASENSITIVE)", "uIU/ml", "0.4 - 4.0", 1),
    "free_t4": ("", "FREE T4", "ng/dl", "0.8 - 1.8", 2),
}
B_ROWS = {
    "creatinine": ("Serum Creatinine", "mg/dL", "0.6-1.1", 2),
    "egfr": ("eGFR", "mL/min/1.73m2", ">90", 0),
    "sodium": ("Serum Sodium", "mmol/L", "136-145", 0),
    "potassium": ("Serum Potassium", "mmol/L", "3.5-5.1", 1),
    "uacr": ("Urine ACR", "mg/g", "<30", 0),
    "tsh": ("TSH", "mIU/L", "0.4-4.0", 1),
    "free_t4": ("Free T4", "ng/dL", "0.8-1.8", 2),
}


def with_egfr(p: OtherPatient, v: Visit) -> dict[str, float]:
    """The lab prints its own eGFR next to creatinine (ChronoTrace recomputes it anyway)."""
    values = dict(v.values)
    if "creatinine" in values:
        values["egfr"] = va.egfr_ckd_epi_2021(values["creatinine"], v.date.year - p.record["birth_year"],
                                              p.record["sex"], EGFR_FORMULA)
    order = list(A_ROWS if v.lab == "A" else B_ROWS)
    return {k: values[k] for k in sorted(values, key=order.index)}


def rows_a(p: OtherPatient, v: Visit) -> list[tuple[str, str, str, str, str]]:
    out, seen = [], set()
    for aid, value in with_egfr(p, v).items():
        section, name, unit, rng, dec = A_ROWS[aid]
        out.append((section if section not in seen else "", name, f"{value:.{dec}f}", unit, rng))
        seen.add(section)
    return out


def rows_b(p: OtherPatient, v: Visit) -> list[tuple[str, str, str, str]]:
    return [(B_ROWS[aid][0], f"{value:.{B_ROWS[aid][3]}f}", B_ROWS[aid][1], B_ROWS[aid][2])
            for aid, value in with_egfr(p, v).items()]
