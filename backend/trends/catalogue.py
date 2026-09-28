"""The drug catalogue (data/drugs.yaml), loaded once."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from data import validate_drugs as vd

UNKNOWN = vd.UNKNOWN


@dataclass(frozen=True)
class Effect:
    analyte_id: str
    direction: str                 # "rise" | "fall"
    note: str
    max_expected_percent: float | None
    size: str | None = None        # "small": a change within noise in the expected direction still counts


@dataclass(frozen=True)
class DrugClass:
    id: str
    name: str
    short_name: str                # used in notes: "ACEi/ARB"
    window_start: int              # days after the start date
    window_end: int
    effects: tuple[Effect, ...]
    source: str
    status: str

    def effect_on(self, analyte_id: str) -> Effect | None:
        return next((e for e in self.effects if e.analyte_id == analyte_id), None)


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return vd.load()


@lru_cache(maxsize=1)
def classes() -> dict[str, DrugClass]:
    out = {}
    for c in catalogue()["classes"]:
        effects = tuple(Effect(e["analyte"], e["direction"], e["note"], e.get("max_expected_percent"), e.get("size"))
                        for e in c["effects"])
        out[c["id"]] = DrugClass(c["id"], c["name"], c.get("short_name") or c["name"], c["window_days"][0],
                                 c["window_days"][1], effects,
                                 " ".join(c["source"].split()), c["status"])
    return out


def resolve(drug: str) -> tuple[str, str | None]:
    """(class id or "unknown", generic name or None)."""
    return vd.resolve(catalogue(), drug)


def drug_class(class_id: str) -> DrugClass | None:
    return classes().get(class_id)
