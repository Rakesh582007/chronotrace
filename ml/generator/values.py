"""Sample test values and format them the way Indian lab reports print them.

All sampling happens in canonical units; values are then converted into the unit chosen
for the report. These bounds only shape synthetic data; they are not clinical thresholds.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from . import dictionary as d

NORMAL_FRACTION = 0.70


@dataclass(frozen=True)
class Sampling:
    floor: float           # lowest plausible abnormal value (canonical unit)
    ceil: float            # highest plausible abnormal value
    p_low: float           # share of abnormal values below the range (rest above)
    log: bool = False      # sample abnormal values on a log scale (wide, skewed analytes)
    open_low: float | None = None   # normal-sampling floor when the range has no low bound
    open_high: float | None = None  # normal-sampling ceiling when the range has no high bound


SAMPLING: dict[str, Sampling] = {
    "hba1c": Sampling(3.8, 13.0, 0.0),
    "fasting_glucose": Sampling(45, 380, 0.1),
    "pp_glucose": Sampling(45, 450, 0.0, open_low=80),
    "creatinine": Sampling(0.3, 8.0, 0.1, log=True),
    "urea": Sampling(6, 180, 0.1, log=True),
    "uacr": Sampling(1, 2000, 0.0, log=True, open_low=3),
    "sodium": Sampling(118, 158, 0.7),
    "potassium": Sampling(2.5, 7.0, 0.4),
    "tsh": Sampling(0.005, 60, 0.3, log=True),
    "free_t4": Sampling(0.2, 5.0, 0.4),
    "total_cholesterol": Sampling(80, 350, 0.0, open_low=110),
    "ldl": Sampling(20, 260, 0.0, open_low=40),
    "hdl": Sampling(15, 100, 1.0, open_high=85),
    "triglycerides": Sampling(30, 900, 0.0, log=True, open_low=45),
    "alt": Sampling(3, 400, 0.0, log=True, open_low=7),
    "ast": Sampling(5, 350, 0.0, log=True, open_low=10),
    "haemoglobin": Sampling(5.5, 19.5, 0.85),
    "platelets": Sampling(20, 800, 0.6),
    "wbc": Sampling(1.5, 30, 0.3),
    # egfr is not sampled: it is computed from creatinine with CKD-EPI 2021.
}

# Decimals printed in the canonical unit (typical Indian report precision).
CANONICAL_DECIMALS: dict[str, int] = {
    "hba1c": 1, "fasting_glucose": 0, "pp_glucose": 0, "creatinine": 2, "urea": 0,
    "egfr": 0, "uacr": 1, "sodium": 0, "potassium": 1, "tsh": 2, "free_t4": 2,
    "total_cholesterol": 0, "ldl": 0, "hdl": 0, "triglycerides": 0, "alt": 0, "ast": 0,
    "haemoglobin": 1, "platelets": 0, "wbc": 1,
}

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

def auto_decimals(v: float, max_decimals: int = 2) -> int:
    """About three significant figures."""
    if v == 0:
        return 0
    return max(0, min(max_decimals, 2 - math.floor(math.log10(abs(v)))))


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


def is_canonical_equivalent(analyte: dict, unit: str) -> bool:
    """mg% for mg/dL, µIU/mL for mIU/L: same numbers, different spelling."""
    conv = d.conversion(analyte, unit)
    return conv["factor"] == 1 and conv.get("offset", 0) == 0


def value_decimals(analyte: dict, unit: str, printed: float) -> int:
    if is_canonical_equivalent(analyte, unit):
        dec = CANONICAL_DECIMALS[analyte["id"]]
        return max(dec, 3) if 0 < abs(printed) < 0.1 else dec  # TSH 0.014, not 0.01
    conv = d.conversion(analyte, unit)
    if conv["factor"] <= 0.001:  # counts per cumm are printed as whole numbers
        return 0
    return auto_decimals(printed, max_decimals=3 if abs(printed) < 1 else 2)


def format_value(rng: random.Random, analyte: dict, unit: str, printed: float) -> str:
    dec = value_decimals(analyte, unit, printed)
    if dec == 0:
        n = int(round(printed))
        return indian_grouping(n) if n >= 1000 and rng.random() < 0.5 else str(n)
    return f"{printed:.{dec}f}"


def format_bound(analyte: dict, unit: str, canonical: float, basis: str) -> str:
    """A reference-range bound in the printed unit."""
    if is_canonical_equivalent(analyte, unit) and basis == "primary":
        # Print as written in the dictionary: 70 -> "70", 13.0 -> "13.0", 0.7 -> "0.7".
        return str(canonical) if isinstance(canonical, int) else repr(float(canonical))
    v = d.from_canonical(analyte, canonical, unit, basis)
    dec = 0 if d.conversion(analyte, unit)["factor"] <= 0.001 else auto_decimals(v)
    text = f"{v:.{dec}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return indian_grouping(int(text)) if text.isdigit() and int(text) >= 100000 else text


# ---------------------------------------------------------------- sampling

def _uniform(rng: random.Random, lo: float, hi: float, log: bool) -> float:
    if log:
        return math.exp(rng.uniform(math.log(lo), math.log(hi)))
    return rng.uniform(lo, hi)


def sample_canonical(rng: random.Random, analyte: dict, sex: str) -> float:
    """About 70% of values inside the patient's reference range, 30% outside."""
    cfg = SAMPLING[analyte["id"]]
    lo, hi = d.reference_range(analyte, sex)
    if rng.random() < NORMAL_FRACTION:
        nlo = lo if lo is not None else cfg.open_low
        nhi = hi if hi is not None else cfg.open_high
        margin = (nhi - nlo) * 0.02
        return rng.uniform(nlo + margin, nhi - margin)
    sides = []
    if lo is not None and cfg.p_low > 0:
        sides.append(("low", cfg.p_low))
    if hi is not None and cfg.p_low < 1:
        sides.append(("high", 1 - cfg.p_low))
    side = rng.choices([s for s, _ in sides], weights=[w for _, w in sides])[0]
    if side == "low":
        return _uniform(rng, cfg.floor, lo * 0.97, cfg.log)
    return _uniform(rng, hi * 1.03, cfg.ceil, cfg.log)


def egfr_from_creatinine(creatinine_mg_dl: float, age: int, sex: str) -> float:
    formula = d.analytes()["egfr"]["formula"]
    return d.va.egfr_ckd_epi_2021(creatinine_mg_dl, age, sex, formula)


def flag_for(analyte: dict, canonical: float, sex: str) -> str:
    """'H', 'L' or '' against the patient's reference range."""
    lo, hi = d.reference_range(analyte, sex)
    if hi is not None and canonical > hi:
        return "H"
    if lo is not None and canonical < lo:
        return "L"
    return ""


# ---------------------------------------------------------------- reference ranges

def _part(analyte, unit, basis, lo, hi, two_sided_style, high_style) -> tuple[str, str]:
    """Render one (low, high) pair; returns (text, format id)."""
    if lo is not None and hi is not None:
        a, b = format_bound(analyte, unit, lo, basis), format_bound(analyte, unit, hi, basis)
        return {
            "dash": f"{a}-{b}",
            "dash_spaced": f"{a} - {b}",
            "paren": f"({a}-{b})",
        }[two_sided_style], two_sided_style
    if hi is not None:
        b = format_bound(analyte, unit, hi, basis)
        return (f"< {b}" if high_style == "lt" else f"Up to {b}"), high_style
    a = format_bound(analyte, unit, lo, basis)
    return f"> {a}", "gt"


def format_range(rng: random.Random, analyte: dict, unit: str, basis: str, sex: str,
                 two_sided_style: str, high_style: str, p_sex_format: float) -> tuple[str, str]:
    """Reference range text in the printed unit, and which format was used."""
    if d.is_sex_specific(analyte) and rng.random() < p_sex_format:
        inner = "dash" if two_sided_style == "paren" else two_sided_style  # "M: 0.7-1.3 F: 0.6-1.1"
        m = _part(analyte, unit, basis, *d.reference_range(analyte, "male"), inner, high_style)[0]
        f = _part(analyte, unit, basis, *d.reference_range(analyte, "female"), inner, high_style)[0]
        return f"M: {m} F: {f}", "sex"
    lo, hi = d.reference_range(analyte, sex)
    return _part(analyte, unit, basis, lo, hi, two_sided_style, high_style)
