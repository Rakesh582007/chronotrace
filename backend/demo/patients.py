"""The other demo patients (synthetic), seeded after K. Selvam through the same upload + confirm API.

M. Rani     F 1962, hypothyroidism: 5 reports from 2 labs, levothyroxine 25 mcg OD started 2024-11-04
            (prescription stored). Two stories:
            1. Expected change not seen: TSH 8.8, 9.2 (lab A, baseline 9.0) -> 8.4 at R3, 63 days after the
               start (inside the 42-90 day window): -6.7%, within its RCV (51%). Free T4 0.85 -> 0.88.
            2. A change of lab: R4 comes from lab B (TSH 3.9, free T4 1.21, both beyond the RCV of R3);
               back at lab A, R5 (TSH 8.1, free T4 0.90) is within the RCV of R3. Four RCV_PREV change
               flags (R4 and R5, TSH and free T4), each with lab_change.same_lab_agrees = true.
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
    events: tuple[dict, ...] = ()                  # POST /medications bodies; each gets a prescription PDF


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


RANI = OtherPatient("rani", {"name": "M. Rani", "sex": "female", "birth_year": 1962, "conditions": ["hypothyroidism"]},
                    Header("Mrs M. RANI", "Mrs M. Rani", "Female", 1962, "7000005318"), (
    Visit("R1", _d("2024-07-08"), "A", {"tsh": 8.8, "free_t4": 0.86}),
    Visit("R2", _d("2024-10-14"), "A", {"tsh": 9.2, "free_t4": 0.84}),
    Visit("R3", _d("2025-01-06"), "A", {"tsh": 8.4, "free_t4": 0.88}),
    Visit("R4", _d("2025-06-16"), "B", {"tsh": 3.9, "free_t4": 1.21}),
    Visit("R5", _d("2025-12-15"), "A", {"tsh": 8.1, "free_t4": 0.90}),
), events=(
    {"drug": "Levothyroxine", "change": "start", "dose_text": "25 mcg OD", "date": "2024-11-04"},
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
