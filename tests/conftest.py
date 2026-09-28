"""Shared test helpers: fixture paths, a rule-based stand-in tagger and signed-in API clients."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# Test login settings, set before the app is imported so the suite never depends on a local .env.
TEST_ENV = {"DEMO_DOCTOR_NAME": "Test Doctor", "DEMO_DOCTOR_USER": "test-doctor",
            "DEMO_DOCTOR_PASSWORD": "test-password-123", "AUTH_SECRET": "t" * 48}
os.environ.update(TEST_ENV)
# Tests never reach the real LLM: an empty environment variable wins over .env (backend/config.py).
os.environ.update({"LLM_PROVIDER": "", "LLM_API_KEY": "", "LLM_MODEL": ""})

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REAL_REPORTS = Path(__file__).resolve().parents[1] / "data" / "real_reports"

_VALUE = re.compile(r"^\d[\d,]*(\.\d+)?$")
_UNITS = {"mg/dl", "mg/dl:", "%", "mmol/l", "mmol/xx", "uiu/ml", "mg/g", "mg/l", "iu/ml", "pg/ml", "gm/dl",
          "ml/min/1.73m2", "fl", "pg", "g/dl", "miu/l", "ng/dl"}
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


def use_fresh_database(uploads=None):
    """A new in-memory database (and uploads folder) for the app, with the rule tagger instead of the model."""
    import tempfile

    from backend import db
    from backend.main import app, tagger_dep

    os.environ["CHRONOTRACE_UPLOADS"] = str(uploads or tempfile.mkdtemp(prefix="chronotrace-uploads-"))
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    app.dependency_overrides.pop(db.get_session, None)
    app.dependency_overrides[tagger_dep] = RuleTagger
    return engine


DOCTOR_A = ("dr.a", "pw-a-12345")                  # username, password of the default test doctor


def signed_in_client(username: str = DOCTOR_A[0], name: str = "Dr A", password: str = DOCTOR_A[1]):
    """A TestClient signed in as a doctor (created in the current database if needed)."""
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select

    from backend import db
    from backend.auth import hash_password
    from backend.db.models import Doctor
    from backend.main import app

    with Session(db.get_engine()) as s:
        if s.exec(select(Doctor).where(Doctor.username == username)).first() is None:
            s.add(Doctor(name=name, username=username, password_hash=hash_password(password)))
            s.commit()
    c = TestClient(app)
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


@pytest.fixture
def client(tmp_path):
    """API client signed in as a doctor, on a fresh in-memory database and uploads folder, with the rule tagger."""
    from backend.main import app

    use_fresh_database(tmp_path / "uploads")
    c = signed_in_client()
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def other_doctor(client):
    """A second doctor's client on the same database as `client`."""
    return signed_in_client("dr.b", "Dr B", "pw-b-12345")
