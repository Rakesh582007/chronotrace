"""Render the demo patients' reports as PDFs in three lab layouts (all names and labs are invented).

A  ASTERLANE DIAGNOSTICS: column header "Investigation / Observed Value / Flag / Units / Biological
   Reference Interval", tests indented under section titles, method lines (the layout of the step-4
   test fixture).
B  Kestrelline Labs: no column header; test, value, unit and range spaced across the line.
C  Varnika Clinical Labs: rendered by the synthetic report generator (ml/generator) with a fixed seed.

Each report prints the lab's own eGFR (rounded); ChronoTrace recomputes it from creatinine anyway.
Layouts A and B take any patient and rows (the other demo patients, backend/demo/patients.py); layout C is
K. Selvam's only. write_prescription() draws a one-drug prescription (stored as a document, never parsed).
"""

from __future__ import annotations

import datetime as dt
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from . import data as demo

ROOT = Path(__file__).resolve().parents[2]
PAGE_H = letter[1]
FONT, BOLD = "Helvetica", "Helvetica-Bold"


def _text(c, x, top, s, size=8.0, font=FONT):
    c.setFont(font, size)
    c.drawString(x, PAGE_H - top - size * 0.8, s)


@dataclass(frozen=True)
class Header:
    """How a lab prints the patient."""
    name_upper: str            # layout A: "Mr K. SELVAM"
    name: str                  # layout B: "Mr K. Selvam"
    sex: str                   # "Male" | "Female"
    birth_year: int
    patient_id: str            # layout A's Patient ID


SELVAM = Header("Mr K. SELVAM", "Mr K. Selvam", "Male", demo.PATIENT["birth_year"], "7000004212")
METHODS = {"GLUCOSE (FASTING)": "HEXOKINASE", "HB A1C": "HPLC", "TSH (ULTRASENSITIVE)": "CLIA",
           "FREE T4": "CLIA"}


def _rows(r: demo.DemoReport) -> list[tuple[str, str, str, str, str]]:
    """(section or "", test name, value, unit, range) in print order."""
    return [
        ("BLOOD - BIOCHEMISTRY", "GLUCOSE (FASTING)", f"{r.fbs:.0f}", "mg/dl", "74 - 99 mg/dl"),
        ("", "HB A1C", f"{r.hba1c:.1f}", "%", "Nondiabetic : Less than 5.7 %"),
        ("RENAL FUNCTION", "CREATININE - SERUM", f"{r.creatinine:.2f}", "mg/dl", "0.7 - 1.3"),
        ("", "eGFR (CKD-EPI 2021)", f"{round(r.egfr):d}", "mL/min/1.73m2", "> 90"),
        ("", "POTASSIUM - SERUM", f"{r.potassium:.1f}", "mmol/l", "3.5 - 5.1"),
        ("URINE EXAMINATION", "URINE ALBUMIN/CREATININE RATIO", f"{r.uacr:.0f}", "mg/g", "Less than 30"),
    ]


def _when(d: dt.date, hour: int) -> str:
    return f"{d.strftime('%d/%m/%Y')} {hour:02d}:{(d.day * 7) % 60:02d}"


def layout_a(r: demo.DemoReport, path: Path) -> None:
    draw_a(path, SELVAM, r.date, _rows(r))


def draw_a(path: Path, who: Header, date: dt.date, rows: list[tuple[str, str, str, str, str]]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    reported = date + dt.timedelta(days=1 if date.day % 2 else 0)
    _text(c, 28, 60, demo.LABS["A"], 12, BOLD)
    _text(c, 28, 117, f"Lab No. :9{date.strftime('%y%m%d')}1", 9)
    _text(c, 425, 117, f"Patient ID : {who.patient_id}", 9)
    _text(c, 28, 133, who.name_upper, 9)
    _text(c, 28, 148, f"Age / Sex :{date.year - who.birth_year} Y / {who.sex}", 9)
    _text(c, 350, 148, "Collected Date and Time :" + _when(date, 8), 9)
    _text(c, 28, 164, "Ref By. :Dr. A. EXAMPLE", 9)
    _text(c, 350, 164, "Reported Date and Time :" + _when(reported, 16), 9)
    _text(c, 260, 225, "Final Test Report Page 1 of 1", 9)
    for x, label in [(28, "Investigation"), (233, "Observed Value"), (334, "Flag"), (365, "Units"),
                     (428, "Biological Reference Interval")]:
        _text(c, x, 244, label, 9, BOLD)
    top = 264.0
    for section, name, value, unit, rng in rows:
        if section:
            _text(c, 28, top, section, 9, BOLD)
            top += 16
        _text(c, 46, top, name, 8, BOLD)
        _text(c, 252, top, value, 8, BOLD)
        _text(c, 372, top, unit)
        _text(c, 441, top, rng)
        top += 11
        _text(c, 46, top, "Method :" + METHODS.get(name, "AUTOMATED"))
        top += 16
    _text(c, 269, top + 20, "* End of Report *", 9)
    c.showPage()
    c.save()


def layout_b(r: demo.DemoReport, path: Path) -> None:
    rows = [("Fasting Blood Sugar", f"{r.fbs:.0f}", "mg/dL", "70-100"), ("HbA1c", f"{r.hba1c:.1f}", "%", "4.0-5.6"),
            ("Serum Creatinine", f"{r.creatinine:.2f}", "mg/dL", "0.7-1.3"),
            ("eGFR", f"{round(r.egfr):d}", "mL/min/1.73m2", ">90"),
            ("Serum Potassium", f"{r.potassium:.1f}", "mmol/L", "3.5-5.1"), ("Urine ACR", f"{r.uacr:.0f}", "mg/g", "<30")]
    draw_b(path, SELVAM, r.date, rows)


def draw_b(path: Path, who: Header, date: dt.date, rows: list[tuple[str, str, str, str]]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    _text(c, 40, 60, demo.LABS["B"], 13, BOLD)
    _text(c, 40, 78, "Complete Laboratory Services", 9)
    _text(c, 40, 104, f"Name : {who.name}   Age : {date.year - who.birth_year} Yrs   Sex : {who.sex}", 9)
    _text(c, 40, 118, "Collected On : " + date.strftime("%d-%b-%Y") + " 09:10", 9)
    _text(c, 330, 118, "Reported On : " + date.strftime("%d-%b-%Y") + " 18:40", 9)
    for i, (name, value, unit, rng) in enumerate(rows):
        top = 150 + 17 * i
        _text(c, 40, top, name, 9)
        _text(c, 220, top, value, 9)
        _text(c, 300, top, unit, 9)
        _text(c, 400, top, rng, 9)
    _text(c, 40, 150 + 17 * len(rows) + 28, "-- End of Report --", 9)
    c.showPage()
    c.save()


def layout_c(r: demo.DemoReport, path: Path) -> None:
    """The synthetic generator's grid_classic family (a training layout), fixed seed."""
    sys.path.insert(0, str(ROOT / "ml"))
    from generator import layouts                      # noqa: E402  (ml/ is not a package)

    age = r.date.year - demo.PATIENT["birth_year"]
    collected = dt.datetime.combine(r.date, dt.time(8, 20))
    people = {"patient_name": "Mr. K. Selvam", "sex": "male", "age": age, "patient_id": "V21-004212",
              "sample_id": f"24A{r.date.strftime('%y%m%d')}0", "referrer": "Dr. A. Example",
              "pathologist": "Dr. B. Example", "pathologist_degree": "MD (Pathology)",
              "pathologist_role": "Consultant Pathologist", "collected": collected,
              "reported": collected + dt.timedelta(hours=9), "sample_type": "Serum / Urine",
              "lab_address": "12, Example Road, Chennai 600001"}
    lab = {"name": demo.LABS["C"], "initials": "VA", "tagline": "Accurate. Caring. Timely.",
           "email": "reports@varnika.example", "phone": "Tel: +91-00-4400-1200"}

    def row(i, aid, panel, name, value, unit, rng):
        return layouts.TestRow(i, aid, None, panel, name, name, "primary", unit, unit, value, None, rng, "dash", "",
                               "", "normal", "male", age, "diabetes_ckd", False)

    sections = [
        layouts.Section("BIOCHEMISTRY", [row(0, "fasting_glucose", "BIOCHEMISTRY", "Fasting Plasma Glucose",
                                             f"{r.fbs:.0f}", "mg/dL", "70-100"),
                                         row(1, "hba1c", "BIOCHEMISTRY", "HbA1c", f"{r.hba1c:.1f}", "%", "4.0-5.6")], []),
        layouts.Section("RENAL FUNCTION", [
            row(2, "creatinine", "RENAL FUNCTION", "Serum Creatinine", f"{r.creatinine:.2f}", "mg/dL", "0.7-1.3"),
            row(3, "egfr", "RENAL FUNCTION", "eGFR (CKD-EPI 2021)", f"{round(r.egfr):d}", "mL/min/1.73m²", "> 90"),
            row(4, "potassium", "RENAL FUNCTION", "Serum Potassium", f"{r.potassium:.1f}", "mmol/L", "3.5-5.1"),
            row(5, "uacr", "RENAL FUNCTION", "UACR", f"{r.uacr:.0f}", "mg/g", "< 30")], []),
    ]
    report = layouts.Report(f"demo-{r.id}", "grid_classic", "diabetes_ckd", lab, people, "LAB INVESTIGATION REPORT",
                            sections)
    style = layouts.resolve_style(random.Random(f"demo:{r.id}"), layouts.FAMILIES_BY_NAME["grid_classic"])
    layouts.render_capped(report, style, path)


LAYOUTS = {"A": layout_a, "B": layout_b, "C": layout_c}


def write_pdf(r: demo.DemoReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"selvam_{r.id}_{r.date.isoformat()}.pdf"
    LAYOUTS[r.lab](r, path)
    return path


def write_prescription(path: Path, who: Header, date: dt.date, drug: str, dose: str, how: str) -> Path:
    """A one-drug prescription from an invented clinic (a document only: ChronoTrace never reads it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    _text(c, 40, 50, "EXAMPLE DIABETES & KIDNEY CLINIC", 13, BOLD)
    _text(c, 40, 68, "12, Example Road, Chennai 600001  ·  Tel: +91-00-4400-1300", 8)
    c.line(40, PAGE_H - 84, 572, PAGE_H - 84)
    _text(c, 40, 100, f"Patient : {who.name}    Age / Sex : {date.year - who.birth_year} / {who.sex}", 9)
    _text(c, 430, 100, "Date : " + date.strftime("%d-%b-%Y"), 9)
    _text(c, 40, 132, "Rx", 16, BOLD)
    _text(c, 70, 162, f"{drug} {dose}", 11, BOLD)
    _text(c, 70, 180, how, 9)
    _text(c, 40, 260, "Dr. A. Example, MD", 9, BOLD)
    _text(c, 40, 273, "Synthetic demo document", 7)
    c.showPage()
    c.save()
    return path
