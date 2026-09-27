"""Format test values and reference ranges the way Indian lab reports print them.

Values are produced in canonical units (see clinical.py), converted into the unit chosen
for the report, then rounded to the precision a lab would print in that unit: "62 - 115"
µmol/L rather than "61.9 - 115", platelets per cumm to the nearest thousand.
"""

from __future__ import annotations

import random
from typing import Callable

from . import dictionary as d

# Decimals printed in the canonical unit and its respellings (mg% for mg/dL, µIU/mL for mIU/L).
CANONICAL_DECIMALS: dict[str, int] = {
    "hba1c": 1, "fasting_glucose": 0, "pp_glucose": 0, "creatinine": 2, "urea": 0,
    "egfr": 0, "uacr": 1, "sodium": 0, "potassium": 1, "tsh": 2, "free_t4": 2,
    "total_cholesterol": 0, "ldl": 0, "hdl": 0, "triglycerides": 0, "alt": 0, "ast": 0,
    "haemoglobin": 1, "platelets": 0, "wbc": 1,
}

# Decimals for converted units. Every non-canonical, non-count unit in data/analytes.yaml
# must be listed (tests enforce this).
SI_DECIMALS: dict[tuple[str, str], int] = {
    ("hba1c", "mmol/mol"): 0,
    ("fasting_glucose", "mmol/L"): 1, ("pp_glucose", "mmol/L"): 1,
    ("creatinine", "µmol/L"): 0,
    ("urea", "mmol/L"): 1,
    ("uacr", "mg/mmol"): 1,
    ("free_t4", "pmol/L"): 1,
    ("total_cholesterol", "mmol/L"): 2, ("ldl", "mmol/L"): 2, ("hdl", "mmol/L"): 2,
    ("triglycerides", "mmol/L"): 2,
    ("alt", "µkat/L"): 2, ("ast", "µkat/L"): 2,
    ("haemoglobin", "g/L"): 0, ("haemoglobin", "mmol/L"): 1,
    ("platelets", "lakh/cumm"): 2, ("platelets", "lakhs/cumm"): 2, ("platelets", "lakh/µL"): 2,
}
_SI = {(aid, d.va.norm_unit(u)): dec for (aid, u), dec in SI_DECIMALS.items()}

# Counts per cumm / µL are whole numbers rounded to a step: platelets to the nearest thousand.
COUNT_STEP: dict[str, int] = {"platelets": 1000, "wbc": 10}

METHODS: dict[str, list[str]] = {
    "hba1c": ["HPLC", "Immunoturbidimetry", "Enzymatic"],
    "fasting_glucose": ["Hexokinase", "GOD-POD"],
    "pp_glucose": ["Hexokinase", "GOD-POD"],
    "creatinine": ["Enzymatic", "Jaffe Kinetic", "Modified Jaffe"],
    "urea": ["Urease-GLDH", "Urease UV"],
    "egfr": ["Calculated", "CKD-EPI 2021"],
    "uacr": ["Immunoturbidimetry", "Calculated"],
    "sodium": ["ISE Indirect", "ISE Direct"],
    "potassium": ["ISE Indirect", "ISE Direct"],
    "tsh": ["CLIA", "ECLIA", "CMIA"],
    "free_t4": ["CLIA", "ECLIA", "CMIA"],
    "total_cholesterol": ["CHOD-POD", "Enzymatic"],
    "ldl": ["Calculated", "Direct Measure"],
    "hdl": ["Direct Measure", "Enzymatic"],
    "triglycerides": ["GPO-PAP", "Enzymatic"],
    "alt": ["IFCC without P5P", "Kinetic UV"],
    "ast": ["IFCC without P5P", "Kinetic UV"],
    "haemoglobin": ["SLS Photometry", "Cyanmethemoglobin"],
    "platelets": ["Electrical Impedance", "Flow Cytometry"],
    "wbc": ["Electrical Impedance", "Flow Cytometry"],
}

# Range formats. Two-sided: dash, dash_spaced, paren. High-only: lt, upto.
# Sex-specific: sex. Low-only ranges (HDL, eGFR) print as "> 40" (gt).
RANGE_FORMATS = ["dash", "dash_spaced", "lt", "upto", "sex", "paren"]
FLAG_STYLES = [("H", "L"), ("High", "Low"), ("*H", "*L")]


# ---------------------------------------------------------------- numbers

def indian_grouping(n: int) -> str:
    """250000 -> '2,50,000' (lakh grouping)."""
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + out


def parse_number(text: str) -> float:
    return float(text.replace(",", ""))


def format_number(x: float, decimals: int, group: bool = False, step: int | None = None) -> str:
    """Round to `step` (whole numbers) or to `decimals`, then print."""
    if step:
        x = round(x / step) * step
    if decimals == 0:
        n = int(round(x))
        return indian_grouping(n) if group and n >= 1000 else str(n)
    return f"{x:.{decimals}f}"


def dictionary_number(x: float) -> str:
    """Print a reference bound as written in a data file: 70 -> '70', 13.0 -> '13.0'."""
    return str(x) if isinstance(x, int) else repr(float(x))


def is_canonical_equivalent(analyte: dict, unit: str) -> bool:
    """mg% for mg/dL, µIU/mL for mIU/L: same numbers, different spelling."""
    conv = d.conversion(analyte, unit)
    return conv["factor"] == 1 and conv.get("offset", 0) == 0


def precision(analyte: dict, unit: str, basis: str = "primary") -> tuple[int, int | None]:
    """(decimals, rounding step) for values and range bounds printed in `unit`."""
    if basis == "alternate" and d.is_mass_unit(unit):
        return 0, None                                      # BUN in mg/dL: whole numbers
    if is_canonical_equivalent(analyte, unit):
        return CANONICAL_DECIMALS[analyte["id"]], None
    if d.conversion(analyte, unit)["factor"] <= 0.001:      # per cumm / per µL counts
        return 0, COUNT_STEP[analyte["id"]]
    return _SI[(analyte["id"], d.va.norm_unit(unit))], None


def format_value(analyte: dict, unit: str, basis: str, printed: float, group: bool) -> str:
    dec, step = precision(analyte, unit, basis)
    if step is None and 0 < abs(printed) < 0.1:
        dec = max(dec, 3)   # TSH 0.014, not 0.01
    return format_number(printed, dec, group, step)


def format_bound(analyte: dict, unit: str, canonical: float, basis: str, group: bool = False) -> str:
    """A reference-range bound in the printed unit, at the same precision as the values."""
    if is_canonical_equivalent(analyte, unit) and basis == "primary":
        return dictionary_number(canonical)
    dec, step = precision(analyte, unit, basis)
    return format_number(d.from_canonical(analyte, canonical, unit, basis), dec, group, step)


# ---------------------------------------------------------------- flags

def flag_from_range(lo: float | None, hi: float | None, x: float) -> str:
    if hi is not None and x > hi:
        return "H"
    if lo is not None and x < lo:
        return "L"
    return ""


def flag_for(analyte: dict, canonical: float, sex: str) -> str:
    """'H', 'L' or '' against the patient's reference range."""
    return flag_from_range(*d.reference_range(analyte, sex), canonical)


def egfr_from_creatinine(creatinine_mg_dl: float, age: int, sex: str) -> float:
    formula = d.analytes()["egfr"]["formula"]
    return d.va.egfr_ckd_epi_2021(creatinine_mg_dl, age, sex, formula)


# ---------------------------------------------------------------- reference ranges

def render_part(lo, hi, fmt: Callable[[float], str], two_sided_style: str, high_style: str) -> tuple[str, str]:
    """Render one (low, high) pair; returns (text, format id)."""
    if lo is not None and hi is not None:
        a, b = fmt(lo), fmt(hi)
        return {"dash": f"{a}-{b}", "dash_spaced": f"{a} - {b}", "paren": f"({a}-{b})"}[two_sided_style], \
            two_sided_style
    if hi is not None:
        b = fmt(hi)
        return (f"< {b}" if high_style == "lt" else f"Up to {b}"), high_style
    return f"> {fmt(lo)}", "gt"


def render_range(rng: random.Random, range_for: Callable[[str], tuple], sex_specific: bool,
                 fmt: Callable[[float], str], sex: str, two_sided_style: str, high_style: str,
                 p_sex_format: float) -> tuple[str, str]:
    if sex_specific and rng.random() < p_sex_format:
        inner = "dash" if two_sided_style == "paren" else two_sided_style  # "M: 0.7-1.3 F: 0.6-1.1"
        m = render_part(*range_for("male"), fmt, inner, high_style)[0]
        f = render_part(*range_for("female"), fmt, inner, high_style)[0]
        return f"M: {m} F: {f}", "sex"
    return render_part(*range_for(sex), fmt, two_sided_style, high_style)


def format_range(rng: random.Random, analyte: dict, unit: str, basis: str, sex: str,
                 two_sided_style: str, high_style: str, p_sex_format: float,
                 group: bool = False) -> tuple[str, str]:
    """Reference range text in the printed unit, and which format was used."""
    return render_range(
        rng, lambda s: d.reference_range(analyte, s), d.is_sex_specific(analyte),
        lambda x: format_bound(analyte, unit, x, basis, group), sex,
        two_sided_style, high_style, p_sex_format)
