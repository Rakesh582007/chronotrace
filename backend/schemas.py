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
    weight_kg: float | None = Field(default=None, gt=0, le=400)

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
    weight_kg: float | None


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
    page_width: float | None          # first page in PDF points; the frame of each observation's bbox
    page_height: float | None
    status: str
    uploaded_at: dt.datetime
    confirmed_at: dt.datetime | None


class DocumentOut(BaseModel):
    id: int
    patient_id: int
    kind: Literal["lab_report", "prescription", "doctor_note"]
    filename: str
    sha256: str
    size: int                         # bytes
    uploaded_at: dt.datetime
    document_date: dt.date | None
    report_id: int | None             # lab reports: the parsed report
    report_status: str | None         # lab reports: "extracted" | "confirmed"


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
    bbox: list[float] | None          # [x0, top, x1, bottom] in PDF points from the top left; None if not read
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


class Target(BaseModel):
    low: float | None                 # guideline goal range (one bound may be open)
    high: float | None
    label: str                        # "< 7%"
    source: str
    status: str                       # verified | unverified


class LabChange(BaseModel):
    from_lab: str
    to_lab: str
    same_lab_agrees: bool | None      # a same-lab result on the other side agrees within the RCV
    same_lab_report_ids: list[int]
    note: str


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
    target: Target | None             # the analyte's guideline goal, if it has one
    target_direction: str | None      # toward | away | within | unchanged (position against the target)
    lab_change: LabChange | None      # RCV_PREV across two labs


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


class Projection(BaseModel):
    threshold: float                  # next KDIGO GFR category boundary below the line's current value
    category: str                     # "G3b"
    category_range: str               # "30–44"
    from_date: dt.date                # the line's last result
    from_value: float                 # the line's value there
    per_year: float
    per_year_low: float               # 95% range of the slope (t, n-2 degrees of freedom)
    per_year_high: float
    date: dt.date                     # when the straight line reaches the threshold
    date_earliest: dt.date
    date_latest: dt.date | None       # None when the slope's range includes no fall
    n_points: int
    note: str
    source: str


class LastTest(BaseModel):
    date: dt.date
    days_since: int
    interval_months: int
    label: str                        # "at least twice a year ..."
    source: str
    status: str
    longer_than_interval: bool


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
    target: Target | None
    projection: Projection | None     # eGFR only
    last_test: LastTest | None        # /trends only (needs today's date)


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
    target: Target | None
    target_direction: str | None      # baseline -> latest against the target


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


class SummaryIn(BaseModel):
    period: Literal["since_last_visit", "range", "all"]
    from_: dt.date | None = Field(default=None, alias="from")     # range only
    to: dt.date | None = None                                      # range only

    model_config = {"populate_by_name": True}


class SummaryCited(BaseModel):
    text: str
    report_ids: list[int]             # the source reports (labels in SummaryContent.reports)


class SummarySection(BaseModel):
    title: str
    sentences: list[SummaryCited]


class SummaryMedicationRow(BaseModel):
    date: str
    drug: str
    dose: str
    observed: str


class SummaryReport(BaseModel):
    report_id: int
    label: str                        # "R7": numbered over the patient's whole history
    date: dt.date                     # confirmed reports always have one
    lab: str


class SummaryBasis(BaseModel):
    flags: int                        # computed flags the summary was written from
    medication_responses: int
    reports: int                      # confirmed reports in the period
    labs: int


class SummaryContent(BaseModel):
    key_finding: SummaryCited
    sections: list[SummarySection]
    medication_rows: list[SummaryMedicationRow]
    data_notes: list[str]
    reports: list[SummaryReport]
    basis: SummaryBasis


class SummaryOut(BaseModel):
    id: int
    patient_id: int
    period: str
    from_: dt.date = Field(alias="from", serialization_alias="from")
    to: dt.date
    created_at: dt.datetime
    model: str
    facts_sha256: str
    content: SummaryContent

    model_config = {"populate_by_name": True}


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
    target_direction: str | None      # before -> after against the analyte's target
    verdict: str | None               # seen | not seen | opposite | above expected (drug starts, assessed)
    verdict_note: str | None


class ResponseEvent(EventRef):
    generic: str | None
    dose_text: str
    drug_class_name: str | None


class MedicationResponse(BaseModel):
    event: ResponseEvent
    note: str | None
    caveat: str | None                # on every drug start: regression to the mean, adherence not recorded
    analytes: list[ResponseEntry]


# ---------------------------------------------------------------- clinical support (step 9c)

class PatientUpdate(BaseModel):
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    conditions: list[str] | None = None


class KdigoRef(BaseModel):
    date: dt.date
    value: float
    report_id: int


class KdigoPosition(BaseModel):
    date: dt.date
    g: str                            # G1 .. G5
    a: str | None                     # A1 .. A3 (None without a urine ACR in the year before)
    egfr: KdigoRef
    uacr: KdigoRef | None


class Kdigo(BaseModel):
    current: KdigoPosition | None
    history: list[KdigoPosition]
    source: str


class SuggestedCode(BaseModel):
    system: str                       # ICD-10 | ICD-10-CM | SNOMED CT
    code: str
    title: str
    why: str


class Criterion(BaseModel):
    id: str
    title: str
    status: str                       # met | not met | not enough data
    evidence: str
    report_ids: list[int]
    source: str
    recorded: bool                    # the condition is already in the patient's recorded conditions
    codes: list[SuggestedCode]


class ConditionCode(BaseModel):
    text: str
    icd10: str | None
    icd10_title: str | None
    snomed: str | None
    snomed_term: str | None
    status: str


class TestCode(BaseModel):
    analyte_id: str
    name: str
    loinc: str
    loinc_name: str


class Codes(BaseModel):
    conditions: list[ConditionCode]
    tests: list[TestCode]
    note: str


class NutritionFigure(BaseModel):
    id: str
    title: str
    figure: str
    per_day: float | None             # per-kg figures times the recorded weight; None without a weight
    unit: str
    applies_because: str
    source: str
    status: str


class Clinical(BaseModel):
    patient_id: int
    kdigo: Kdigo
    criteria: list[Criterion]
    codes: Codes
    nutrition: list[NutritionFigure]
    weight_kg: float | None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AskCited(BaseModel):
    text: str
    report_ids: list[int]


class AskOut(BaseModel):
    question: str
    answer: list[AskCited]
    in_facts: bool                    # false: the facts do not hold the answer, or it asked for a decision
    reports: list[dict]               # {"report_id", "label", "date"} for the chips
    model: str
