"""Build the test-fixture PDFs in this folder.  Usage:  python tests/fixtures/make_fixtures.py

real_layout.pdf    Copies the layout of one real Indian lab report (column positions, section titles,
                   "Method :" / "Specimen:" / accreditation-code lines, ranges spread over many lines,
                   pdfplumber merging left notes with right range lines). Every value, name, date, code
                   and the lab are INVENTED; nothing is taken from the real report's header.
edge_cases.pdf     Non-numeric and censored values, TSH in uIU/ml, an unknown unit, eGFR with creatinine,
                   only a "Reported" date.
no_header.pdf      Result rows with no column-header line.
scanned.pdf        A page with no text layer.
demo_t2d_ckd_*.pdf Two reports for the demo patient (type 2 diabetes + CKD), used by the API tests
                   and the examples in docs/api.md.
undated.pdf        A report with no printed date (the doctor must enter it).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
PAGE_H = letter[1]
FONT, BOLD = "Helvetica", "Helvetica-Bold"

# Column x positions of the copied layout.
X_SECTION, X_CODE, X_TEST, X_VALUE, X_FLAG, X_UNIT, X_RANGE = 28, 30, 46, 252, 353, 372, 441
HEADER = [(28, "Investigation"), (233, "Observed Value"), (334, "Flag"), (365, "Units"),
          (428, "Biological Reference Interval")]
LAB = "ASTERLANE DIAGNOSTICS"      # invented
CODE = "MC-4821"                   # invented accreditation code


def text(c: canvas.Canvas, x: float, top: float, s: str, size: float = 8, font: str = FONT) -> None:
    """Draw so that pdfplumber reports roughly this `top`."""
    c.setFont(font, size)
    c.drawString(x, PAGE_H - top - size * 0.8, s)


def page_header(c, page: int, pages: int, collected: str | None, reported: str | None, patient: str,
                age_sex: str) -> float:
    text(c, 28, 60, LAB, 12, BOLD)
    text(c, 28, 117, "Lab No. :90001234", 9)
    text(c, 425, 117, "Patient ID : 7000000001", 9)
    text(c, 28, 133, patient, 9)
    if reported:
        text(c, 350, 133, "Registered Date and Time: " + reported.split()[0] + " 07:55", 9)
    text(c, 28, 148, "Age / Sex :" + age_sex, 9)
    if collected:
        text(c, 350, 148, "Collected Date and Time :" + collected, 9)
    text(c, 28, 164, "Ref By. :Dr. A. EXAMPLE", 9)
    if reported:
        text(c, 350, 164, "Reported Date and Time :" + reported, 9)
    text(c, 350, 180, "Sample :" + LAB, 9)
    text(c, 260, 225, f"Final Test Report Page {page} of {pages}", 9)
    for x, label in HEADER:
        text(c, x, 244, label, 9, BOLD)
    return 264.0


def result(c, top, name, value, unit="", rng="", flag="") -> None:
    text(c, X_TEST, top, name, 8, BOLD)
    text(c, X_VALUE, top, value, 8, BOLD)
    if flag:
        text(c, X_FLAG, top, flag, 8, BOLD)
    if unit:
        text(c, X_UNIT, top, unit)
    if rng:
        text(c, X_RANGE, top, rng)


def left(c, top, s, x=X_TEST) -> None:
    if s == CODE:     # printed tiny in the copied layout, so it ends well before the notes column
        from reportlab.pdfbase.pdfmetrics import stringWidth
        size = 8.0
        while x + stringWidth(s, FONT, size) > X_TEST - 4:
            size -= 0.25
        text(c, x, top, s, size)
        return
    text(c, x, top, s)


def rng(c, top, s) -> None:
    text(c, X_RANGE, top, s)


def footer(c) -> None:
    text(c, 538, 735, "Cond ....", 7)


# ---------------------------------------------------------------- real_layout.pdf

def real_layout(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    hdr = dict(collected="15/01/2024 08:40", reported="15/01/2024 14:05", patient="Mr TEST PATIENT",
               age_sex="52 Y / Male")

    # Page 1: glucose with the four-line range, biochemistry, start of the lipid profile.
    page_header(c, 1, 3, **hdr)
    text(c, X_SECTION, 264, "BLOOD - BIOCHEMISTRY", 9, BOLD)
    result(c, 295, "GLUCOSE (FASTING)", "92", "mg/dl", "74 - 99 mg/dl : Normal.")
    left(c, 306, "Method :HEXOKINASE"); rng(c, 306, "100 - 125 mg/dl: IFG/Fair Control")
    left(c, 314, CODE, X_CODE); left(c, 314, "Specimen: FLUORIDE PLASMA"); rng(c, 314, "> 126 mg/dl : DM / Poor Control")
    rng(c, 325, "IFG- Impaired Fasting Glucose. Pls do")
    rng(c, 335, "GTT to confirm Diagnosis.")
    result(c, 348, "CALCIUM -SERUM", "9.4", "mg/dl", "8.6 - 10")
    left(c, 358, "Method :BAPTA")
    left(c, 366, CODE, X_CODE); left(c, 366, "Specimen: SERUM")
    result(c, 384, "CREATININE - SERUM", "0.74", "mg/dl", "0.7 - 1.3")
    left(c, 394, "Method :ALKALINE PICRATE KINETIC")
    left(c, 402, CODE, X_CODE); left(c, 402, "Specimen: SERUM")
    result(c, 420, "UREA - SERUM", "26.0", "mg/dl", "13 - 43")
    left(c, 430, "Method :GLDH - UREASE")
    left(c, 438, CODE, X_CODE); left(c, 438, "Specimen: SERUM")
    result(c, 456, "URIC ACID - SERUM", "5.02", "mg/dl", "3.5-7.2")
    left(c, 466, "Method :URICASE")
    left(c, 474, CODE, X_CODE); left(c, 474, "Specimen: SERUM")
    result(c, 492, "A.S.O. TITRE", "88.2", "IU/ml", "less than 200")
    left(c, 502, "Method :IMMUNOTURBIDIMETRY")
    left(c, 511, "Specimen: SERUM")
    result(c, 528, "C.R.P.", "2.1", "mg/l", "less than 5")
    left(c, 538, "Method :IMMUNOTURBIDIMETRY")
    left(c, 546, CODE, X_CODE); left(c, 546, "Specimen: SERUM")
    text(c, X_SECTION, 600, "LIPID PROFILE", 9, BOLD)
    result(c, 616, "CHOLESTEROL - SERUM", "176", "mg/dl", "NCEP guidelines ATP III classification")
    left(c, 627, "Method :ENZYMATIC/CHOD/POD"); rng(c, 627, "(Coronary heart disease risk)")
    left(c, 635, CODE, X_CODE); left(c, 635, "Specimen: SERUM")
    rng(c, 646, "Child(upto19 yrs)")
    rng(c, 655, "Less than 170 mg/dl : Desirable")
    rng(c, 665, "170 - 199 mg/dl : Borderline High")
    rng(c, 675, ">= 200 mg/dl : High")
    rng(c, 694, "Adult(Above 19 yrs)")
    rng(c, 704, "Less than 200 mg/dl : Desirable")
    rng(c, 714, "200 - 239 mg/dl : Borderline High")
    footer(c)
    c.showPage()

    # Page 2: HDL / TG / LDL with merged Specimen + range rows, VLDL, TC/HDL ratio.
    page_header(c, 2, 3, **hdr)
    result(c, 264, "HDL CHOLESTEROL (DIRECT)", "52", "mg/dl", "NCEP guidelines ATP III classification")
    left(c, 274, "Method :DIRECT MEASURE - POLYMER POLY"); rng(c, 274, "(Coronary heart disease risk)")
    left(c, 283, CODE, X_CODE); left(c, 283, "ANION")
    left(c, 292, "Specimen: SERUM"); rng(c, 292, "Less than 40 mg/dl : High Risk")
    rng(c, 303, "40 - 60 mg/dl : Normal Risk")
    rng(c, 313, ">= 60 mg/dl : Low Risk")
    result(c, 326, "TRIGLYCERIDES", "104", "mg/dl", "NCEP guidelines ATP III classification")
    left(c, 336, "Method :GPO - POD"); rng(c, 336, "(Coronary heart disease risk)")
    left(c, 345, CODE, X_CODE); left(c, 345, "Specimen: SERUM")
    rng(c, 355, "Less than 150 mg/dl : Desirable")
    rng(c, 365, "150 - 199 mg/dl : Normal Risk")
    rng(c, 375, "200 - 499 mg/dl : High Risk")
    rng(c, 384, ">= 500 mg/dl : Very High Risk")
    result(c, 397, "LDL CHOLESTEROL (DIRECT)", "102", "mg/dl", "NCEP guidelines ATP III classification")
    left(c, 408, "Method :HOMOGENOUS ENZYMATIC"); rng(c, 408, "(Coronary heart disease risk)")
    left(c, 416, CODE, X_CODE); left(c, 416, "COLORIMETRIC")
    left(c, 426, "Specimen: SERUM"); rng(c, 426, "Less than 129 mg/dl : Normal")
    rng(c, 437, "139-159 mg/dl : Borderline High")
    rng(c, 446, "160-189 mg/dl : High")
    rng(c, 456, ">= 190 mg/dl : Very High")
    result(c, 469, "VLDL CHOLESTEROL", "20.8", "mg/dl")
    left(c, 480, "Method :CALCULATED")
    left(c, 489, "Specimen: SERUM")
    result(c, 505, "TOTAL CHO / HDL RATIO", "3.38", "", "Less than 3.5 : Low Risk")
    left(c, 516, "Method :CALCULATED"); rng(c, 516, "3.5 - 5.0 : Normal Risk")
    left(c, 525, "Specimen: SERUM"); rng(c, 525, "> 5.0 : High Risk")
    text(c, X_SECTION, 541, "BLOOD - BIOCHEMISTRY", 9, BOLD)
    footer(c)
    c.showPage()

    # Page 3: HbA1c with a nine-line interpretation, signature, end of report.
    page_header(c, 3, 3, **hdr)
    result(c, 264, "HB A1C", "5.6", "%", "Nondiabetic : Less than 5.6 %")
    left(c, 274, "Method : HPLC"); rng(c, 274, "Risk of developing diabetes: 5.7 - 6.4")
    left(c, 283, CODE, X_CODE); left(c, 283, "Specimen: EDTA BLOOD"); rng(c, 283, "%")
    rng(c, 293, "Diabetes : More than or Equal")
    rng(c, 303, "to 6.5%")
    rng(c, 313, "In known Diabetics :-")
    rng(c, 322, "Good Control : 6 - 7 %")
    rng(c, 332, "Fair Control : 7 - 8 %")
    rng(c, 342, "Poor Control : More than 8 %")
    text(c, 419, 397, "Dr A Example Pathologist", 9)
    text(c, 425, 411, "MBBS ,MD Pathology.", 9)
    text(c, 269, 426, "* End of Report *", 9)
    text(c, 117, 493, f"Test marked with NABL symbol are accredited by NABL vide certificate no {CODE}", 8)
    footer(c)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- edge_cases.pdf

def edge_cases(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    page_header(c, 1, 1, collected=None, reported="16/01/2024 11:20", patient="Mr EDGE CASE", age_sex="57 Y / Male")
    text(c, X_SECTION, 264, "BLOOD - BIOCHEMISTRY", 9, BOLD)
    result(c, 280, "SERUM CREATININE", "1.62", "mg/dl", "0.7 - 1.3", "H")
    result(c, 296, "eGFR (CKD-EPI 2021)", "49", "mL/min/1.73m2", "> 90", "L")
    result(c, 312, "TSH (ULTRASENSITIVE)", "3.2", "uIU/ml", "0.35 - 5.5")
    result(c, 328, "TRIGLYCERIDES", ">1000", "mg/dl", "Less than 150")
    result(c, 344, "SERUM SODIUM", "138", "mmol/xx", "136 - 145")
    result(c, 360, "SERUM POTASSIUM", "Haemolysed", "mmol/l", "3.5 - 5.1")
    result(c, 376, "URINE ALBUMIN/CREATININE RATIO", "<0.5", "mg/g", "Less than 30")
    text(c, X_SECTION, 400, "SEROLOGY", 9, BOLD)
    result(c, 416, "HBsAg", "Non Reactive", "", "Non Reactive")
    result(c, 432, "URINE SUGAR", "Nil", "", "Nil")
    result(c, 448, "HIV I & II ANTIBODY", "Negative", "", "Negative")
    footer(c)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- no_header.pdf

def no_header(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    text(c, 28, 60, "Kestrelline Labs", 12, BOLD)
    text(c, 28, 90, "Collected On : 02-Feb-2024 09:10", 9)
    for i, (name, value, unit, rng_) in enumerate([
            ("Fasting Blood Sugar", "124", "mg/dL", "70-100"), ("HbA1c", "6.9", "%", "4.0-5.6"),
            ("Serum Creatinine", "1.1", "mg/dL", "0.7-1.3"), ("Serum Potassium", "4.4", "mmol/L", "3.5-5.1")]):
        top = 130 + 16 * i
        text(c, 40, top, name, 9)
        text(c, 220, top, value, 9)
        text(c, 300, top, unit, 9)
        text(c, 380, top, rng_, 9)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- scanned.pdf

def scanned(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    c.setFillGray(0.85)
    for i in range(12):                       # grey bars standing in for scanned text
        c.rect(40, 700 - 22 * i, 400 - 17 * (i % 5), 9, stroke=0, fill=1)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- demo reports (T2D + CKD)

DEMO = [
    ("demo_t2d_ckd_1.pdf", "08/01/2024 08:15", "08/01/2024 16:30",
     {"hba1c": "8.4", "glucose": "162", "creat": "1.58", "urea": "54.2", "egfr": "49", "k": "5.1", "uacr": "286", "tsh": "2.8"}),
    ("demo_t2d_ckd_2.pdf", "11/04/2024 08:05", "11/04/2024 17:10",
     {"hba1c": "7.6", "glucose": "138", "creat": "1.72", "urea": "61.0", "egfr": "44", "k": "5.4", "uacr": ">300", "tsh": "3.1"}),
]


def demo(path: Path, collected: str | None, reported: str | None, v: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    page_header(c, 1, 1, collected=collected, reported=reported, patient="Mr DEMO PATIENT", age_sex="58 Y / Male")
    text(c, X_SECTION, 264, "BLOOD - BIOCHEMISTRY", 9, BOLD)
    result(c, 280, "GLUCOSE (FASTING)", v["glucose"], "mg/dl", "74 - 99 mg/dl : Normal.", "H")
    left(c, 291, "Method :HEXOKINASE"); rng(c, 291, "100 - 125 mg/dl: IFG/Fair Control")
    result(c, 306, "HB A1C", v["hba1c"], "%", "Nondiabetic : Less than 5.6 %", "H")
    left(c, 317, "Method : HPLC")
    result(c, 332, "CREATININE - SERUM", v["creat"], "mg/dl", "0.7 - 1.3", "H")
    result(c, 348, "UREA - SERUM", v["urea"], "mg/dl", "13 - 43", "H")
    result(c, 364, "eGFR (CKD-EPI 2021)", v["egfr"], "mL/min/1.73m2", "> 90", "L")
    result(c, 380, "POTASSIUM - SERUM", v["k"], "mmol/l", "3.5 - 5.1", "H" if float(v["k"]) > 5.1 else "")
    result(c, 396, "URINE ALBUMIN/CREATININE RATIO", v["uacr"], "mg/g", "Less than 30", "H")
    result(c, 412, "TSH (ULTRASENSITIVE)", v["tsh"], "uIU/ml", "0.35 - 5.5")
    result(c, 428, "VITAMIN B12", "312", "pg/ml", "211 - 911")
    text(c, X_SECTION, 450, "URINE EXAMINATION", 9, BOLD)
    result(c, 466, "URINE KETONES", "Negative", "", "Negative")
    result(c, 482, "URINE GLUCOSE", "Nil", "", "Nil")
    text(c, 269, 516, "* End of Report *", 9)
    c.showPage()
    c.save()


def main() -> None:
    real_layout(HERE / "real_layout.pdf")
    edge_cases(HERE / "edge_cases.pdf")
    no_header(HERE / "no_header.pdf")
    scanned(HERE / "scanned.pdf")
    for name, collected, reported, values in DEMO:
        demo(HERE / name, collected, reported, values)
    demo(HERE / "undated.pdf", None, None, {**DEMO[0][3], "hba1c": "8.1", "glucose": "149"})
    print("fixtures written to", HERE)


if __name__ == "__main__":
    main()
