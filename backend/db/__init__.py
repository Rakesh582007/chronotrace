"""SQLite database (SQLModel): patients, reports, observations and medication events."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from .models import Doctor, MedicationEvent, Observation, Patient, Report  # noqa: F401  (register tables)

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


def set_engine(engine) -> None:
    """Use this engine for every request (tests and the doc generator use a throwaway database)."""
    global _engine
    _engine = engine


class SchemaError(RuntimeError):
    pass


def check_schema(engine) -> None:
    """Refuse to run on a database created by an older ChronoTrace (SQLite does not add new columns).

    Rebuild the demo database with:  python -m backend.demo.seed --reset
    """
    insp = inspect(engine)
    missing = []
    for table in SQLModel.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        missing += [f"{table.name}.{c.name}" for c in table.columns if c.name not in have]
    if missing:
        raise SchemaError("the database was created by an older ChronoTrace (missing columns: "
                          + ", ".join(missing) + "). Rebuild the demo database: python -m backend.demo.seed --reset")


def reset_schema(engine) -> None:
    """Drop and recreate every table (demo data only)."""
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
