"""Analyte facts the trend engine needs, read from data/analytes.yaml (nothing hard-coded)."""

from __future__ import annotations

from functools import lru_cache

from data import validate_analytes as va

from .engine import AnalyteInfo


@lru_cache(maxsize=1)
def analyte_infos() -> tuple[AnalyteInfo, ...]:
    """Every analyte in dictionary order, with its RCV (None when not established) and RCV status."""
    out = []
    for a in va.load()["analytes"]:
        rcv = a.get("rcv") or {}
        out.append(AnalyteInfo(a["id"], a["canonical_name"], a["canonical_unit"], rcv.get("percent"),
                               rcv.get("status", "not_established").replace("_", " "),
                               " ".join(str(rcv.get("source") or "").split())))
    return tuple(out)


def infos_by_id() -> dict[str, AnalyteInfo]:
    return {a.id: a for a in analyte_infos()}
