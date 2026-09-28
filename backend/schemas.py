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
    patient_code: str                 # "CT-0001": what the UI shows; routes take the id
    name: str
    sex: str
    birth_year: int
    conditions: list[str]
    has_photo: bool


class PatientListItem(PatientOut):
    """A patient card: the flag counts come from the same engine as GET /patients/{id}/flags."""
    guideline_flags: int
    change_flags: int                 # change flags without an expected drug effect
    expected_flags: int               # change flags explained by an expected drug effect
    latest_report_date: dt.date | None
    report_count: int                 # confirmed reports
    lab_count: int                    # distinct labs among them


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


class MedicationIn(BaseModel):
    drug: str = Field(min_length=1, max_length=200)
    change: Literal["start", "stop", "dose_change"]
    dose_text: str = ""
    date: dt.date


class MedicationOut(BaseModel):
    id: int
    patient_id: int
    drug: str
    generic: str | None               # generic name when the drug is in the catalogue
    drug_class: str                   # class id from data/drugs.yaml, or "unknown"
    drug_class_name: str | None
    change: str
    dose_text: str
    date: dt.date


# ---------------------------------------------------------------- trends, flags, medication response

class DayRef(BaseModel):
    """A value used in a calculation: the mean of one date's confirmed, non-censored results."""
    date: dt.date
    value: float
    observation_ids: list[int]
    report_ids: list[int]
    labs: list[str]                   # lab of each result ("unknown lab" when the report shows none)


class FlagFrom(BaseModel):
    label: str                        # "previous result", "baseline" or "mean before the event"
    value: float
    dates: list[dt.date]
    observation_ids: list[int]
    report_ids: list[int]
    labs: list[str]
    note: str | None                  # baseline note, e.g. "includes on-treatment results"


class SlopeSummary(BaseModel):
    per_year: float
    n_points: int
    span_days: int
    first_date: dt.date
    last_date: dt.date


class Compared(BaseModel):
    from_: FlagFrom | None = Field(alias="from", serialization_alias="from")
    to: DayRef | None
    slope: SlopeSummary | None

    model_config = {"populate_by_name": True}


class Threshold(BaseModel):
    type: str                         # "rcv_percent" or "slope_per_year"
    value: float
    rcv_status: str | None            # verified | unverified (RCV flags only)


class EventRef(BaseModel):
    event_id: int
    drug: str
    drug_class: str
    change: str
    date: dt.date


class DateWindow(BaseModel):
    start: dt.date
    end: dt.date


class ExpectedEffect(BaseModel):
    event_id: int
    drug: str
    drug_class: str
    note: str
    source: str
    window: DateWindow


class Flag(BaseModel):
    id: str
    rule_id: str                      # RCV_PREV | RCV_BASELINE | KDIGO_RAPID_EGFR
    level: str                        # "change" | "guideline"
    analyte_id: str
    analyte_name: str
    unit: str
    direction: str                    # "rise" | "fall"
    date: dt.date
    threshold: Threshold
    compared: Compared
    change_abs: float | None
    change_percent: float | None
    observation_ids: list[int]
    report_ids: list[int]
    dates: list[dt.date]
    message: str
    expected_effect: ExpectedEffect | None
    drug_events_since_baseline: list[EventRef]
    source: str | None
    cross_lab: bool                   # the compared values come from different labs
    cross_lab_note: str | None


class Flags(BaseModel):
    patient_id: int
    flags: list[Flag]


class TrendPoint(TimelinePoint):
    censored: bool
    in_window: list[int]              # medication event ids whose expected-effect window contains the date


class ExcludedPoint(BaseModel):
    date: dt.date
    observation_ids: list[int]
    reason: str


class Slope(BaseModel):
    per_year: float | None
    unit: str
    n_points: int
    span_days: int
    first_date: dt.date | None
    last_date: dt.date | None
    observation_ids: list[int]
    excluded_points: list[ExcludedPoint]
    status: str                       # "ok" | "not enough span" | "not enough points"


class AnalyteTrend(BaseModel):
    analyte_id: str
    name: str
    canonical_unit: str
    rcv_percent: float | None
    rcv_status: str                   # verified | unverified | not established
    status: str                       # "ok" | "insufficient data" | "censored values only"
    baseline: float | None
    baseline_note: str | None
    baseline_dates: list[dt.date]
    baseline_observation_ids: list[int]
    points: list[TrendPoint]
    slope: Slope | None


class Trends(BaseModel):
    patient: PatientOut
    analytes: list[AnalyteTrend]


class SystemLatest(BaseModel):
    date: dt.date
    value: float
    value_text: str
    comparator: str | None
    censored: bool
    report_id: int                    # the source report of the value shown


class SystemHeadline(BaseModel):
    analyte_id: str
    name: str
    unit: str
    latest: SystemLatest | None       # None when the headline analyte has no result yet
    baseline: float | None
    change_vs_baseline_percent: float | None     # latest vs baseline, as RCV_BASELINE compares them
    slope: Slope | None


class AnalyteName(BaseModel):
    analyte_id: str
    name: str


class FlagCounts(BaseModel):
    guideline: int
    change: int                       # change flags without an expected drug effect
    expected: int                     # change flags explained by an expected drug effect


class BodySystemOut(BaseModel):
    id: str
    name: str
    order: int
    status: Literal["guideline", "changed", "stable", "no_data"]
    headline: SystemHeadline
    analytes_with_data: list[AnalyteName]
    flag_counts: FlagCounts


class Systems(BaseModel):
    patient_id: int
    systems: list[BodySystemOut]      # every system in data/analytes.yaml, in order


class Expected(BaseModel):
    direction: str
    note: str
    source: str
    status: str                       # catalogue status: verified | unverified
    applies: bool                     # expected effects are for drug starts


class Confounder(EventRef):
    days_from_event: int


class ResponseEntry(BaseModel):
    analyte_id: str
    name: str
    unit: str
    expected: Expected
    window: DateWindow
    before: FlagFrom | None           # mean of the last 2-3 results before the event
    before_values: list[DayRef]       # the results that mean was taken over
    before_note: str | None           # "single prior value"
    after: DayRef | None
    change_abs: float | None
    change_percent: float | None
    rcv_percent: float | None
    rcv_status: str
    beyond_rcv: bool | None
    cross_lab: bool | None            # before and after values come from different labs
    cross_lab_note: str | None
    expected_effect: ExpectedEffect | None
    confounders: list[Confounder]
    status: str                       # assessed | too early to assess | no baseline | no result in window


class ResponseEvent(EventRef):
    generic: str | None
    dose_text: str
    drug_class_name: str | None


class MedicationResponse(BaseModel):
    event: ResponseEvent
    note: str | None
    caveat: str | None                # on every drug start: regression to the mean, adherence not recorded
    analytes: list[ResponseEntry]
