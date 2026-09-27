"""Step 5 normalisation: extracted results -> observations in canonical units, with a status.

Status of each observation:
  extracted     tracked analyte, numeric value, known unit: canonical value set (awaits the doctor)
  needs_review  something must be fixed by the doctor first (reason says what); no canonical value
  not_tracked   the test is not in the dictionary; kept as printed, never dropped
(confirmed and rejected are set later by the doctor.)

A result whose name is not in the dictionary and that has neither a unit nor a range is not a
lab result ("Age / Sex : 44 Y"); it is returned as skipped with that reason instead.

eGFR is never taken from the report: it is recomputed with CKD-EPI 2021 from the same report's
creatinine and the patient's age and sex. The printed eGFR stays as raw text.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from data import validate_analytes as va

from .names import NameIndex, NameMatch, name_index
from .values import ParsedValue, find_conversion, parse_value

EXTRACTED, CONFIRMED, NEEDS_REVIEW, NOT_TRACKED, REJECTED = (
    "extracted", "confirmed", "needs_review", "not_tracked", "rejected")
NOT_A_RESULT = "test name not in the dictionary and no unit or range printed: not a lab result"
ADULT_AGE = (18, 120)        # CKD-EPI 2021 is an adult equation


@dataclass
class Patient:
    sex: str                 # "male" or "female"
    birth_year: int


@dataclass
class Observation:
    test_text: str
    value_text: str
    unit_text: str
    range_text: str
    flag_text: str
    row_text: str
    page: int
    line: int
    range_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    analyte_id: str | None = None
    match: str | None = None             # "exact", "loose", "doctor" or None
    basis: str = "primary"
    comparator: str | None = None
    value_number: float | None = None    # the printed number, in the printed unit
    canonical_value: float | None = None
    canonical_unit: str | None = None
    status: str = NOT_TRACKED
    status_reason: str = ""


def analyte(analyte_id: str) -> dict:
    return name_index().analytes[analyte_id]


def normalise_value(obs: Observation, index: NameIndex | None = None, analyte_id: str | None = None) -> Observation:
    """Set analyte, parsed value, canonical value and status for one observation (not eGFR's value)."""
    index = index or name_index()
    if analyte_id is not None:                       # chosen by the doctor; the basis still follows the name
        m = NameMatch(analyte_id, index.basis_for(obs.test_text, analyte_id), "doctor", (analyte_id,))
    else:
        m = index.match(obs.test_text)
    obs.analyte_id, obs.match, obs.basis = m.analyte_id, m.method, m.basis
    pv: ParsedValue = parse_value(obs.value_text)
    obs.comparator, obs.value_number = pv.comparator, pv.number
    obs.canonical_value, obs.canonical_unit = None, None

    if m.analyte_id is None:
        if m.ambiguous:
            obs.status, obs.status_reason = NEEDS_REVIEW, "test name matches more than one test: " + ", ".join(m.candidates)
        else:
            obs.status, obs.status_reason = NOT_TRACKED, "test is not in the ChronoTrace dictionary"
        return obs

    a = index.analytes[m.analyte_id]
    obs.canonical_unit = a["canonical_unit"]
    if not pv.numeric:
        obs.status, obs.status_reason = NEEDS_REVIEW, f"value '{obs.value_text}' is not a number"
        return obs
    if m.analyte_id == "egfr":
        obs.status, obs.status_reason = NEEDS_REVIEW, "eGFR not computed yet"
        return obs
    conv = find_conversion(a, obs.unit_text)
    if conv is None:
        what = f"unit '{obs.unit_text}' is not a known unit" if obs.unit_text.strip() else "no unit printed"
        obs.status, obs.status_reason = NEEDS_REVIEW, f"{what} for {a['canonical_name']}"
        return obs
    value = pv.number * conv["factor"] + conv.get("offset", 0)
    if m.basis == "alternate":
        value *= va.alternate_basis_factor(a, obs.unit_text)
    obs.canonical_value = round(value, 6)
    obs.status = EXTRACTED
    obs.status_reason = "" if pv.comparator is None else f"value is censored ({pv.comparator})"
    return obs


def recompute_egfr(observations: list[Observation], patient: Patient, date: dt.date | None) -> None:
    """Set every eGFR observation's canonical value from the report's creatinine (CKD-EPI 2021)."""
    egfrs = [o for o in observations if o.analyte_id == "egfr" and o.status not in (REJECTED,)]
    if not egfrs:
        return
    a = analyte("egfr")
    creat = [o for o in observations if o.analyte_id == "creatinine" and o.canonical_value is not None
             and o.status in (EXTRACTED, CONFIRMED)]
    for o in egfrs:
        # The stored eGFR is computed, never read: a printed "<60" or ">90" stays in value_text only,
        # and the computed value is exact, so it carries no comparator.
        o.canonical_unit, o.canonical_value, o.comparator = a["canonical_unit"], None, None
        age = date.year - patient.birth_year if date is not None else None
        if o.status == CONFIRMED:
            o.status = EXTRACTED
        if not creat:
            o.status, o.status_reason = NEEDS_REVIEW, "eGFR is recomputed from creatinine, but this report has no usable creatinine"
        elif len({c.canonical_value for c in creat}) > 1:
            o.status, o.status_reason = NEEDS_REVIEW, "report has more than one creatinine value; cannot tell which one eGFR uses"
        elif date is None:
            o.status, o.status_reason = NEEDS_REVIEW, "report date needed to compute age for eGFR"
        elif patient.sex not in ("male", "female"):
            o.status, o.status_reason = NEEDS_REVIEW, "patient sex needed for eGFR"
        elif creat[0].comparator is not None:
            o.status, o.status_reason = NEEDS_REVIEW, "creatinine is censored; eGFR cannot be computed"
        elif creat[0].canonical_value <= 0:
            o.status, o.status_reason = NEEDS_REVIEW, "creatinine must be above 0 to compute eGFR"
        elif not ADULT_AGE[0] <= age <= ADULT_AGE[1]:
            o.status, o.status_reason = NEEDS_REVIEW, (
                f"age {age} at the report date is outside {ADULT_AGE[0]}-{ADULT_AGE[1]}; CKD-EPI 2021 is for adults "
                "(check the report date and birth year)")
        else:
            c = creat[0]
            o.canonical_value = round(va.egfr_ckd_epi_2021(c.canonical_value, age, patient.sex, a["formula"]), 2)
            o.status = EXTRACTED
            o.status_reason = (f"recomputed with CKD-EPI 2021 from creatinine {c.canonical_value:g} mg/dL "
                               f"(page {c.page}, line {c.line}), age {age}, {patient.sex}; "
                               f"printed eGFR '{o.value_text}' kept as text")


def normalise(results, patient: Patient, date: dt.date | None) -> tuple[list[Observation], list[tuple]]:
    """Results from extraction -> (observations, skipped). skipped: (page, line, text, reason)."""
    index = name_index()
    observations: list[Observation] = []
    skipped: list[tuple] = []
    for r in results:
        o = normalise_value(Observation(
            test_text=r.test_text, value_text=r.value_text, unit_text=r.unit_text, range_text=r.range_text,
            flag_text=r.flag_text, row_text=r.row_text, page=r.page, line=r.line,
            range_lines=list(r.range_lines), notes=list(r.notes)), index)
        has_range = o.range_text.strip() or any(line.strip() for line in o.range_lines)
        if o.status == NOT_TRACKED and not o.unit_text.strip() and not has_range:
            skipped.append((r.page, r.line, r.row_text, NOT_A_RESULT))
            continue
        observations.append(o)
    recompute_egfr(observations, patient, date)
    return observations, skipped
