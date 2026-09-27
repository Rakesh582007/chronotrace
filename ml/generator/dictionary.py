"""Access to data/analytes.yaml for the generator: panels, synonyms, units, conversions."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

import validate_analytes as va  # noqa: E402

# Section header printed above each panel, and the analytes it contains (in print order).
PANELS: dict[str, list[str]] = {
    "BIOCHEMISTRY": ["fasting_glucose", "pp_glucose", "hba1c"],
    "RENAL FUNCTION": ["urea", "creatinine", "egfr", "sodium", "potassium", "uacr"],
    "LIPID PROFILE": ["total_cholesterol", "triglycerides", "hdl", "ldl"],
    "LFT": ["alt", "ast"],
    "CBC": ["haemoglobin", "wbc", "platelets"],
    "THYROID PROFILE": ["tsh", "free_t4"],
}


@lru_cache(maxsize=1)
def load() -> dict:
    data = va.load()
    errors = va.validate(data)
    if errors:
        raise ValueError("data/analytes.yaml is invalid: " + "; ".join(errors))
    return data


def analytes() -> dict[str, dict]:
    return {a["id"]: a for a in load()["analytes"]}


def name_pool(analyte: dict) -> list[str]:
    """Names a report may print for this analyte: synonyms plus the canonical name."""
    names = list(analyte["synonyms"])
    if analyte["canonical_name"] not in names:
        names.append(analyte["canonical_name"])
    return names


def basis_synonyms(analyte: dict) -> list[str]:
    """Names that mean the value is on an alternate basis (urea reported as BUN)."""
    return list((analyte.get("alternate_basis") or {}).get("synonyms", []))


def is_mass_unit(unit: str) -> bool:
    return "mol" not in va.norm_unit(unit)


def basis_factor(analyte: dict, unit: str, basis: str) -> float:
    """Multiplier from the alternate basis to the analyte (BUN mg/dL x 2.1437 = urea mg/dL)."""
    if basis == "alternate" and is_mass_unit(unit):
        return analyte["alternate_basis"]["mass_factor"]
    return 1.0


def conversion(analyte: dict, unit: str) -> dict:
    key = va.norm_unit(unit)
    for conv in analyte["conversions"]:
        if va.norm_unit(conv["unit"]) == key:
            return conv
    raise ValueError(f"unknown unit '{unit}' for {analyte['id']}")


def to_canonical(analyte: dict, value: float, unit: str, basis: str = "primary") -> float:
    """Reported value in `unit` -> canonical unit (reuses the step-1 converter)."""
    return va.to_canonical(analyte, value, unit) * basis_factor(analyte, unit, basis)


def from_canonical(analyte: dict, canonical: float, unit: str, basis: str = "primary") -> float:
    """Canonical value -> value as it would be printed in `unit` (inverse of to_canonical)."""
    conv = conversion(analyte, unit)
    return (canonical / basis_factor(analyte, unit, basis) - conv.get("offset", 0)) / conv["factor"]


def reference_range(analyte: dict, sex: str) -> tuple[float | None, float | None]:
    """(low, high) in canonical units for a patient of this sex."""
    ranges = {r["sex"]: r for r in analyte["reference_ranges"]}
    r = ranges.get(sex) or ranges["any"]
    return r["low"], r["high"]


def is_sex_specific(analyte: dict) -> bool:
    return "any" not in {r["sex"] for r in analyte["reference_ranges"]}
