"""The demo patient: K. Selvam (synthetic), male, born 1968, type 2 diabetes + CKD.

Ten reports from three labs and three medication starts. Creatinine values were chosen so that
CKD-EPI 2021 (age = report year - 1968) gives the eGFR column. Potassium, fasting glucose and UACR stay
within their reference change values of each other, so they raise no flags.

The story: HbA1c falls after metformin; creatinine rises (and eGFR falls) as expected after ramipril;
eGFR dips a little after empagliflozin. After that no single report changes beyond the RCV, but the
slope over R7-R10 is below -5 per year, which only the trend shows.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from data import validate_analytes as va

PATIENT = {"name": "K. Selvam", "sex": "male", "birth_year": 1968,
           "conditions": ["type 2 diabetes", "chronic kidney disease"]}

# Lab layouts: A = ASTERLANE (column header, method/specimen lines), B = Kestrelline (no column header),
# C = a synthetic-generator layout.
LABS = {"A": "ASTERLANE DIAGNOSTICS", "B": "Kestrelline Labs", "C": "Varnika Clinical Labs"}


@dataclass(frozen=True)
class DemoReport:
    id: str
    date: dt.date
    lab: str               # key of LABS
    creatinine: float      # mg/dL
    egfr: float            # CKD-EPI 2021 from creatinine (checked in tests)
    hba1c: float           # %
    potassium: float       # mmol/L
    fbs: float             # mg/dL
    uacr: float            # mg/g


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


REPORTS = [
    DemoReport("R1", _d("2023-06-12"), "A", 1.10, 79.3, 8.9, 4.5, 152, 118),
    DemoReport("R2", _d("2023-09-14"), "B", 1.13, 76.8, 8.7, 4.6, 148, 126),
    DemoReport("R3", _d("2023-11-16"), "A", 1.11, 78.4, 8.6, 4.5, 146, 122),
    DemoReport("R4", _d("2024-02-15"), "C", 1.11, 77.9, 7.4, 4.6, 136, 131),
    DemoReport("R5", _d("2024-04-01"), "A", 1.29, 65.1, 7.2, 4.9, 134, 148),
    DemoReport("R6", _d("2024-06-10"), "B", 1.35, 61.6, 7.0, 4.9, 131, 142),
    DemoReport("R7", _d("2024-10-15"), "C", 1.31, 63.9, 6.9, 4.8, 130, 139),
    DemoReport("R8", _d("2025-03-10"), "A", 1.35, 61.2, 7.0, 4.9, 132, 151),
    DemoReport("R9", _d("2025-09-01"), "B", 1.41, 58.1, 6.9, 5.0, 130, 160),
    DemoReport("R10", _d("2026-03-02"), "A", 1.49, 54.1, 7.1, 5.0, 133, 172),
]
LIVE_REPORT = "R10"        # uploaded live in the demo

EVENTS = [
    {"drug": "Metformin", "change": "start", "dose_text": "500 mg BD", "date": "2023-10-02"},
    {"drug": "Ramipril", "change": "start", "dose_text": "2.5 mg OD", "date": "2024-03-04"},
    {"drug": "Empagliflozin", "change": "start", "dose_text": "10 mg OD", "date": "2024-05-06"},
]


def computed_egfr(r: DemoReport) -> float:
    formula = next(a for a in va.load()["analytes"] if a["id"] == "egfr")["formula"]
    return va.egfr_ckd_epi_2021(r.creatinine, r.date.year - PATIENT["birth_year"], PATIENT["sex"], formula)


def values(r: DemoReport) -> dict[str, float]:
    """Canonical values the pipeline should store for this report (eGFR as recomputed)."""
    return {"creatinine": r.creatinine, "egfr": round(computed_egfr(r), 2), "hba1c": r.hba1c,
            "potassium": r.potassium, "fasting_glucose": r.fbs, "uacr": r.uacr}
