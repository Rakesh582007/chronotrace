"""SQLite database (SQLModel): patients, reports, observations and medication events."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from .models import MedicationEvent, Observation, Patient, Report  # noqa: F401  (register tables)

DEFAULT_DB = Path(__file__).resolve().parents[1] / "chronotrace.db"    # git-ignored (*.db)


def make_engine(url: str | None = None):
    url = url or os.environ.get("CHRONOTRACE_DB") or f"sqlite:///{DEFAULT_DB}"
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    SQLModel.metadata.create_all(engine)
    return engine


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
