"""Request and response bodies of the API (documented in docs/api.md)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sex: Literal["male", "female"]
    birth_year: int = Field(ge=1900)
    conditions: list[str] = []

    @field_validator("birth_year")
    @classmethod
    def not_in_future(cls, v: int) -> int:
        if v > dt.date.today().year:
            raise ValueError("birth_year is in the future")
        return v


class PatientOut(BaseModel):
    id: int
    name: str
    sex: str
    birth_year: int
    conditions: list[str]


class ReportOut(BaseModel):
    id: int
    patient_id: int
    filename: str
    file_sha256: str
    lab: str | None
    collected_at: dt.date | None
    date_label: str | None
    reported_at: dt.date | None
    layout: str
    pages: int
    status: str
    uploaded_at: dt.datetime
    confirmed_at: dt.datetime | None


class ObservationOut(BaseModel):
    id: int
    report_id: int
    analyte_id: str | None
    analyte_name: str | None
    match: str | None
    test_text: str
    value_text: str
    unit_text: str
    range_text: str
    flag_text: str
    row_text: str
    range_lines: list[str]
    notes: list[str]
    comparator: str | None
    value_number: float | None
    canonical_value: float | None
    canonical_unit: str | None
    page: int
    line: int
    status: str
    status_reason: str
    edited: bool


class SkippedOut(BaseModel):
    page: int
    line: int
    text: str
    reason: str


class Counts(BaseModel):
    extracted: int
    needs_review: int
    not_tracked: int
    confirmed: int
    rejected: int
    skipped: int


class ReportDetail(BaseModel):
    report: ReportOut
    counts: Counts
    observations: list[ObservationOut]
    skipped: list[SkippedOut]


class ObservationEdit(BaseModel):
    id: int
    value_text: str | None = None
    unit_text: str | None = None
    analyte_id: str | None = None     # send null to mark the test "not tracked"
    reject: bool = False


class ObservationAdd(BaseModel):
    """A result the doctor adds, usually from a line in `skipped`."""
    page: int = Field(ge=1)
    line: int = Field(ge=1)
    test_text: str = Field(min_length=1)
    value_text: str = Field(min_length=1)
    unit_text: str = ""
    range_text: str = ""
    analyte_id: str | None = None     # leave out to match by test_text


class ConfirmIn(BaseModel):
    collected_at: dt.date | None = None
    lab: str | None = None
    observations: list[ObservationEdit] = []
    add: list[ObservationAdd] = []


class TimelinePoint(BaseModel):
    observation_id: int
    report_id: int
    date: dt.date
    value: float
    comparator: str | None
    value_text: str
    unit_text: str
    lab: str | None
    page: int
    line: int


class TimelineSeries(BaseModel):
    analyte_id: str
    name: str
    canonical_unit: str
    loinc: str
    points: list[TimelinePoint]


class Timeline(BaseModel):
    patient: PatientOut
    analytes: list[TimelineSeries]
