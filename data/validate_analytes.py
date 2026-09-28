"""Validate data/analytes.yaml and provide small helpers used by later steps.

Usage:  python data/validate_analytes.py [path/to/analytes.yaml]
Exit code 0 when the dictionary is valid, 1 otherwise.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("analytes.yaml")

EXPECTED_COUNT = 20
REQUIRED_FIELDS = [
    "id", "canonical_name", "synonyms", "loinc", "loinc_name", "specimen",
    "canonical_unit", "conversions", "reference_ranges", "reference_range_source", "rcv", "system",
]
SYSTEM_FIELDS = ["id", "name", "order", "headline"]
RCV_STATUSES = {"verified", "unverified", "not_established"}
SEXES = {"any", "male", "female"}
RCV_Z = 1.96 * math.sqrt(2)  # two-sided 95%, two measurements
RCV_TOLERANCE = 0.1  # percentage points; the file stores one decimal


def load(path: Path = DEFAULT_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def norm_text(s: str) -> str:
    """Normalise a test name for matching: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def norm_unit(u: str) -> str:
    """Normalise a unit for lookup: lowercase, no spaces, micro sign -> 'u'."""
    return re.sub(r"\s+", "", str(u)).replace("µ", "u").replace("μ", "u").lower()


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC codes end in a mod-10 (Luhn) check digit, e.g. 2160-0."""
    m = re.fullmatch(r"(\d{1,7})-(\d)", str(code))
    if not m:
        return False
    body, check = m.group(1), int(m.group(2))
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:  # rightmost digit and every second one from it are doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == check


def rcv_percent(cv_i: float, cv_a: float) -> float:
    return RCV_Z * math.hypot(cv_i, cv_a)


def validate(data: dict) -> list[str]:
    """Return a list of human-readable errors (empty when valid)."""
    errors: list[str] = []
    analytes = (data or {}).get("analytes")
    if not isinstance(analytes, list):
        return ["top-level 'analytes' list is missing"]
    if len(analytes) != EXPECTED_COUNT:
        errors.append(f"expected {EXPECTED_COUNT} analytes, found {len(analytes)}")

    ids: set[str] = set()
    loincs: dict[str, str] = {}
    names: dict[str, str] = {}  # normalised synonym -> analyte id

    for a in analytes:
        aid = a.get("id", "<missing id>")
        where = f"[{aid}]"

        for field in REQUIRED_FIELDS:
            if a.get(field) in (None, "", []):
                errors.append(f"{where} missing field '{field}'")
        if aid in ids:
            errors.append(f"{where} duplicate id")
        ids.add(aid)

        # Synonyms: 2+, and no name may point to two analytes.
        synonyms = a.get("synonyms") or []
        if len(synonyms) < 2:
            errors.append(f"{where} needs at least 2 synonyms, has {len(synonyms)}")
        report_synonyms = a.get("report_synonyms", [])
        if not isinstance(report_synonyms, list) or not all(isinstance(n, str) and n for n in report_synonyms):
            errors.append(f"{where} report_synonyms must be a list of names")
            report_synonyms = []
        all_names = [a.get("canonical_name", "")] + list(synonyms) + list(report_synonyms)
        all_names += (a.get("alternate_basis") or {}).get("synonyms", [])
        for name in {norm_text(n) for n in all_names if n}:
            if name in names and names[name] != aid:
                errors.append(f"{where} synonym '{name}' also used by [{names[name]}]")
            names[name] = aid

        # LOINC codes: format, check digit, uniqueness.
        codes = [a.get("loinc")] + [x.get("code") for x in a.get("loinc_alternates", [])]
        if a.get("alternate_basis"):
            codes.append(a["alternate_basis"].get("loinc"))
        for code in codes:
            if not loinc_check_digit_ok(code):
                errors.append(f"{where} LOINC '{code}' has bad format or check digit")
            elif code in loincs:
                errors.append(f"{where} LOINC '{code}' also used by [{loincs[code]}]")
            else:
                loincs[code] = aid

        # Units: canonical unit present as identity, positive factors, no duplicates.
        canonical = a.get("canonical_unit")
        seen_units: set[str] = set()
        has_identity = False
        for conv in a.get("conversions") or []:
            unit, factor = conv.get("unit"), conv.get("factor")
            offset = conv.get("offset", 0)
            key = norm_unit(unit)
            if key in seen_units:
                errors.append(f"{where} unit '{unit}' listed twice")
            seen_units.add(key)
            if not isinstance(factor, (int, float)) or factor <= 0:
                errors.append(f"{where} unit '{unit}' needs a positive factor")
            if not isinstance(offset, (int, float)):
                errors.append(f"{where} unit '{unit}' has a non-numeric offset")
            if key == norm_unit(canonical):
                has_identity = factor == 1 and offset == 0
        if canonical and not has_identity:
            errors.append(f"{where} canonical unit '{canonical}' must be listed with factor 1, offset 0")

        # Reference ranges: adult, both sexes covered, low < high.
        sexes = set()
        for rr in a.get("reference_ranges") or []:
            sex, low, high = rr.get("sex"), rr.get("low"), rr.get("high")
            if sex not in SEXES:
                errors.append(f"{where} reference range sex '{sex}' not in {sorted(SEXES)}")
            sexes.add(sex)
            if low is None and high is None:
                errors.append(f"{where} reference range for '{sex}' has no bounds")
            if low is not None and high is not None and not low < high:
                errors.append(f"{where} reference range for '{sex}' has low >= high")
        if "any" not in sexes and not {"male", "female"} <= sexes:
            errors.append(f"{where} reference ranges must cover 'any' or both 'male' and 'female'")

        # RCV: status and source always; numbers must match the formula.
        rcv = a.get("rcv") or {}
        status = rcv.get("status")
        if status not in RCV_STATUSES:
            errors.append(f"{where} rcv.status '{status}' not in {sorted(RCV_STATUSES)}")
        if not rcv.get("source"):
            errors.append(f"{where} rcv.source is required (say where the number comes from, or why it is missing)")
        pct = rcv.get("percent")
        if status == "not_established":
            if pct is not None:
                errors.append(f"{where} rcv.percent must be null when status is not_established")
        elif not isinstance(pct, (int, float)) or pct <= 0:
            errors.append(f"{where} rcv.percent must be a positive number")
        elif rcv.get("method") == "guideline":
            # A threshold stated by a guideline (e.g. KDIGO's >20% eGFR change), not computed from CVs.
            if "practice point" not in str(rcv.get("source", "")).lower() and "recommendation" not in                     str(rcv.get("source", "")).lower():
                errors.append(f"{where} a guideline rcv must cite the practice point or recommendation in its source")
        elif rcv.get("method") != "derived_from_creatinine":
            cv_i, cv_a = rcv.get("cv_i"), rcv.get("cv_a")
            if not all(isinstance(v, (int, float)) and v > 0 for v in (cv_i, cv_a)):
                errors.append(f"{where} rcv needs positive cv_i and cv_a")
            elif abs(rcv_percent(cv_i, cv_a) - pct) > RCV_TOLERANCE:
                errors.append(
                    f"{where} rcv.percent {pct} does not match cv_i/cv_a "
                    f"(expected {rcv_percent(cv_i, cv_a):.1f})"
                )

        # Optional guideline target: low and/or high, a label, a source and a status.
        target = a.get("target")
        if target is not None:
            lo, hi = target.get("low"), target.get("high")
            if lo is None and hi is None:
                errors.append(f"{where} target needs low and/or high")
            if any(v is not None and not isinstance(v, (int, float)) for v in (lo, hi)):
                errors.append(f"{where} target bounds must be numbers")
            elif lo is not None and hi is not None and not lo < hi:
                errors.append(f"{where} target has low >= high")
            for key in ("label", "source"):
                if not target.get(key):
                    errors.append(f"{where} target.{key} is required")
            if target.get("status") not in {"verified", "unverified"}:
                errors.append(f"{where} target.status must be verified or unverified")

        # Derived analytes need a formula whose inputs exist.
        if a.get("derived"):
            formula = a.get("formula") or {}
            for key in ("name", "inputs", "source"):
                if not formula.get(key):
                    errors.append(f"{where} derived analyte needs formula.{key}")

    # Cross-analyte checks that need every id loaded first.
    by_id = {a.get("id"): a for a in analytes}
    errors += validate_systems(data.get("systems"), analytes)
    for a in analytes:
        if a.get("derived"):
            for inp in (a.get("formula") or {}).get("inputs", []):
                if inp not in by_id and inp not in {"age_years", "sex"}:
                    errors.append(f"[{a['id']}] formula input '{inp}' is not a known analyte")
        rcv = a.get("rcv") or {}
        if rcv.get("method") == "derived_from_creatinine":
            base = (by_id.get("creatinine") or {}).get("rcv", {}).get("percent")
            exp = (a.get("formula") or {}).get("exponent_above_kappa")
            if base and exp:
                expected = (1 - (1 + base / 100) ** exp) * 100
                if abs(expected - rcv["percent"]) > RCV_TOLERANCE:
                    errors.append(f"[{a['id']}] rcv.percent should be {expected:.1f} from creatinine RCV")

    return errors


def validate_systems(systems, analytes: list[dict]) -> list[str]:
    """Every analyte's system is listed; each system has analytes and a headline analyte of its own."""
    if not isinstance(systems, list) or not systems:
        return ["top-level 'systems' list is missing"]
    errors: list[str] = []
    ids: set[str] = set()
    orders: set = set()
    members: dict[str, list[str]] = {}
    for a in analytes:
        members.setdefault(a.get("system"), []).append(a.get("id"))
    for s in systems:
        sid = s.get("id", "<missing id>")
        where = f"system [{sid}]"
        for field in SYSTEM_FIELDS:
            if s.get(field) in (None, ""):
                errors.append(f"{where} missing field '{field}'")
        if sid in ids:
            errors.append(f"{where} duplicate id")
        ids.add(sid)
        if not isinstance(s.get("order"), int) or s.get("order") in orders:
            errors.append(f"{where} order must be a whole number used by one system only")
        orders.add(s.get("order"))
        if not members.get(sid):
            errors.append(f"{where} has no analytes")
        elif s.get("headline") not in members[sid]:
            errors.append(f"{where} headline '{s.get('headline')}' is not one of its analytes")
    for a in analytes:
        if a.get("system") and a.get("system") not in ids:
            errors.append(f"[{a.get('id')}] system '{a.get('system')}' is not in the systems list")
    return errors


# ---------------------------------------------------------------- helpers

def primary_names(analyte: dict) -> list[str]:
    """Names that mean the analyte on its own basis: canonical name, synonyms, report synonyms."""
    return [analyte["canonical_name"], *analyte["synonyms"], *analyte.get("report_synonyms", [])]


def basis_names(analyte: dict) -> list[str]:
    """Names that mean the value is on the alternate basis (urea printed as BUN)."""
    return list((analyte.get("alternate_basis") or {}).get("synonyms", []))


def find_analyte(data: dict, name: str) -> dict | None:
    """Look up an analyte by any synonym (case-insensitive, exact after normalising)."""
    key = norm_text(name)
    for a in data["analytes"]:
        if key in {norm_text(n) for n in primary_names(a) + basis_names(a)}:
            return a
    return None


def is_mass_unit(unit: str) -> bool:
    return "mol" not in norm_unit(unit)


def alternate_basis_factor(analyte: dict, unit: str) -> float:
    """Multiplier from the alternate basis to the analyte in a mass unit (BUN mg/dL x 2.1437 = urea
    mg/dL). Molar units need no factor: one mole of urea carries one mole of urea nitrogen pairs."""
    return analyte["alternate_basis"]["mass_factor"] if is_mass_unit(unit) else 1.0


def to_canonical(analyte: dict, value: float, unit: str) -> float:
    """Convert a reported value to the analyte's canonical unit."""
    key = norm_unit(unit)
    for conv in analyte["conversions"]:
        if norm_unit(conv["unit"]) == key:
            return value * conv["factor"] + conv.get("offset", 0)
    raise ValueError(f"unknown unit '{unit}' for {analyte['id']}")


def egfr_ckd_epi_2021(creatinine_mg_dl: float, age_years: float, sex: str, formula: dict) -> float:
    """CKD-EPI 2021 race-free eGFR (mL/min/1.73 m²) using the coefficients in the dictionary."""
    if sex not in ("male", "female"):
        raise ValueError("sex must be 'male' or 'female'")
    kappa, alpha = formula["kappa"][sex], formula["alpha"][sex]
    ratio = creatinine_mg_dl / kappa
    egfr = (
        formula["constant"]
        * min(ratio, 1) ** alpha
        * max(ratio, 1) ** formula["exponent_above_kappa"]
        * formula["age_base"] ** age_years
    )
    if sex == "female":
        egfr *= formula["female_factor"]
    return egfr


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    data = load(path)
    errors = validate(data)
    analytes = data.get("analytes", [])
    if errors:
        print(f"FAIL {path}: {len(errors)} error(s)")
        for e in errors:
            print(f"  - {e}")
        return 1

    status_counts: dict[str, int] = {}
    for a in analytes:
        s = a["rcv"]["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    print(f"OK {path}: {len(analytes)} analytes")
    print(f"  {'id':<18} {'LOINC':<9} {'unit':<15} {'units':>5} {'RCV %':>6}  status")
    for a in analytes:
        r = a["rcv"]
        pct = "-" if r["percent"] is None else f"{r['percent']:.1f}"
        print(f"  {a['id']:<18} {a['loinc']:<9} {a['canonical_unit']:<15} {len(a['conversions']):>5} {pct:>6}  {r['status']}")
    print("  RCV status: " + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
