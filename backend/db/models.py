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
    patient_code: str = Field(unique=True, index=True)     # CT-0001, CT-0002, ... (shown in the UI)
    photo_path: str | None = None                          # file under the uploads folder
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
    page_width: float | None = None            # first page in PDF points: the frame of Observation.bbox
    page_height: float | None = None           # (None for reports read before step 7)
    status: str = "extracted"                  # "extracted" | "confirmed"
    skipped: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    uploaded_at: dt.datetime = Field(default_factory=_now)
    confirmed_at: dt.datetime | None = None


class Document(SQLModel, table=True):
    """A file kept for a patient. Lab reports are parsed (their Report row is report_id); prescriptions and
    doctor's notes are stored only, never parsed. The file itself is under the uploads folder."""
    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    kind: str                                  # "lab_report" | "prescription" | "doctor_note"
    filename: str
    sha256: str = Field(index=True)
    size: int                                  # bytes
    stored_path: str = ""                      # relative to the uploads folder (backend/storage.py)
    uploaded_at: dt.datetime = Field(default_factory=_now)
    report_id: int | None = Field(default=None, foreign_key="report.id", index=True)
    document_date: dt.date | None = None       # date written on the document, when given


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
    bbox: list[float] | None = Field(default=None, sa_column=Column(JSON, nullable=True))  # [x0, top, x1, bottom]
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
