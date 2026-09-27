"""Report date and lab name from the page-header text, by regex.

Date: the "Collected" date is preferred (it is when the sample was taken); "Reported" is the
fallback. The label used is returned so the doctor can see which date was taken. Dates are read
day-first (Indian reports); a month above 12 in the second field is read as month-first.
No date found -> None, and the doctor enters it when confirming the report.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# A 4-digit year directly followed by ":" is really a 2-digit year glued to a time ("03/07/2309:18").
_NUMERIC = r"(?P<a>\d{1,2})[/.\-](?P<b>\d{1,2})[/.\-](?P<y>\d{4}(?!:)|\d{2})(?!\d{1,2}[/.\-])"
_TEXTUAL = r"(?P<d>\d{1,2})[\s/.\-]*(?P<mon>[A-Za-z]{3,9})[\s/.,\-]*(?P<y2>\d{4}(?!:)|\d{2})"
_ISO = r"(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})"
DATE = re.compile(rf"(?:{_ISO}|{_NUMERIC}|{_TEXTUAL})")
EARLIEST_YEAR = 1950          # earlier dates, and dates after today, are not report dates

# Label, then up to a few joining words ("Date and Time", "On", "At", "/Received"), then an optional
# colon. The date must follow directly, so "Collected At <place>" is not a date.
_JOIN = r"(?:\s*(?:on|date|dt|and|time|at|received|recd|&|/))*"
LABELS = {
    "Collected": re.compile(rf"\b(?:sample\s+)?(?:collect(?:ed|ion)|coll\.?){_JOIN}\s*:?\s*", re.I),
    "Reported": re.compile(rf"\breport(?:ed|ing)?{_JOIN}\s*:?\s*", re.I),
}

LAB_SUFFIX = re.compile(
    r"^(?:diagnostics?|labs?|laborator(?:y|ies)|pathology|path|healthcare|clinic|hospital|polyclinic|"
    r"imaging|scans?)$", re.I)
LAB_TAIL = re.compile(r"^(?:centre|center|services|lab|labs|laboratory|pvt\.?|private|ltd\.?|limited|llp)$", re.I)
LAB_STOP = re.compile(
    r"^(?:sample|processed|at|collected|collection|report|reported|patient|name|ref|referred|by|dr\.?|"
    r"tel|phone|no|id|sid|age|sex|investigation|final|test|lab|director|the|of|and|&|"
    r"mr|mrs|ms|miss|master|baby|male|female|m|f|y|yrs|years)\.?$", re.I)
FIELD_WORD = re.compile(r"^(?:no|id|code|ref|number|num|#)\.?:?$", re.I)     # "Lab No." is a field label


@dataclass
class ReportMeta:
    collected_at: dt.date | None
    reported_at: dt.date | None
    date: dt.date | None
    date_label: str | None       # "Collected", "Reported" or None
    lab: str | None


def parse_date(text: str) -> dt.date | None:
    m = DATE.search(text)
    if not m:
        return None
    try:
        if m.group("iy"):
            year, month, day = int(m.group("iy")), int(m.group("im")), int(m.group("id"))
        elif m.group("a"):
            a, b, y = int(m.group("a")), int(m.group("b")), int(m.group("y"))
            day, month = (a, b) if b <= 12 else (b, a)
        else:
            mon = MONTHS.get(m.group("mon")[:3].lower())
            if mon is None:
                return None
            day, month, y = int(m.group("d")), mon, int(m.group("y2"))
        if not m.group("iy"):
            year = y + 2000 if y < 100 else y
        d = dt.date(year, month, day)
    except ValueError:
        return None
    return d if EARLIEST_YEAR <= d.year and d <= dt.date.today() else None


def _labelled_date(lines: list[str], label: str) -> dt.date | None:
    pattern = LABELS[label]
    for text in lines:
        for m in pattern.finditer(text):
            d = parse_date(text[m.end():m.end() + 30])
            if d and DATE.match(text[m.end():].lstrip(": ")):
                return d
    return None


def find_lab(lines: list[str]) -> str | None:
    """First "<Name> Diagnostics/Labs/Healthcare ..." phrase in the page header."""
    for text in lines:
        if re.search(r"\bdr\b\.?", text, re.I):         # referring-doctor line ("Dr. X", "DR.KUMAR")
            continue
        toks = [t.strip(":(),;") for t in text.split()]
        toks = [t for t in toks if t]
        for i, t in enumerate(toks):
            if not LAB_SUFFIX.match(t) or i == 0 or (i + 1 < len(toks) and FIELD_WORD.match(toks[i + 1])):
                continue
            j = i
            while j > 0 and i - j < 4 and toks[j - 1][:1].isupper() and not LAB_STOP.match(toks[j - 1]) \
                    and not any(ch.isdigit() for ch in toks[j - 1]):
                j -= 1
            if j == i:
                continue
            k = i + 1
            while k < len(toks) and k - i <= 3 and LAB_TAIL.match(toks[k]):
                k += 1
            return " ".join(toks[j:k])
    return None


def read_metadata(header_lines: list[str], all_lines: list[str]) -> ReportMeta:
    """header_lines: page-header rows (preferred for the lab name); all_lines: every row, in order."""
    collected = _labelled_date(all_lines, "Collected")
    reported = _labelled_date(all_lines, "Reported")
    date, label = (collected, "Collected") if collected else ((reported, "Reported") if reported else (None, None))
    return ReportMeta(collected, reported, date, label, find_lab(header_lines) or find_lab(all_lines[:15]))
