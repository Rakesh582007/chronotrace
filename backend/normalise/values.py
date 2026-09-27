"""Parse printed values and find unit conversions.

Values: "87", "1,50,000" (Indian grouping), "6,370", "<0.5", "> 1000", "less than 5", "upto 40".
A comparator is kept separately; the number is still stored. Text such as "Negative", "Nil" or
"Reactive" has no number and is never converted (the observation needs review).

Units: case-insensitive, spaces ignored, "µ"/"μ" = "u" (the dictionary's rule), and dots ignored so
"Cells/cu.mm" matches "cells/cumm". A unit not listed for the analyte is never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from data import validate_analytes as va

_COMPARATORS = [
    (re.compile(r"^(?:<=|≤|=<)\s*"), "<="), (re.compile(r"^(?:>=|≥|=>)\s*"), ">="),
    (re.compile(r"^<\s*"), "<"), (re.compile(r"^>\s*"), ">"),
    (re.compile(r"^(?:less\s+than|below|upto|up\s+to)\s+", re.I), "<"),
    (re.compile(r"^(?:more\s+than|greater\s+than|above)\s+", re.I), ">"),
]
# Digit grouping only in its real forms: western "6,370" / "1,234,567" or Indian "1,50,000" /
# "12,34,567" (never a leading 0 group). "0,60" or "4,25" is a decimal comma or an OCR slip, not
# grouping, so it is not a number (the observation then needs review).
_NUMBER = re.compile(r"^[+]?(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d?(?:,\d{2})+,\d{3}|\d+)(?:\.\d+)?$|^[+]?\.\d+$")


@dataclass(frozen=True)
class ParsedValue:
    number: float | None
    comparator: str | None

    @property
    def numeric(self) -> bool:
        return self.number is not None


def parse_value(text: str | None) -> ParsedValue:
    t = (text or "").strip().rstrip("*").strip()
    comparator = None
    for pattern, symbol in _COMPARATORS:
        m = pattern.match(t)
        if m:
            comparator, t = symbol, t[m.end():].strip()
            break
    if not _NUMBER.match(t):
        return ParsedValue(None, comparator)
    try:
        return ParsedValue(float(t.replace(",", "").lstrip("+")), comparator)
    except ValueError:
        return ParsedValue(None, comparator)


def unit_key(unit: str) -> str:
    return va.norm_unit(unit).replace(".", "")


def find_conversion(analyte: dict, unit: str | None) -> dict | None:
    if not unit or not unit.strip():
        return None
    key = unit_key(unit)
    for conv in analyte["conversions"]:
        if unit_key(conv["unit"]) == key:
            return conv
    return None
