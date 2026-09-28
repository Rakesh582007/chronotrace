"""Database tables.

Observation keeps every raw text as printed (test, value, unit, range, flag, whole row) plus its
page and line, so each value in the timeline links back to where it came from on the report.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class Doctor(SQLModel, table=True):
    """A doctor who signs in (step 7: one demo doctor seeded from .env)."""
    id: int | None = Field(default=None, primary_key=True)
    name: str
    username: str = Field(unique=True, index=True)
    password_hash: str                         # pbkdf2_sha256$iterations$salt$hash (backend/auth.py)


class Patient(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    doctor_id: int = Field(foreign_key="doctor.id", index=True)
    name: str
    sex: str                                   # "male" | "female"
    birth_year: int
    conditions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: dt.datetime = Field(default_factory=_now)


class Report(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("file_sha256"),)

    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    file_sha256: str = Field(index=True)
    filename: str
    lab: str | None = None
    collected_at: dt.date | None = None        # date used for the timeline (see date_label)
    date_label: str | None = None              # "Collected", "Reported", "Entered by doctor" or None
    reported_at: dt.date | None = None
    layout: str = "header"                     # "header" | "no header"
    pages: int = 0
    status: str = "extracted"                  # "extracted" | "confirmed"
    skipped: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    uploaded_at: dt.datetime = Field(default_factory=_now)
    confirmed_at: dt.datetime | None = None


class Observation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id", index=True)
    analyte_id: str | None = Field(default=None, index=True)
    match: str | None = None                   # "exact" | "loose" | "doctor" | None
    basis: str = "primary"
    test_text: str
    value_text: str
    unit_text: str = ""
    range_text: str = ""
    flag_text: str = ""
    row_text: str = ""
    range_lines: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    notes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    comparator: str | None = None
    value_number: float | None = None
    canonical_value: float | None = None
    canonical_unit: str | None = None
    page: int
    line: int
    status: str                                # extracted | confirmed | needs_review | not_tracked | rejected
    status_reason: str = ""
    edited: bool = False                       # changed by the doctor at confirmation


class MedicationEvent(SQLModel, table=True):
    """Drug start / stop / dose change (used from step 6)."""
    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    drug: str
    change: str                                # "start" | "stop" | "dose_change"
    dose_text: str = ""
    date: dt.date
