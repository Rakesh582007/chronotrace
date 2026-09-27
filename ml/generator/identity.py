"""Fictional labs, people, dates and filler text for synthetic reports.

Lab names are invented from made-up stems; people come from Faker en_IN. No real lab
brands, no phone numbers that could reach a real line (the area code 00 is invalid),
and e-mail domains use the reserved .example TLD.
"""

from __future__ import annotations

import datetime as dt
import random

from faker import Faker

LAB_STEMS = [
    "Aravel", "Nirvika", "Sumedhya", "Ilavira", "Tarvik", "Varnika", "Zenora", "Oravyn",
    "Kesarin", "Mridval", "Pranvi", "Sathvara", "Utkira", "Vedhya", "Yashvin", "Daksira",
    "Heliora", "Janvika", "Lumira", "Riddhan",
]
LAB_SUFFIXES = [
    "Diagnostics", "Clinical Laboratory", "Diagnostic Centre", "Pathology Centre", "Labs",
    "Biochem Laboratory", "Health Diagnostics", "Clinical Labs Pvt. Ltd.",
]
TAGLINES = [
    "Accurate | Reliable | Timely", "Clinical Pathology & Biochemistry",
    "Quality Diagnostics Since 1998", "Committed to Precision", "Complete Laboratory Services",
    "Pathology | Biochemistry | Haematology",
]
REPORT_TITLES = ["LABORATORY REPORT", "TEST REPORT", "LAB INVESTIGATION REPORT", "FINAL REPORT"]
DOCTOR_DEGREES = [
    ("MD (Pathology)", "Consultant Pathologist"), ("MBBS, DCP", "Pathologist"),
    ("MD (Biochemistry)", "Consultant Biochemist"), ("MD, DNB (Pathology)", "Lab Director"),
    ("MSc, PhD (Biochemistry)", "Chief Biochemist"),
]
SAMPLE_TYPES = ["Serum", "Serum / EDTA Whole Blood", "Plasma / Serum", "EDTA Whole Blood, Serum, Urine"]

PANEL_NOTES: dict[str, list[str]] = {
    "BIOCHEMISTRY": [
        "Interpretation (HbA1c): Non-diabetic < 5.7 %, Prediabetes 5.7 - 6.4 %, Diabetes >= 6.5 %",
        "Fasting sample to be collected after an overnight fast of 8-10 hours.",
        "Post prandial sample collected 2 hours after meal.",
    ],
    "RENAL FUNCTION": [
        "eGFR calculated using the CKD-EPI 2021 equation (race-free).",
        "Albuminuria categories: A1 < 30 mg/g, A2 30 - 300 mg/g, A3 > 300 mg/g",
        "Kindly correlate with hydration status and medication history.",
    ],
    "LIPID PROFILE": [
        "Total Cholesterol: Desirable < 200 mg/dL, Borderline High 200 - 239 mg/dL, High >= 240 mg/dL",
        "LDL calculated by Friedewald equation when triglycerides are below 400 mg/dL.",
        "A fasting sample of 10-12 hours is recommended for lipid profile.",
    ],
    "LFT": [
        "Transaminase levels may be raised after strenuous exercise.",
        "Kindly correlate clinically.",
    ],
    "CBC": [
        "Platelet count verified on peripheral smear.",
        "Kindly correlate clinically.",
    ],
    "THYROID PROFILE": [
        "TSH shows diurnal variation; values are highest in early morning.",
        "Pregnancy-specific reference ranges apply to pregnant women.",
    ],
}
GENERIC_NOTES = [
    "Note: Results relate only to the sample as received.",
    "Test results should be interpreted by a registered medical practitioner.",
    "This is an electronically authenticated report.",
    "Values outside the reference range are printed in bold.",
]
DISCLAIMERS = [
    "This is a computer generated report and does not require a signature.",
    "Results are for the use of the referring doctor only.",
    "Partial reproduction of this report is not permitted.",
]


def lab(rng: random.Random) -> dict:
    stem = rng.choice(LAB_STEMS)
    return {
        "name": f"{stem} {rng.choice(LAB_SUFFIXES)}",
        "initials": stem[:2].upper(),
        "tagline": rng.choice(TAGLINES),
        "email": f"reports@{stem.lower()}.example",
        "phone": f"Tel: +91-00-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
    }


def people(fake: Faker, rng: random.Random) -> dict:
    sex = rng.choice(["male", "female"])
    if sex == "male":
        first, title = fake.first_name_male(), "Mr."
    else:
        first, title = fake.first_name_female(), rng.choice(["Mrs.", "Ms."])
    degree, role = rng.choice(DOCTOR_DEGREES)
    collected = dt.datetime(2023, 1, 1) + dt.timedelta(
        days=rng.randint(0, 1275), hours=rng.randint(7, 11), minutes=rng.randint(0, 59))
    reported = collected + dt.timedelta(hours=rng.randint(4, 40))
    address = fake.address().replace("\n", ", ")
    return {
        "patient_name": f"{title} {first} {fake.last_name()}",
        "sex": sex,
        "age": rng.randint(25, 85),
        "patient_id": f"{rng.choice('ABCDEFGHKMPRT')}{rng.randint(10, 99)}-{rng.randint(100000, 999999)}",
        "sample_id": f"{rng.randint(20, 26)}{rng.choice('ABCDEFGH')}{rng.randint(1000000, 9999999)}",
        "referrer": f"Dr. {fake.first_name()} {fake.last_name()}",
        "pathologist": f"Dr. {fake.first_name()} {fake.last_name()}",
        "pathologist_degree": degree,
        "pathologist_role": role,
        "collected": collected,
        "reported": reported,
        "sample_type": rng.choice(SAMPLE_TYPES),
        "lab_address": address,
    }


def fmt_datetime(rng_style: int, when: dt.datetime) -> str:
    return [
        when.strftime("%d/%m/%Y %H:%M"),
        when.strftime("%d-%b-%Y %I:%M %p"),
        when.strftime("%d.%m.%Y %H:%M"),
    ][rng_style % 3]
