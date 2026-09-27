"""Shared test helpers: fixture paths, a rule-based stand-in tagger and an API client."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_REPORTS = Path(__file__).resolve().parents[1] / "data" / "real_reports"

_VALUE = re.compile(r"^\d[\d,]*(\.\d+)?$")
_UNITS = {"mg/dl", "mg/dl:", "%", "mmol/l", "mmol/xx", "uiu/ml", "mg/g", "mg/l", "iu/ml", "pg/ml", "gm/dl",
          "ml/min/1.73m2", "fl", "pg", "g/dl"}
_FLAGS = {"h", "l", "high", "low"}


class RuleTagger:
    """Test double for the NER model: deterministic and deliberately naive.

    Words before the first plain number are TEST, that number is VALUE, a known unit after it is
    UNIT, H/L are FLAG, everything after is RANGE. It happily tags "Method :HEXOKINASE 100 - 125" as a
    test with a value, so tests using it show that the column rules, not the tagger, stop such lines
    from becoming results. Like the trained model, it does not see a value in ">1000" or "Negative"
    (neither appeared as a value in the training data), so those rows end up in `skipped`.
    """
    source = "tests.conftest.RuleTagger"

    def tag(self, rows: list[list[str]]) -> list[list[str]]:
        return [self._row(r) for r in rows]

    def _row(self, words: list[str]) -> list[str]:
        tags = ["O"] * len(words)
        v = next((i for i, w in enumerate(words) if _VALUE.match(w)), None)
        if v is None or v == 0:
            return tags
        for i in range(v):
            tags[i] = "B-TEST" if i == 0 else "I-TEST"
        tags[v] = "B-VALUE"
        in_range = False
        for i in range(v + 1, len(words)):
            low = words[i].lower()
            if low in _FLAGS and not in_range:
                tags[i] = "B-FLAG"
            elif low in _UNITS and not in_range and "B-UNIT" not in tags:
                tags[i] = "B-UNIT"
            else:
                tags[i] = "I-RANGE" if in_range else "B-RANGE"
                in_range = True
        return tags


def ner_tagger_or_skip():
    """The real NER model, or skip the test when torch/transformers or the model are unavailable."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from backend.extraction.tagger import get_tagger
    try:
        return get_tagger()
    except OSError as e:   # not downloaded and no network
        pytest.skip(f"NER model not available: {e}")


@pytest.fixture
def rule_tagger() -> RuleTagger:
    return RuleTagger()


@pytest.fixture
def client(monkeypatch):
    """API client on a fresh in-memory database, with the rule tagger instead of the model."""
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from backend import db
    from backend.main import app, tagger_dep

    engine = db.make_engine("sqlite://")

    def session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[db.get_session] = session
    app.dependency_overrides[tagger_dep] = RuleTagger
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
