"""Rule-based tagger: the baseline the trained model has to beat.

Produces the same word-level BIO tags as the model, from rules only:
  TEST   longest match of a known test name at the start of the row (dictionary synonyms and
         canonical names from data/analytes.yaml, plus extra_tests.py names; case-insensitive)
  RANGE  "a-b", "(a-b)", "a - b", "< a", "> a", "Up to a", "Upto a", with optional "M:"/"F:" parts
  VALUE  the first number (Indian or Western digit grouping) not taken by a range
  UNIT   longest match of a known unit string (all units in the dictionary and extras)
  FLAG   H, L, High, Low, *H, *L after the value
Known method names (e.g. "CKD-EPI 2021") and dot leaders are skipped as "O". A row without a
known test name or without a value, or with more than MAX_SKIPPED other words before the value
(a note sentence that starts with a test name), is tagged all "O".

The name, unit and method lists are the ones the generator draws from, so on synthetic data this
baseline knows every name and unit it will see. It is a strong baseline for synthetic data;
on real reports it will miss names and units the dictionary lacks.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator import dictionary as d  # noqa: E402
from generator import extra_tests as xt  # noqa: E402
from generator import values as v  # noqa: E402

_NUM = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?"
NUM = re.compile(rf"^{_NUM}$")
RANGE_TOKEN = re.compile(rf"^\(?{_NUM}-{_NUM}\)?$")
OPEN_NUM = re.compile(rf"^\({_NUM}$")
CLOSE_NUM = re.compile(rf"^{_NUM}\)$")
COMPARATORS = {"<", ">", "<=", ">=", "≤", "≥"}
DASHES = {"-", "–", "to"}
SEX_LABELS = {"m:", "f:", "male:", "female:", "m", "f"}
LEADER = re.compile(r"^[.:_-]{3,}$")
MAX_SKIPPED = 2
FLAGS = {"h", "l", "high", "low", "*h", "*l", "h*", "l*", "↑", "↓"}


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.lower().split())


@lru_cache(maxsize=1)
def test_names() -> list[tuple[str, ...]]:
    names = {n for a in d.analytes().values() for n in d.name_pool(a) + d.basis_synonyms(a)}
    names |= {n for t in xt.EXTRA_TESTS.values() for n in t.names}
    return sorted({_words(n) for n in names}, key=len, reverse=True)


@lru_cache(maxsize=1)
def unit_names() -> list[tuple[str, ...]]:
    units = {c["unit"] for a in d.analytes().values() for c in a["conversions"]}
    units |= {t.unit for t in xt.EXTRA_TESTS.values() if t.unit}
    return sorted({_words(u) for u in units}, key=len, reverse=True)


@lru_cache(maxsize=1)
def method_names() -> list[tuple[str, ...]]:
    methods = {m for ms in v.METHODS.values() for m in ms} | {m for t in xt.EXTRA_TESTS.values() for m in t.methods}
    return sorted({_words(m) for m in methods}, key=len, reverse=True)


def _match(low: list[str], i: int, candidates: list[tuple[str, ...]]) -> int:
    """Length of the longest candidate starting at low[i], or 0."""
    for c in candidates:   # longest first
        if tuple(low[i:i + len(c)]) == c:
            return len(c)
    return 0


def _bound(tok: list[str], low: list[str], i: int) -> int:
    """End index of one range part starting at i, or i if none."""
    n = len(tok)
    if i >= n:
        return i
    if RANGE_TOKEN.match(tok[i]):
        return i + 1
    if tok[i] in COMPARATORS and i + 1 < n and NUM.match(tok[i + 1]):
        return i + 2
    if low[i] == "upto" and i + 1 < n and NUM.match(tok[i + 1]):
        return i + 2
    if low[i] == "up" and i + 2 < n and low[i + 1] == "to" and NUM.match(tok[i + 2]):
        return i + 3
    if i + 2 < n and low[i + 1] in DASHES:
        if NUM.match(tok[i]) and NUM.match(tok[i + 2]):
            return i + 3
        if OPEN_NUM.match(tok[i]) and CLOSE_NUM.match(tok[i + 2]):
            return i + 3
    return i


def _range(tok: list[str], low: list[str], i: int) -> int:
    """End index of a reference range starting at i (one part, or sex-labelled parts), or i."""
    if low[i] in SEX_LABELS:
        j = i
        while j < len(tok) and low[j] in SEX_LABELS:
            end = _bound(tok, low, j + 1)
            if end == j + 1:
                break
            j = end
        return j
    return _bound(tok, low, i)


def _span(tags: list[str], start: int, end: int, kind: str) -> None:
    tags[start] = f"B-{kind}"
    for k in range(start + 1, end):
        tags[k] = f"I-{kind}"


def tag_row(tokens: list[str]) -> list[str]:
    tags = ["O"] * len(tokens)
    low = [t.lower() for t in tokens]
    n_test = _match(low, 0, test_names())
    if not n_test:
        return tags
    _span(tags, 0, n_test, "TEST")

    found = set()
    skipped = 0
    i = n_test
    while i < len(tokens):
        if "VALUE" not in found:
            if LEADER.match(tokens[i]):
                i += 1
                continue
            n = _match(low, i, method_names())
            if n:
                i += n
                continue
        if "RANGE" not in found:
            end = _range(tokens, low, i)
            if end > i:
                _span(tags, i, end, "RANGE")
                found.add("RANGE")
                i = end
                continue
        if "VALUE" not in found and NUM.match(tokens[i]):
            _span(tags, i, i + 1, "VALUE")
            found.add("VALUE")
            i += 1
            continue
        if "UNIT" not in found:
            n = _match(low, i, unit_names())
            if n:
                _span(tags, i, i + n, "UNIT")
                found.add("UNIT")
                i += n
                continue
        if "VALUE" in found and "FLAG" not in found and low[i] in FLAGS:
            _span(tags, i, i + 1, "FLAG")
            found.add("FLAG")
        elif "VALUE" not in found:
            skipped += 1
            if skipped > MAX_SKIPPED:
                return ["O"] * len(tokens)
        i += 1

    return tags if "VALUE" in found else ["O"] * len(tokens)
