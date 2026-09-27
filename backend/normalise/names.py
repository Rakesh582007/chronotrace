"""Map a printed test name to an analyte in data/analytes.yaml.

1. Exact: the name equals a synonym, canonical name or report synonym (case and spacing ignored).
2. Loose: lowercase, punctuation to spaces, qualifier words dropped (serum, plasma, s., sr.,
   direct, calculated, blood, whole, and "fasting" except in glucose names), then compared
   a) as a set of words, and b) with the spaces removed ("hb a1c" == "hba1c").
   The dictionary's own names are loosened the same way. One analyte -> match. Two or more ->
   ambiguous (needs review, never a guess). None -> not tracked.

"fasting" is dropped for other tests ("TRIGLYCERIDES (FASTING)") but kept for glucose, where it is
what tells fasting from random or post-prandial glucose, so a bare "GLUCOSE" is not guessed as
fasting glucose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from data import validate_analytes as va

QUALIFIERS = {"serum", "plasma", "direct", "calculated", "blood", "whole"}
GLUCOSE_WORDS = {"glucose", "sugar"}
_PUNCT = re.compile(r"[^0-9a-z ]+")
# "S." / "Sr." for serum only as a prefix ("S. Creatinine", "S.Creatinine", "Sr Urea"), so the S of
# dotted initials ("F.B.S.", "T.S.H.") and of "Hb S" is kept.
_SERUM_PREFIX = re.compile(r"^\s*sr?(?:\.\s*|\s+)(?=[a-z])")


def loose_words(name: str) -> list[str]:
    words = _PUNCT.sub(" ", _SERUM_PREFIX.sub("", name.lower())).split()
    glucose = bool(GLUCOSE_WORDS & set(words))
    return [w for w in words if w not in QUALIFIERS and (w != "fasting" or glucose)]


def loose_keys(name: str) -> tuple[frozenset[str], str]:
    words = loose_words(name)
    return frozenset(words), "".join(words)


@dataclass(frozen=True)
class NameMatch:
    analyte_id: str | None
    basis: str = "primary"               # "alternate" for BUN-style names
    method: str | None = None            # "exact", "loose" or None
    candidates: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ambiguous(self) -> bool:
        return self.analyte_id is None and len(self.candidates) > 1


class NameIndex:
    def __init__(self, data: dict):
        self.analytes = {a["id"]: a for a in data["analytes"]}
        self.exact: dict[str, tuple[str, str]] = {}
        self.by_set: dict[frozenset[str], set[tuple[str, str]]] = {}
        self.by_joined: dict[str, set[tuple[str, str]]] = {}
        for a in data["analytes"]:
            for basis, names in (("primary", va.primary_names(a)), ("alternate", va.basis_names(a))):
                for n in names:
                    self.exact[va.norm_text(n)] = (a["id"], basis)
                    words, joined = loose_keys(n)
                    if words:
                        self.by_set.setdefault(words, set()).add((a["id"], basis))
                        self.by_joined.setdefault(joined, set()).add((a["id"], basis))

    def match(self, name: str) -> NameMatch:
        if not name or not name.strip():
            return NameMatch(None)
        hit = self.exact.get(va.norm_text(name))
        if hit:
            return NameMatch(hit[0], hit[1], "exact", (hit[0],))
        words, joined = loose_keys(name)
        if not words:
            return NameMatch(None)
        found = self.by_set.get(words, set()) | self.by_joined.get(joined, set())
        ids = sorted({aid for aid, _ in found})
        if len(ids) == 1:
            bases = {b for _, b in found}
            return NameMatch(ids[0], "alternate" if bases == {"alternate"} else "primary", "loose", tuple(ids))
        return NameMatch(None, "primary", None, tuple(ids))

    def basis_for(self, name: str, analyte_id: str) -> str:
        """Basis of a value printed under `name` when it is known to be `analyte_id` (the doctor chose
        it): "alternate" if the name carries a word only the alternate names use ("BUN", "nitrogen")."""
        m = self.match(name)
        if m.analyte_id == analyte_id:
            return m.basis
        a = self.analytes[analyte_id]
        if not a.get("alternate_basis"):
            return "primary"
        primary = {w for n in va.primary_names(a) for w in loose_words(n)}
        alternate_only = {w for n in va.basis_names(a) for w in loose_words(n)} - primary
        return "alternate" if alternate_only & set(loose_words(name)) else "primary"


@lru_cache(maxsize=1)
def name_index() -> NameIndex:
    return NameIndex(va.load())
