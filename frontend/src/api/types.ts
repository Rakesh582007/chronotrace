// Types for the ChronoTrace API (docs/api.md). Field names match the JSON exactly.

export type Sex = "male" | "female";

export interface Doctor {
  id: number;
  name: string;
}

export interface Patient {
  id: number;
  patient_code: string;
  name: string;
  sex: Sex;
  birth_year: number;
  conditions: string[];
  has_photo: boolean;
}

export interface PatientCard extends Patient {
  guideline_flags: number;
  change_flags: number;
  expected_flags: number;
  latest_report_date: string | null;
  report_count: number;
  lab_count: number;
}

export interface NewPatient {
  name: string;
  sex: Sex;
  birth_year: number;
  conditions: string[];
}

export interface TrendPoint {
  observation_id: number;
  report_id: number;
  date: string;
  value: number;
  comparator: string | null;
  value_text: string;
  unit_text: string;
  lab: string | null;
  page: number;
  line: number;
  censored: boolean;
  in_window: number[];
}

export interface Slope {
  per_year: number;
  unit: string;
  n_points: number;
  span_days: number;
  first_date: string;
  last_date: string;
  observation_ids: number[];
  excluded_points: { date: string; observation_ids: number[]; reason: string }[];
  status: string;
}

export interface Target {
  low: number | null;
  high: number | null;
  label: string;
  source: string;
  status: "verified" | "unverified";
}

export type TargetDirection = "toward" | "away" | "within" | "unchanged";

export interface LabChange {
  from_lab: string;
  to_lab: string;
  same_lab_agrees: boolean | null;
  same_lab_report_ids: number[];
  note: string;
}

export interface Trend {
  analyte_id: string;
  name: string;
  canonical_unit: string;
  rcv_percent: number | null;
  rcv_status: string | null;
  status: string;
  baseline: number | null;
  baseline_note: string | null;
  baseline_dates: string[];
  baseline_observation_ids: number[];
  points: TrendPoint[];
  slope: Slope | null;
  target: Target | null;
  projection: Projection | null;
  last_test: LastTest | null;
}

export interface Projection {
  threshold: number;
  category: string;
  category_range: string;
  from_date: string;
  from_value: number;
  per_year: number;
  per_year_low: number;
  per_year_high: number;
  date: string;
  date_earliest: string;
  date_latest: string | null;
  n_points: number;
  note: string;
  source: string;
}

export interface LastTest {
  date: string;
  days_since: number;
  interval_months: number;
  label: string;
  source: string;
  status: string;
  longer_than_interval: boolean;
}

export interface TrendsResponse {
  patient: Patient;
  analytes: Trend[];
}

export interface FlagSide {
  label?: string;
  date?: string;
  value: number;
  dates?: string[];
  observation_ids: number[];
  report_ids: number[];
  labs: (string | null)[];
  note?: string | null;
}

export interface ExpectedEffect {
  event_id: number;
  drug: string;
  drug_class: string;
  note: string;
  source: string;
  window: { start: string; end: string };
}

export interface Flag {
  id: string;
  rule_id: string;
  level: "guideline" | "change";
  analyte_id: string;
  analyte_name: string;
  unit: string;
  direction: "rise" | "fall";
  date: string;
  threshold: { type: string; value: number; rcv_status: string | null };
  compared: {
    from: FlagSide | null;
    to: FlagSide | null;
    slope: { per_year: number; n_points: number; span_days: number; first_date: string; last_date: string } | null;
  };
  change_abs: number | null;
  change_percent: number | null;
  observation_ids: number[];
  report_ids: number[];
  dates: string[];
  message: string;
  expected_effect: ExpectedEffect | null;
  drug_events_since_baseline: { event_id: number; drug: string; drug_class: string; change: string; date: string }[];
  source: string;
  cross_lab: boolean;
  cross_lab_note: string | null;
  target: Target | null;
  target_direction: TargetDirection | null;
  lab_change: LabChange | null;
}

export interface FlagsResponse {
  patient_id: number;
  flags: Flag[];
}

export type SystemStatus = "guideline" | "changed" | "stable" | "no_data";

export interface BodySystem {
  id: string;
  name: string;
  order: number;
  status: SystemStatus;
  headline: {
    analyte_id: string;
    name: string;
    unit: string;
    latest: {
      date: string;
      value: number;
      value_text: string;
      comparator: string | null;
      censored: boolean;
      report_id: number;
    } | null;
    baseline: number | null;
    change_vs_baseline_percent: number | null;
    slope: Slope | null;
    target: Target | null;
    target_direction: TargetDirection | null;
  } | null;
  analytes_with_data: { analyte_id: string; name: string }[];
  flag_counts: { guideline: number; change: number; expected: number };
}

export interface SystemsResponse {
  patient_id: number;
  systems: BodySystem[];
}

export interface Medication {
  id: number;
  patient_id: number;
  drug: string;
  generic: string | null;
  drug_class: string | null;
  drug_class_name: string | null;
  change: "start" | "stop" | "dose_change";
  dose_text: string | null;
  date: string;
}

export type DocumentKind = "lab_report" | "prescription" | "doctor_note";

export interface PatientDocument {
  id: number;
  patient_id: number;
  kind: DocumentKind;
  filename: string;
  sha256: string;
  size: number;
  uploaded_at: string;
  document_date: string | null;
  report_id: number | null;
  report_status: "extracted" | "confirmed" | null;
}

export type ObservationStatus = "extracted" | "needs_review" | "not_tracked" | "confirmed" | "rejected";

export interface Observation {
  id: number;
  report_id: number;
  analyte_id: string | null;
  analyte_name: string | null;
  match: string | null;
  test_text: string;
  value_text: string;
  unit_text: string;
  range_text: string;
  flag_text: string;
  row_text: string;
  range_lines: string[];
  notes: string[];
  comparator: string | null;
  value_number: number | null;
  canonical_value: number | null;
  canonical_unit: string | null;
  page: number;
  line: number;
  bbox: [number, number, number, number] | null;
  status: ObservationStatus;
  status_reason: string;
  edited: boolean;
}

export interface Report {
  id: number;
  patient_id: number;
  filename: string;
  file_sha256: string;
  lab: string | null;
  collected_at: string | null;
  date_label: string | null;
  reported_at: string | null;
  layout: string;
  pages: number;
  page_width: number | null;
  page_height: number | null;
  status: "extracted" | "confirmed";
  uploaded_at: string;
  confirmed_at: string | null;
}

export interface SkippedLine {
  page: number;
  line: number;
  text: string;
  reason: string;
}

export interface ReportDetail {
  report: Report;
  counts: Record<string, number>;
  observations: Observation[];
  skipped: SkippedLine[];
}

export interface ConfirmBody {
  collected_at?: string;
  lab?: string;
  observations?: { id: number; value_text?: string; unit_text?: string; analyte_id?: string | null; reject?: boolean }[];
  add?: { page: number; line: number; test_text: string; value_text: string; unit_text?: string; range_text?: string; analyte_id?: string }[];
}

export type SummaryPeriod = "since_last_visit" | "range" | "all";

export interface Cited {
  text: string;
  report_ids: number[];
}

export interface Summary {
  id: number;
  patient_id: number;
  period: SummaryPeriod;
  from: string;
  to: string;
  created_at: string;
  model: string;
  facts_sha256: string;
  content: {
    key_finding: Cited;
    sections: { title: string; sentences: Cited[] }[];
    medication_rows: { date: string; drug: string; dose: string; observed: string }[];
    data_notes: string[];
    reports: { report_id: number; label: string; date: string; lab: string | null }[];
    basis: Record<string, number>;
  };
}
