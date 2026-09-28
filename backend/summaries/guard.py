"""Checks on an LLM summary before it is saved. A summary that fails any check is never saved.

- Structure: the JSON matches LLMSummary.
- Numbers: every number in the text is in the facts, at the facts' precision or rounded to fewer decimals
  (signs are ignored: "fell by 7.1" quotes a slope of -7.08). Report labels such as "R7" are not numbers.
- Report ids: every cited label is one of the facts' reports; the key finding cites at least one.
- Medication rows: each is one of the facts' medication events (same date and drug).
- Wording: nothing matches the BANNED guardrail or causal wording (backend/trends/wording.py), apart from
  names: the patient's recorded conditions (entered by the doctor) and lab names ("... DIAGNOSTICS").
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ValidationError

from ..trends.wording import BANNED, CAUSAL, offending
from .facts import Facts, canonical

# A number not glued to a letter, digit or point on its left: "R7", "T4" and "HbA1c" are names, not numbers.
NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")


class Cited(BaseModel):
    text: str
    report_ids: list[str]             # report labels from the facts ("R7")


class Section(BaseModel):
    title: str
    sentences: list[Cited]


class MedicationRow(BaseModel):
    date: str                         # YYYY-MM-DD, as in the facts
    drug: str
    dose: str
    observed: str


class LLMSummary(BaseModel):
    """The structured output asked of the model."""
    key_finding: Cited
    sections: list[Section]
    medication_rows: list[MedicationRow]
    data_notes: list[str]


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def allowed_numbers(facts: Facts) -> set[str]:
    """Every number in the facts, and each of its roundings to fewer decimals."""
    out: set[str] = set()
    for s in NUMBER.findall(canonical(facts.data)):
        d = Decimal(s)
        for k in range(_decimals(s) + 1):
            q = Decimal(1).scaleb(-k)
            for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
                out.add(format(d.quantize(q, rounding=mode), f".{k}f"))
    return out


def _normal(s: str) -> str:
    return format(Decimal(s), f".{_decimals(s)}f")


def texts(summary: LLMSummary) -> list[tuple[str, str]]:
    """(where, text) for every text the summary shows."""
    out = [("key_finding", summary.key_finding.text)]
    for i, sec in enumerate(summary.sections, 1):
        out.append((f"section {i} title", sec.title))
        out += [(f"section {i} sentence {j}", s.text) for j, s in enumerate(sec.sentences, 1)]
    for i, row in enumerate(summary.medication_rows, 1):
        out += [(f"medication row {i} {k}", getattr(row, k)) for k in ("date", "drug", "dose", "observed")]
    out += [(f"data note {i}", n) for i, n in enumerate(summary.data_notes, 1)]
    return out


def parse(text: str) -> tuple[LLMSummary | None, list[str]]:
    try:
        return LLMSummary.model_validate(json.loads(text)), []
    except json.JSONDecodeError as e:
        return None, [f"the answer is not valid JSON ({e.msg})"]
    except ValidationError as e:
        return None, [f"the JSON does not match the schema: {err['loc']} {err['msg']}" for err in e.errors()[:5]]


def check(summary: LLMSummary, facts: Facts) -> list[str]:
    errors: list[str] = []
    allowed = allowed_numbers(facts)
    for where, text in texts(summary):
        for n in NUMBER.findall(text):
            if _normal(n) not in allowed:
                errors.append(f'{where}: the number {n} is not in the facts ("{text}")')
        words = offending(text, facts.allowed_phrases, (BANNED, CAUSAL))
        if words:
            errors.append(f'{where}: uses the word(s) {", ".join(repr(w) for w in words)} ("{text}")')

    cited = [("key_finding", summary.key_finding.report_ids)] + [
        (f"section {i} sentence {j}", s.report_ids)
        for i, sec in enumerate(summary.sections, 1) for j, s in enumerate(sec.sentences, 1)]
    for where, ids in cited:
        unknown = [r for r in ids if r not in facts.label_to_id]
        if unknown:
            errors.append(f"{where}: report_ids {unknown} are not reports in the facts")
    if not summary.key_finding.report_ids:
        errors.append("key_finding: cite at least one report in report_ids")
    if not summary.key_finding.text.strip():
        errors.append("key_finding: the text is empty")

    events = {(e["date"], e["drug"].casefold()) for e in facts.data["medication_events"]}
    for i, row in enumerate(summary.medication_rows, 1):
        if not any(d == row.date and drug in row.drug.casefold() for d, drug in events):
            errors.append(f"medication row {i}: {row.date} {row.drug} is not a medication event in the facts")
    return errors


def check_text(text: str, facts: Facts) -> tuple[LLMSummary | None, list[str]]:
    summary, errors = parse(text)
    if summary is None:
        return None, errors
    errors = check(summary, facts)
    return (summary if not errors else None), errors
