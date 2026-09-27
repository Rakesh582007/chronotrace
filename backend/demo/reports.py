"""Render the demo patient's reports as PDFs in three lab layouts (all names and labs are invented).

A  ASTERLANE DIAGNOSTICS: column header "Investigation / Observed Value / Flag / Units / Biological
   Reference Interval", tests indented under section titles, method lines (the layout of the step-4
   test fixture).
B  Kestrelline Labs: no column header; test, value, unit and range spaced across the line.
C  Varnika Clinical Labs: rendered by the synthetic report generator (ml/generator) with a fixed seed.

Each report prints the lab's own eGFR (rounded); ChronoTrace recomputes it from creatinine anyway.
"""

from __future__ import annotations

import datetime as dt
import random
import sys
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
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    reported = r.date + dt.timedelta(days=1 if r.date.day % 2 else 0)
    _text(c, 28, 60, demo.LABS["A"], 12, BOLD)
    _text(c, 28, 117, f"Lab No. :9{r.date.strftime('%y%m%d')}1", 9)
    _text(c, 425, 117, "Patient ID : 7000004212", 9)
    _text(c, 28, 133, "Mr K. SELVAM", 9)
    _text(c, 28, 148, f"Age / Sex :{r.date.year - demo.PATIENT['birth_year']} Y / Male", 9)
    _text(c, 350, 148, "Collected Date and Time :" + _when(r.date, 8), 9)
    _text(c, 28, 164, "Ref By. :Dr. A. EXAMPLE", 9)
    _text(c, 350, 164, "Reported Date and Time :" + _when(reported, 16), 9)
    _text(c, 260, 225, "Final Test Report Page 1 of 1", 9)
    for x, label in [(28, "Investigation"), (233, "Observed Value"), (334, "Flag"), (365, "Units"),
                     (428, "Biological Reference Interval")]:
        _text(c, x, 244, label, 9, BOLD)
    top = 264.0
    for section, name, value, unit, rng in _rows(r):
        if section:
            _text(c, 28, top, section, 9, BOLD)
            top += 16
        _text(c, 46, top, name, 8, BOLD)
        _text(c, 252, top, value, 8, BOLD)
        _text(c, 372, top, unit)
        _text(c, 441, top, rng)
        top += 11
        _text(c, 46, top, "Method :" + {"GLUCOSE (FASTING)": "HEXOKINASE", "HB A1C": "HPLC"}.get(name, "AUTOMATED"))
        top += 16
    _text(c, 269, top + 20, "* End of Report *", 9)
    c.showPage()
    c.save()


def layout_b(r: demo.DemoReport, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    _text(c, 40, 60, demo.LABS["B"], 13, BOLD)
    _text(c, 40, 78, "Complete Laboratory Services", 9)
    _text(c, 40, 104, f"Name : Mr K. Selvam   Age : {r.date.year - demo.PATIENT['birth_year']} Yrs   Sex : Male", 9)
    _text(c, 40, 118, "Collected On : " + r.date.strftime("%d-%b-%Y") + " 09:10", 9)
    _text(c, 330, 118, "Reported On : " + r.date.strftime("%d-%b-%Y") + " 18:40", 9)
    rows = [("Fasting Blood Sugar", f"{r.fbs:.0f}", "mg/dL", "70-100"), ("HbA1c", f"{r.hba1c:.1f}", "%", "4.0-5.6"),
            ("Serum Creatinine", f"{r.creatinine:.2f}", "mg/dL", "0.7-1.3"),
            ("eGFR", f"{round(r.egfr):d}", "mL/min/1.73m2", ">90"),
            ("Serum Potassium", f"{r.potassium:.1f}", "mmol/L", "3.5-5.1"), ("Urine ACR", f"{r.uacr:.0f}", "mg/g", "<30")]
    for i, (name, value, unit, rng) in enumerate(rows):
        top = 150 + 17 * i
        _text(c, 40, top, name, 9)
        _text(c, 220, top, value, 9)
        _text(c, 300, top, unit, 9)
        _text(c, 400, top, rng, 9)
    _text(c, 40, 280, "-- End of Report --", 9)
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
