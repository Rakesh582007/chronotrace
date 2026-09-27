# ChronoTrace API

Reference for the frontend (step 8). Everything the UI needs is here: each endpoint has a complete
example request and the complete response it produced. The examples come from real runs on the
demo patient (type 2 diabetes + chronic kidney disease) and are checked in the test suite
(`tests/test_api_contract.py`): every response below must have exactly the same keys and value
types as the running API, so this file and the code cannot drift apart.

## Basics

- Run locally from the repo root: `uvicorn backend.main:app --reload` → `http://127.0.0.1:8000`.
  Interactive docs are at `/docs`. CORS allows `http://localhost:5173` (Vite) by default; set
  `CHRONOTRACE_CORS` to a comma-separated list to change it.
- JSON everywhere except the report upload (multipart form). Dates are `YYYY-MM-DD`; timestamps are
  ISO 8601 in UTC. Ids are integers.
- Errors are `{"detail": ...}` where `detail` is a string or an object (see [Errors](#errors)).
- Database: SQLite file `backend/chronotrace.db` (git-ignored), or `CHRONOTRACE_DB` (SQLAlchemy URL).
- Model: `ml/models/chronotrace-ner` if present, else the Hugging Face Hub model
  `Rip-Shadw/chronotrace-report-ner`; `CHRONOTRACE_MODEL` overrides both. It loads on the first upload
  (a few seconds) and runs on CPU.

## How the screens use it

1. **Patients**: `GET /patients`, `POST /patients`.
2. **Upload**: `POST /patients/{id}/reports` with the PDF. The response is the report with its
   extracted observations. Nothing is in the timeline yet.
3. **Review**: show `observations` grouped by `status`, and `skipped` lines with their reasons. The
   doctor can edit a value or unit, map a test to an analyte, reject an observation, add a result from a
   skipped line, and enter the report date if `collected_at` is null. Reload with `GET /reports/{id}`.
4. **Confirm**: `POST /reports/{id}/confirm` with the edits. It fails (422) until every
   `needs_review` observation is fixed or rejected and the report has a date.
5. **Timeline**: `GET /patients/{id}/timeline` returns confirmed values per analyte. Each point
   carries `report_id`, `lab`, `date`, `page` and `line`, so every point links back to where it was
   printed.
6. **Medications**: `POST /patients/{id}/medications` (start, stop, dose change), `GET`, `DELETE`.
7. **Trends and flags**: `GET /patients/{id}/trends`, `GET /patients/{id}/flags` and
   `GET /medications/{id}/response`, all recomputed from confirmed data on each request.

## Statuses and fields

### Observation `status`

| status | meaning | canonical value | in timeline |
| --- | --- | --- | --- |
| `extracted` | tracked analyte, numeric value, known unit; waiting for the doctor | yes | after confirm |
| `needs_review` | the doctor must fix it first; `status_reason` says what (unknown unit, value not a number, name matches two tests, eGFR cannot be computed: no creatinine, no report date, creatinine 0 or censored, age outside 18-120) | no | no (blocks confirm) |
| `not_tracked` | test not in the ChronoTrace dictionary; kept exactly as printed | no | no |
| `confirmed` | accepted by the doctor | yes | yes |
| `rejected` | rejected by the doctor (kept for the record) | no | no |

### Observation fields

| field | type | notes |
| --- | --- | --- |
| `id`, `report_id` | int | |
| `analyte_id` | string or null | dictionary id, e.g. `hba1c`; null when not tracked or ambiguous |
| `analyte_name` | string or null | display name from the dictionary, e.g. `HbA1c` |
| `match` | string or null | how the name was matched: `exact`, `loose` (punctuation/qualifiers ignored), `doctor`, or null |
| `test_text`, `value_text`, `unit_text`, `range_text`, `flag_text` | string | exactly as printed (`""` when absent). `range_text` is the first range line without its interpretation |
| `row_text` | string | the whole printed line |
| `range_lines` | string[] | every line of the reference range as printed (first line first) |
| `notes` | string[] | continuation lines: method, specimen, accreditation codes |
| `comparator` | string or null | `<`, `>`, `<=`, `>=` for censored values such as `<0.5`; the number is still stored |
| `value_number` | number or null | the printed number, in the printed unit |
| `canonical_value`, `canonical_unit` | number / string or null | value converted to the dictionary's unit; eGFR is always recomputed (CKD-EPI 2021) from the same report's creatinine and the patient's age and sex, never taken from the report |
| `page`, `line` | int | where it was printed: page number and line on that page (1-based, counted from the top) |
| `status`, `status_reason` | string | see above; the reason is `""` when there is nothing to say |
| `edited` | bool | changed, added or rejected by the doctor |

### Report fields

| field | type | notes |
| --- | --- | --- |
| `collected_at` | date or null | date used for the timeline; null when the report shows none (the doctor must enter it) |
| `date_label` | string or null | where that date came from: `Collected` (preferred), `Reported` (fallback), `Entered by doctor`, or null |
| `reported_at` | date or null | the report's "Reported" date when printed |
| `lab` | string or null | lab name found in the page header, if any |
| `layout` | string | `header` (columns found from the table header line) or `no header` (fell back to the model's tags alone; review more carefully) |
| `status` | string | `extracted` or `confirmed` |
| `file_sha256` | string | the same file cannot be uploaded twice |

### `skipped`

Lines that are not observations, each with the reason: every line where the model saw a value ends up
as an observation, as a continuation (in `notes`/`range_lines`), or here. Typical reasons:
`page header: above the results table`, `repeated on several pages (page header or footer)`,
`looks like a result row, but the model did not tag the value cell 'Negative' as a value`,
`test name not in the dictionary and no unit or range printed: not a lab result`. The doctor can turn a
skipped line into an observation with `add` in the confirm request.

## Endpoints

### `POST /patients`: create a patient

`sex` is `male` or `female` (needed for eGFR). `birth_year` is used for the age in eGFR.

<!-- example: create-patient request -->
```json
{
  "name": "Ravi Kumar",
  "sex": "male",
  "birth_year": 1966,
  "conditions": [
    "type 2 diabetes",
    "CKD stage 3"
  ]
}
```

Response `201`:

<!-- example: create-patient response 201 -->
```json
{
  "id": 1,
  "name": "Ravi Kumar",
  "sex": "male",
  "birth_year": 1966,
  "conditions": [
    "type 2 diabetes",
    "CKD stage 3"
  ]
}
```

### `GET /patients`: list patients

Response `200`:

<!-- example: list-patients response 200 -->
```json
[
  {
    "id": 1,
    "name": "Ravi Kumar",
    "sex": "male",
    "birth_year": 1966,
    "conditions": [
      "type 2 diabetes",
      "CKD stage 3"
    ]
  }
]
```

### `POST /patients/{patient_id}/reports`: upload a report PDF

Multipart form with one field, `file` (a PDF with a text layer, at most 20 MB):

```http
POST /patients/1/reports
Content-Type: multipart/form-data; boundary=----x

------x
Content-Disposition: form-data; name="file"; filename="demo_t2d_ckd_1.pdf"
Content-Type: application/pdf

<PDF bytes>
------x--
```

```js
const form = new FormData();
form.append("file", fileInput.files[0]);
const res = await fetch(`/patients/${patientId}/reports`, { method: "POST", body: form });
```

Response `201`: the report, counts per status, observations (sorted by page and line) and skipped
lines. Here the printed eGFR was 49; the stored value is recomputed from the creatinine on the same
report. `URINE KETONES Negative` is skipped because the model did not read `Negative` as a value.

<!-- example: upload-report response 201 -->
```json
{
  "report": {
    "id": 1,
    "patient_id": 1,
    "filename": "demo_t2d_ckd_1.pdf",
    "file_sha256": "a1eb3c683aa8154f14349153ea0d236dcf0bf86578b19829809591c7e0f45821",
    "lab": "ASTERLANE DIAGNOSTICS",
    "collected_at": "2024-01-08",
    "date_label": "Collected",
    "reported_at": "2024-01-08",
    "layout": "header",
    "pages": 1,
    "status": "extracted",
    "uploaded_at": "2026-09-27T16:27:02Z",
    "confirmed_at": null
  },
  "counts": {
    "extracted": 8,
    "needs_review": 0,
    "not_tracked": 1,
    "confirmed": 0,
    "rejected": 0,
    "skipped": 2
  },
  "observations": [
    {
      "id": 1,
      "report_id": 1,
      "analyte_id": "fasting_glucose",
      "analyte_name": "Fasting Plasma Glucose",
      "match": "exact",
      "test_text": "GLUCOSE (FASTING)",
      "value_text": "162",
      "unit_text": "mg/dl",
      "range_text": "74 - 99 mg/dl",
      "flag_text": "H",
      "row_text": "GLUCOSE (FASTING) 162 H mg/dl 74 - 99 mg/dl : Normal.",
      "range_lines": [
        "74 - 99 mg/dl : Normal.",
        "100 - 125 mg/dl: IFG/Fair Control"
      ],
      "notes": [
        "Method :HEXOKINASE"
      ],
      "comparator": null,
      "value_number": 162.0,
      "canonical_value": 162.0,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 10,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 2,
      "report_id": 1,
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "match": "exact",
      "test_text": "HB A1C",
      "value_text": "8.4",
      "unit_text": "%",
      "range_text": "Nondiabetic : Less than 5.6 %",
      "flag_text": "H",
      "row_text": "HB A1C 8.4 H % Nondiabetic : Less than 5.6 %",
      "range_lines": [
        "Nondiabetic : Less than 5.6 %"
      ],
      "notes": [
        "Method : HPLC"
      ],
      "comparator": null,
      "value_number": 8.4,
      "canonical_value": 8.4,
      "canonical_unit": "%",
      "page": 1,
      "line": 12,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 3,
      "report_id": 1,
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "match": "exact",
      "test_text": "CREATININE - SERUM",
      "value_text": "1.58",
      "unit_text": "mg/dl",
      "range_text": "0.7 - 1.3",
      "flag_text": "H",
      "row_text": "CREATININE - SERUM 1.58 H mg/dl 0.7 - 1.3",
      "range_lines": [
        "0.7 - 1.3"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 1.58,
      "canonical_value": 1.58,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 14,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 4,
      "report_id": 1,
      "analyte_id": "urea",
      "analyte_name": "Blood Urea",
      "match": "exact",
      "test_text": "UREA - SERUM",
      "value_text": "54.2",
      "unit_text": "mg/dl",
      "range_text": "13 - 43",
      "flag_text": "H",
      "row_text": "UREA - SERUM 54.2 H mg/dl 13 - 43",
      "range_lines": [
        "13 - 43"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 54.2,
      "canonical_value": 54.2,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 15,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 5,
      "report_id": 1,
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "match": "exact",
      "test_text": "eGFR (CKD-EPI 2021)",
      "value_text": "49",
      "unit_text": "mL/min/1.73m2",
      "range_text": "> 90",
      "flag_text": "L",
      "row_text": "eGFR (CKD-EPI 2021) 49 L mL/min/1.73m2 > 90",
      "range_lines": [
        "> 90"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 49.0,
      "canonical_value": 50.39,
      "canonical_unit": "mL/min/1.73m²",
      "page": 1,
      "line": 16,
      "status": "extracted",
      "status_reason": "recomputed with CKD-EPI 2021 from creatinine 1.58 mg/dL (page 1, line 14), age 58, male; printed eGFR '49' kept as text",
      "edited": false
    },
    {
      "id": 6,
      "report_id": 1,
      "analyte_id": "potassium",
      "analyte_name": "Serum Potassium",
      "match": "loose",
      "test_text": "POTASSIUM - SERUM",
      "value_text": "5.1",
      "unit_text": "mmol/l",
      "range_text": "3.5 - 5.1",
      "flag_text": "",
      "row_text": "POTASSIUM - SERUM 5.1 mmol/l 3.5 - 5.1",
      "range_lines": [
        "3.5 - 5.1"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 5.1,
      "canonical_value": 5.1,
      "canonical_unit": "mmol/L",
      "page": 1,
      "line": 17,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 7,
      "report_id": 1,
      "analyte_id": "uacr",
      "analyte_name": "Urine Albumin/Creatinine Ratio",
      "match": "exact",
      "test_text": "URINE ALBUMIN/CREATININE RATIO",
      "value_text": "286",
      "unit_text": "mg/g",
      "range_text": "Less than 30",
      "flag_text": "H",
      "row_text": "URINE ALBUMIN/CREATININE RATIO 286 H mg/g Less than 30",
      "range_lines": [
        "Less than 30"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 286.0,
      "canonical_value": 286.0,
      "canonical_unit": "mg/g",
      "page": 1,
      "line": 18,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 8,
      "report_id": 1,
      "analyte_id": "tsh",
      "analyte_name": "TSH",
      "match": "exact",
      "test_text": "TSH (ULTRASENSITIVE)",
      "value_text": "2.8",
      "unit_text": "uIU/ml",
      "range_text": "0.35 - 5.5",
      "flag_text": "",
      "row_text": "TSH (ULTRASENSITIVE) 2.8 uIU/ml 0.35 - 5.5",
      "range_lines": [
        "0.35 - 5.5"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 2.8,
      "canonical_value": 2.8,
      "canonical_unit": "mIU/L",
      "page": 1,
      "line": 19,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 9,
      "report_id": 1,
      "analyte_id": null,
      "analyte_name": null,
      "match": null,
      "test_text": "VITAMIN B12",
      "value_text": "312",
      "unit_text": "pg/ml",
      "range_text": "211 - 911",
      "flag_text": "",
      "row_text": "VITAMIN B12 312 pg/ml 211 - 911",
      "range_lines": [
        "211 - 911"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 312.0,
      "canonical_value": null,
      "canonical_unit": null,
      "page": 1,
      "line": 20,
      "status": "not_tracked",
      "status_reason": "test is not in the ChronoTrace dictionary",
      "edited": false
    }
  ],
  "skipped": [
    {
      "page": 1,
      "line": 22,
      "text": "URINE KETONES Negative Negative",
      "reason": "looks like a result row, but the model did not tag the value cell 'Negative' as a value"
    },
    {
      "page": 1,
      "line": 23,
      "text": "URINE GLUCOSE Nil Nil",
      "reason": "looks like a result row, but the model did not tag the value cell 'Nil' as a value"
    }
  ]
}
```

Errors: `404` patient not found, `409` already uploaded (also when the same file is sent twice at once),
`413` larger than 20 MB, `415` not a PDF, `422` scanned PDF with no text, `422` damaged or
password-protected PDF (see [Errors](#errors)). Every error body is JSON.

### `GET /reports/{report_id}`: a report with its observations

Same body as the upload response. Response `200`:

<!-- example: get-report response 200 -->
```json
{
  "report": {
    "id": 1,
    "patient_id": 1,
    "filename": "demo_t2d_ckd_1.pdf",
    "file_sha256": "a1eb3c683aa8154f14349153ea0d236dcf0bf86578b19829809591c7e0f45821",
    "lab": "ASTERLANE DIAGNOSTICS",
    "collected_at": "2024-01-08",
    "date_label": "Collected",
    "reported_at": "2024-01-08",
    "layout": "header",
    "pages": 1,
    "status": "extracted",
    "uploaded_at": "2026-09-27T16:27:02Z",
    "confirmed_at": null
  },
  "counts": {
    "extracted": 8,
    "needs_review": 0,
    "not_tracked": 1,
    "confirmed": 0,
    "rejected": 0,
    "skipped": 2
  },
  "observations": [
    {
      "id": 1,
      "report_id": 1,
      "analyte_id": "fasting_glucose",
      "analyte_name": "Fasting Plasma Glucose",
      "match": "exact",
      "test_text": "GLUCOSE (FASTING)",
      "value_text": "162",
      "unit_text": "mg/dl",
      "range_text": "74 - 99 mg/dl",
      "flag_text": "H",
      "row_text": "GLUCOSE (FASTING) 162 H mg/dl 74 - 99 mg/dl : Normal.",
      "range_lines": [
        "74 - 99 mg/dl : Normal.",
        "100 - 125 mg/dl: IFG/Fair Control"
      ],
      "notes": [
        "Method :HEXOKINASE"
      ],
      "comparator": null,
      "value_number": 162.0,
      "canonical_value": 162.0,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 10,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 2,
      "report_id": 1,
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "match": "exact",
      "test_text": "HB A1C",
      "value_text": "8.4",
      "unit_text": "%",
      "range_text": "Nondiabetic : Less than 5.6 %",
      "flag_text": "H",
      "row_text": "HB A1C 8.4 H % Nondiabetic : Less than 5.6 %",
      "range_lines": [
        "Nondiabetic : Less than 5.6 %"
      ],
      "notes": [
        "Method : HPLC"
      ],
      "comparator": null,
      "value_number": 8.4,
      "canonical_value": 8.4,
      "canonical_unit": "%",
      "page": 1,
      "line": 12,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 3,
      "report_id": 1,
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "match": "exact",
      "test_text": "CREATININE - SERUM",
      "value_text": "1.58",
      "unit_text": "mg/dl",
      "range_text": "0.7 - 1.3",
      "flag_text": "H",
      "row_text": "CREATININE - SERUM 1.58 H mg/dl 0.7 - 1.3",
      "range_lines": [
        "0.7 - 1.3"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 1.58,
      "canonical_value": 1.58,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 14,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 4,
      "report_id": 1,
      "analyte_id": "urea",
      "analyte_name": "Blood Urea",
      "match": "exact",
      "test_text": "UREA - SERUM",
      "value_text": "54.2",
      "unit_text": "mg/dl",
      "range_text": "13 - 43",
      "flag_text": "H",
      "row_text": "UREA - SERUM 54.2 H mg/dl 13 - 43",
      "range_lines": [
        "13 - 43"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 54.2,
      "canonical_value": 54.2,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 15,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 5,
      "report_id": 1,
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "match": "exact",
      "test_text": "eGFR (CKD-EPI 2021)",
      "value_text": "49",
      "unit_text": "mL/min/1.73m2",
      "range_text": "> 90",
      "flag_text": "L",
      "row_text": "eGFR (CKD-EPI 2021) 49 L mL/min/1.73m2 > 90",
      "range_lines": [
        "> 90"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 49.0,
      "canonical_value": 50.39,
      "canonical_unit": "mL/min/1.73m²",
      "page": 1,
      "line": 16,
      "status": "extracted",
      "status_reason": "recomputed with CKD-EPI 2021 from creatinine 1.58 mg/dL (page 1, line 14), age 58, male; printed eGFR '49' kept as text",
      "edited": false
    },
    {
      "id": 6,
      "report_id": 1,
      "analyte_id": "potassium",
      "analyte_name": "Serum Potassium",
      "match": "loose",
      "test_text": "POTASSIUM - SERUM",
      "value_text": "5.1",
      "unit_text": "mmol/l",
      "range_text": "3.5 - 5.1",
      "flag_text": "",
      "row_text": "POTASSIUM - SERUM 5.1 mmol/l 3.5 - 5.1",
      "range_lines": [
        "3.5 - 5.1"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 5.1,
      "canonical_value": 5.1,
      "canonical_unit": "mmol/L",
      "page": 1,
      "line": 17,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 7,
      "report_id": 1,
      "analyte_id": "uacr",
      "analyte_name": "Urine Albumin/Creatinine Ratio",
      "match": "exact",
      "test_text": "URINE ALBUMIN/CREATININE RATIO",
      "value_text": "286",
      "unit_text": "mg/g",
      "range_text": "Less than 30",
      "flag_text": "H",
      "row_text": "URINE ALBUMIN/CREATININE RATIO 286 H mg/g Less than 30",
      "range_lines": [
        "Less than 30"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 286.0,
      "canonical_value": 286.0,
      "canonical_unit": "mg/g",
      "page": 1,
      "line": 18,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 8,
      "report_id": 1,
      "analyte_id": "tsh",
      "analyte_name": "TSH",
      "match": "exact",
      "test_text": "TSH (ULTRASENSITIVE)",
      "value_text": "2.8",
      "unit_text": "uIU/ml",
      "range_text": "0.35 - 5.5",
      "flag_text": "",
      "row_text": "TSH (ULTRASENSITIVE) 2.8 uIU/ml 0.35 - 5.5",
      "range_lines": [
        "0.35 - 5.5"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 2.8,
      "canonical_value": 2.8,
      "canonical_unit": "mIU/L",
      "page": 1,
      "line": 19,
      "status": "extracted",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 9,
      "report_id": 1,
      "analyte_id": null,
      "analyte_name": null,
      "match": null,
      "test_text": "VITAMIN B12",
      "value_text": "312",
      "unit_text": "pg/ml",
      "range_text": "211 - 911",
      "flag_text": "",
      "row_text": "VITAMIN B12 312 pg/ml 211 - 911",
      "range_lines": [
        "211 - 911"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 312.0,
      "canonical_value": null,
      "canonical_unit": null,
      "page": 1,
      "line": 20,
      "status": "not_tracked",
      "status_reason": "test is not in the ChronoTrace dictionary",
      "edited": false
    }
  ],
  "skipped": [
    {
      "page": 1,
      "line": 22,
      "text": "URINE KETONES Negative Negative",
      "reason": "looks like a result row, but the model did not tag the value cell 'Negative' as a value"
    },
    {
      "page": 1,
      "line": 23,
      "text": "URINE GLUCOSE Nil Nil",
      "reason": "looks like a result row, but the model did not tag the value cell 'Nil' as a value"
    }
  ]
}
```

### `POST /reports/{report_id}/confirm`: the doctor's review

All fields are optional:

- `collected_at`: the report date, if missing or wrong (then `date_label` becomes `Entered by doctor`).
  It must lie between the patient's birth year and today.
- `lab`: corrected lab name.
- `observations`: edits by observation `id`: `value_text` and/or `unit_text` (the value is parsed and
  converted again), `analyte_id` (map to a dictionary analyte, or `null` to mark it not tracked), or
  `"reject": true`.
- `add`: results the pipeline did not produce, usually from a `skipped` line. The `page` and `line`
  must be on the report and not already hold an observation (give a skipped line's `page` and
  `line`; that line then leaves `skipped`). `analyte_id` is optional; without it the name is matched.

Every observation still `extracted` becomes `confirmed`; eGFR is recomputed after the edits. The request
fails with `422` and changes nothing while any observation is `needs_review` or the report has no date.

Example: reject vitamin B12, restate potassium's unit, add the urine ketones line.

<!-- example: confirm-report request -->
```json
{
  "observations": [
    {
      "id": 9,
      "reject": true
    },
    {
      "id": 6,
      "value_text": "5.1",
      "unit_text": "mmol/L"
    }
  ],
  "add": [
    {
      "page": 1,
      "line": 22,
      "test_text": "URINE KETONES",
      "value_text": "Negative",
      "range_text": "Negative"
    }
  ]
}
```

Response `200`:

<!-- example: confirm-report response 200 -->
```json
{
  "report": {
    "id": 1,
    "patient_id": 1,
    "filename": "demo_t2d_ckd_1.pdf",
    "file_sha256": "a1eb3c683aa8154f14349153ea0d236dcf0bf86578b19829809591c7e0f45821",
    "lab": "ASTERLANE DIAGNOSTICS",
    "collected_at": "2024-01-08",
    "date_label": "Collected",
    "reported_at": "2024-01-08",
    "layout": "header",
    "pages": 1,
    "status": "confirmed",
    "uploaded_at": "2026-09-27T16:27:02Z",
    "confirmed_at": "2026-09-27T16:27:02Z"
  },
  "counts": {
    "extracted": 0,
    "needs_review": 0,
    "not_tracked": 1,
    "confirmed": 8,
    "rejected": 1,
    "skipped": 1
  },
  "observations": [
    {
      "id": 1,
      "report_id": 1,
      "analyte_id": "fasting_glucose",
      "analyte_name": "Fasting Plasma Glucose",
      "match": "exact",
      "test_text": "GLUCOSE (FASTING)",
      "value_text": "162",
      "unit_text": "mg/dl",
      "range_text": "74 - 99 mg/dl",
      "flag_text": "H",
      "row_text": "GLUCOSE (FASTING) 162 H mg/dl 74 - 99 mg/dl : Normal.",
      "range_lines": [
        "74 - 99 mg/dl : Normal.",
        "100 - 125 mg/dl: IFG/Fair Control"
      ],
      "notes": [
        "Method :HEXOKINASE"
      ],
      "comparator": null,
      "value_number": 162.0,
      "canonical_value": 162.0,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 10,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 2,
      "report_id": 1,
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "match": "exact",
      "test_text": "HB A1C",
      "value_text": "8.4",
      "unit_text": "%",
      "range_text": "Nondiabetic : Less than 5.6 %",
      "flag_text": "H",
      "row_text": "HB A1C 8.4 H % Nondiabetic : Less than 5.6 %",
      "range_lines": [
        "Nondiabetic : Less than 5.6 %"
      ],
      "notes": [
        "Method : HPLC"
      ],
      "comparator": null,
      "value_number": 8.4,
      "canonical_value": 8.4,
      "canonical_unit": "%",
      "page": 1,
      "line": 12,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 3,
      "report_id": 1,
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "match": "exact",
      "test_text": "CREATININE - SERUM",
      "value_text": "1.58",
      "unit_text": "mg/dl",
      "range_text": "0.7 - 1.3",
      "flag_text": "H",
      "row_text": "CREATININE - SERUM 1.58 H mg/dl 0.7 - 1.3",
      "range_lines": [
        "0.7 - 1.3"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 1.58,
      "canonical_value": 1.58,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 14,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 4,
      "report_id": 1,
      "analyte_id": "urea",
      "analyte_name": "Blood Urea",
      "match": "exact",
      "test_text": "UREA - SERUM",
      "value_text": "54.2",
      "unit_text": "mg/dl",
      "range_text": "13 - 43",
      "flag_text": "H",
      "row_text": "UREA - SERUM 54.2 H mg/dl 13 - 43",
      "range_lines": [
        "13 - 43"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 54.2,
      "canonical_value": 54.2,
      "canonical_unit": "mg/dL",
      "page": 1,
      "line": 15,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 5,
      "report_id": 1,
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "match": "exact",
      "test_text": "eGFR (CKD-EPI 2021)",
      "value_text": "49",
      "unit_text": "mL/min/1.73m2",
      "range_text": "> 90",
      "flag_text": "L",
      "row_text": "eGFR (CKD-EPI 2021) 49 L mL/min/1.73m2 > 90",
      "range_lines": [
        "> 90"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 49.0,
      "canonical_value": 50.39,
      "canonical_unit": "mL/min/1.73m²",
      "page": 1,
      "line": 16,
      "status": "confirmed",
      "status_reason": "recomputed with CKD-EPI 2021 from creatinine 1.58 mg/dL (page 1, line 14), age 58, male; printed eGFR '49' kept as text",
      "edited": false
    },
    {
      "id": 6,
      "report_id": 1,
      "analyte_id": "potassium",
      "analyte_name": "Serum Potassium",
      "match": "loose",
      "test_text": "POTASSIUM - SERUM",
      "value_text": "5.1",
      "unit_text": "mmol/L",
      "range_text": "3.5 - 5.1",
      "flag_text": "",
      "row_text": "POTASSIUM - SERUM 5.1 mmol/l 3.5 - 5.1",
      "range_lines": [
        "3.5 - 5.1"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 5.1,
      "canonical_value": 5.1,
      "canonical_unit": "mmol/L",
      "page": 1,
      "line": 17,
      "status": "confirmed",
      "status_reason": "",
      "edited": true
    },
    {
      "id": 7,
      "report_id": 1,
      "analyte_id": "uacr",
      "analyte_name": "Urine Albumin/Creatinine Ratio",
      "match": "exact",
      "test_text": "URINE ALBUMIN/CREATININE RATIO",
      "value_text": "286",
      "unit_text": "mg/g",
      "range_text": "Less than 30",
      "flag_text": "H",
      "row_text": "URINE ALBUMIN/CREATININE RATIO 286 H mg/g Less than 30",
      "range_lines": [
        "Less than 30"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 286.0,
      "canonical_value": 286.0,
      "canonical_unit": "mg/g",
      "page": 1,
      "line": 18,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 8,
      "report_id": 1,
      "analyte_id": "tsh",
      "analyte_name": "TSH",
      "match": "exact",
      "test_text": "TSH (ULTRASENSITIVE)",
      "value_text": "2.8",
      "unit_text": "uIU/ml",
      "range_text": "0.35 - 5.5",
      "flag_text": "",
      "row_text": "TSH (ULTRASENSITIVE) 2.8 uIU/ml 0.35 - 5.5",
      "range_lines": [
        "0.35 - 5.5"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 2.8,
      "canonical_value": 2.8,
      "canonical_unit": "mIU/L",
      "page": 1,
      "line": 19,
      "status": "confirmed",
      "status_reason": "",
      "edited": false
    },
    {
      "id": 9,
      "report_id": 1,
      "analyte_id": null,
      "analyte_name": null,
      "match": null,
      "test_text": "VITAMIN B12",
      "value_text": "312",
      "unit_text": "pg/ml",
      "range_text": "211 - 911",
      "flag_text": "",
      "row_text": "VITAMIN B12 312 pg/ml 211 - 911",
      "range_lines": [
        "211 - 911"
      ],
      "notes": [],
      "comparator": null,
      "value_number": 312.0,
      "canonical_value": null,
      "canonical_unit": null,
      "page": 1,
      "line": 20,
      "status": "rejected",
      "status_reason": "rejected by the doctor",
      "edited": true
    },
    {
      "id": 10,
      "report_id": 1,
      "analyte_id": null,
      "analyte_name": null,
      "match": null,
      "test_text": "URINE KETONES",
      "value_text": "Negative",
      "unit_text": "",
      "range_text": "Negative",
      "flag_text": "",
      "row_text": "URINE KETONES Negative Negative",
      "range_lines": [],
      "notes": [],
      "comparator": null,
      "value_number": null,
      "canonical_value": null,
      "canonical_unit": null,
      "page": 1,
      "line": 22,
      "status": "not_tracked",
      "status_reason": "test is not in the ChronoTrace dictionary",
      "edited": true
    }
  ],
  "skipped": [
    {
      "page": 1,
      "line": 23,
      "text": "URINE GLUCOSE Nil Nil",
      "reason": "looks like a result row, but the model did not tag the value cell 'Nil' as a value"
    }
  ]
}
```

Other `422` bodies, all `{"detail": {"message": ..., ...}}`: `collected_at` out of range, an `add` for a
line that is not free (`detail.lines`), unknown observation ids (`detail.ids`), unknown `analyte_id`
(`detail.analyte_ids`), and a report with no date:

<!-- example: confirm-no-date request -->
```json
{}
```
<!-- example: confirm-no-date response 422 -->
```json
{
  "detail": {
    "message": "enter the report date (collected_at) before confirming"
  }
}
```

Response `422` when something still needs review (request `{}` on a report whose sodium unit was
printed as `mmol/xx`):

<!-- example: confirm-needs-review response 422 -->
```json
{
  "detail": {
    "message": "fix or reject these observations before confirming",
    "observations": [
      {
        "id": 32,
        "test_text": "SERUM SODIUM",
        "reason": "unit 'mmol/xx' is not a known unit for Serum Sodium"
      }
    ]
  }
}
```

### `GET /patients/{patient_id}/timeline`: confirmed values per analyte

Analytes in dictionary order; points sorted by date. `value` is in `canonical_unit`; `value_text` and
`unit_text` are as printed. Only confirmed observations of confirmed reports appear. Two confirmed
reports of the demo patient (January and April 2024). In April the lab printed UACR as `>300`; the
model does not read a censored value as a value, so the line was skipped and the doctor added it at
confirmation. The point keeps `"comparator": ">"` (the true value is above 300):

<!-- example: timeline response 200 -->
```json
{
  "patient": {
    "id": 1,
    "name": "Ravi Kumar",
    "sex": "male",
    "birth_year": 1966,
    "conditions": [
      "type 2 diabetes",
      "CKD stage 3"
    ]
  },
  "analytes": [
    {
      "analyte_id": "hba1c",
      "name": "HbA1c",
      "canonical_unit": "%",
      "loinc": "4548-4",
      "points": [
        {
          "observation_id": 2,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 8.4,
          "comparator": null,
          "value_text": "8.4",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 12
        },
        {
          "observation_id": 12,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 7.6,
          "comparator": null,
          "value_text": "7.6",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 12
        }
      ]
    },
    {
      "analyte_id": "fasting_glucose",
      "name": "Fasting Plasma Glucose",
      "canonical_unit": "mg/dL",
      "loinc": "1558-6",
      "points": [
        {
          "observation_id": 1,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 162.0,
          "comparator": null,
          "value_text": "162",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 10
        },
        {
          "observation_id": 11,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 138.0,
          "comparator": null,
          "value_text": "138",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 10
        }
      ]
    },
    {
      "analyte_id": "creatinine",
      "name": "Serum Creatinine",
      "canonical_unit": "mg/dL",
      "loinc": "2160-0",
      "points": [
        {
          "observation_id": 3,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 1.58,
          "comparator": null,
          "value_text": "1.58",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14
        },
        {
          "observation_id": 13,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 1.72,
          "comparator": null,
          "value_text": "1.72",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14
        }
      ]
    },
    {
      "analyte_id": "urea",
      "name": "Blood Urea",
      "canonical_unit": "mg/dL",
      "loinc": "3091-6",
      "points": [
        {
          "observation_id": 4,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 54.2,
          "comparator": null,
          "value_text": "54.2",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 15
        },
        {
          "observation_id": 14,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 61.0,
          "comparator": null,
          "value_text": "61.0",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 15
        }
      ]
    },
    {
      "analyte_id": "egfr",
      "name": "eGFR (CKD-EPI 2021)",
      "canonical_unit": "mL/min/1.73m²",
      "loinc": "98979-8",
      "points": [
        {
          "observation_id": 5,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 50.39,
          "comparator": null,
          "value_text": "49",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16
        },
        {
          "observation_id": 15,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 45.51,
          "comparator": null,
          "value_text": "44",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16
        }
      ]
    },
    {
      "analyte_id": "uacr",
      "name": "Urine Albumin/Creatinine Ratio",
      "canonical_unit": "mg/g",
      "loinc": "9318-7",
      "points": [
        {
          "observation_id": 7,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 286.0,
          "comparator": null,
          "value_text": "286",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18
        },
        {
          "observation_id": 19,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 300.0,
          "comparator": ">",
          "value_text": ">300",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18
        }
      ]
    },
    {
      "analyte_id": "potassium",
      "name": "Serum Potassium",
      "canonical_unit": "mmol/L",
      "loinc": "2823-3",
      "points": [
        {
          "observation_id": 6,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 5.1,
          "comparator": null,
          "value_text": "5.1",
          "unit_text": "mmol/L",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 17
        },
        {
          "observation_id": 16,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 5.4,
          "comparator": null,
          "value_text": "5.4",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 17
        }
      ]
    },
    {
      "analyte_id": "tsh",
      "name": "TSH",
      "canonical_unit": "mIU/L",
      "loinc": "3016-3",
      "points": [
        {
          "observation_id": 8,
          "report_id": 1,
          "date": "2024-01-08",
          "value": 2.8,
          "comparator": null,
          "value_text": "2.8",
          "unit_text": "uIU/ml",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 19
        },
        {
          "observation_id": 17,
          "report_id": 2,
          "date": "2024-04-11",
          "value": 3.1,
          "comparator": null,
          "value_text": "3.1",
          "unit_text": "uIU/ml",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 19
        }
      ]
    }
  ]
}
```

## Medications and trends (step 6)

Trends and flags are **computed on every request** from the patient's confirmed values (the same data
as the timeline) and medication events. Nothing is stored, so an edit, a newly confirmed report or a
deleted medication changes them immediately. All the maths is in code; thresholds come from
`data/analytes.yaml` (reference change values) and `data/drugs.yaml` (expected drug effects). Flags
describe an observed change and where it came from; they never say what to do.

Rules the UI should explain to the doctor:

- **Censored values** (`comparator` set, e.g. UACR `>300`) are shown (`censored: true`) but never used
  in a calculation.
- **Baseline**: median of the patient's first (up to 3) results before the first medication event that
  affects the analyte. If fewer than 2 exist, the first 3 results overall (`baseline_note: "includes
  on-treatment results"`).
- **RCV flags** (`level: "change"`): `RCV_PREV` (change from the previous result) and `RCV_BASELINE`
  (change from the baseline) beyond the analyte's reference change value (RCV). Analytes without an RCV
  (post-prandial glucose, `rcv_status: "not established"`) get a trend but no RCV flags; an
  `rcv_status` of `unverified` means the RCV's source is not yet checked (show it).
- **Expected effect**: a change inside the window after a drug start whose class is expected to move
  that value in that direction carries `expected_effect` (drug, note, source). `RCV_BASELINE` flags
  also list `drug_events_since_baseline`.
- **Slope** (per year): only on results after the last drug's expected-effect window, so a planned
  drug dip is not counted as a trend. It needs 3 results over at least 365 days (`status: "ok"`);
  otherwise `"not enough span"` / `"not enough points"`.
- **KDIGO_RAPID_EGFR** (`level: "guideline"`, the only guideline rule): eGFR slope below -5
  mL/min/1.73 m² per year.
- Every flag lists the `observation_ids`, `report_ids` and `dates` it was computed from, its
  `threshold` and the values `compared`, so each one links back to the printed reports.

### `POST /patients/{patient_id}/medications`: record a drug start, stop or dose change

`change` is `start`, `stop` or `dose_change`; `date` must lie between the patient's birth year and
today. The drug name is matched (generic or brand, case-insensitive) to a class in `data/drugs.yaml`;
unlisted drugs get `drug_class: "unknown"` (kept, and counted as a confounder, but with no expected
effect).

<!-- example: add-medication request -->
```json
{
  "drug": "Atorvastatin",
  "change": "start",
  "dose_text": "10 mg OD",
  "date": "2024-08-01"
}
```

Response `201`:

<!-- example: add-medication response 201 -->
```json
{
  "id": 4,
  "patient_id": 3,
  "drug": "Atorvastatin",
  "generic": null,
  "drug_class": "unknown",
  "drug_class_name": null,
  "change": "start",
  "dose_text": "10 mg OD",
  "date": "2024-08-01"
}
```

A date in the future or before the birth year:

<!-- example: medication-bad-date request -->
```json
{
  "drug": "Atorvastatin",
  "change": "start",
  "dose_text": "10 mg OD",
  "date": "2999-01-01"
}
```

<!-- example: medication-bad-date response 422 -->
```json
{
  "detail": {
    "message": "date must be between the patient's birth year and today"
  }
}
```

### `GET /patients/{patient_id}/medications`: medication events, oldest first

<!-- example: list-medications response 200 -->
```json
[
  {
    "id": 1,
    "patient_id": 3,
    "drug": "Metformin",
    "generic": "metformin",
    "drug_class": "biguanide",
    "drug_class_name": "Biguanide",
    "change": "start",
    "dose_text": "500 mg BD",
    "date": "2023-10-02"
  },
  {
    "id": 2,
    "patient_id": 3,
    "drug": "Ramipril",
    "generic": "ramipril",
    "drug_class": "acei_arb",
    "drug_class_name": "ACE inhibitor / angiotensin receptor blocker",
    "change": "start",
    "dose_text": "2.5 mg OD",
    "date": "2024-03-04"
  },
  {
    "id": 3,
    "patient_id": 3,
    "drug": "Empagliflozin",
    "generic": "empagliflozin",
    "drug_class": "sglt2i",
    "drug_class_name": "SGLT2 inhibitor",
    "change": "start",
    "dose_text": "10 mg OD",
    "date": "2024-05-06"
  },
  {
    "id": 4,
    "patient_id": 3,
    "drug": "Atorvastatin",
    "generic": null,
    "drug_class": "unknown",
    "drug_class_name": null,
    "change": "start",
    "dose_text": "10 mg OD",
    "date": "2024-08-01"
  }
]
```

### `DELETE /medications/{medication_id}`: delete a medication event

Response `204` with no body (`404` if it does not exist). Trends and flags change accordingly.

### `GET /patients/{patient_id}/trends`: one trend per analyte

Analytes with at least one confirmed value, in dictionary order. `status` is `ok`, `insufficient data`
(fewer than 2 usable results) or `censored values only`. Each point is a timeline point plus
`censored` and `in_window` (ids of the medication events whose expected-effect window contains its
date). `slope.excluded_points` says which results were left out of the slope and why.

Example: the demo patient K. Selvam (type 2 diabetes + CKD, 10 reports from 3 labs, metformin,
ramipril and empagliflozin starts), after the latest report:

<!-- example: trends response 200 -->
```json
{
  "patient": {
    "id": 3,
    "name": "K. Selvam",
    "sex": "male",
    "birth_year": 1968,
    "conditions": [
      "type 2 diabetes",
      "chronic kidney disease"
    ]
  },
  "analytes": [
    {
      "analyte_id": "hba1c",
      "name": "HbA1c",
      "canonical_unit": "%",
      "rcv_percent": 6.3,
      "rcv_status": "verified",
      "status": "ok",
      "baseline": 8.8,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14"
      ],
      "baseline_observation_ids": [
        34,
        40
      ],
      "points": [
        {
          "observation_id": 34,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 8.9,
          "comparator": null,
          "value_text": "8.9",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 40,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 8.7,
          "comparator": null,
          "value_text": "8.7",
          "unit_text": "%",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 6,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 46,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 8.6,
          "comparator": null,
          "value_text": "8.6",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 52,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 7.4,
          "comparator": null,
          "value_text": "7.4",
          "unit_text": "%",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 12,
          "censored": false,
          "in_window": [
            1
          ]
        },
        {
          "observation_id": 58,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 7.2,
          "comparator": null,
          "value_text": "7.2",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 64,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 7.0,
          "comparator": null,
          "value_text": "7.0",
          "unit_text": "%",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 6,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 70,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 6.9,
          "comparator": null,
          "value_text": "6.9",
          "unit_text": "%",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 12,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 76,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 7.0,
          "comparator": null,
          "value_text": "7.0",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 82,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 6.9,
          "comparator": null,
          "value_text": "6.9",
          "unit_text": "%",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 6,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 88,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 7.1,
          "comparator": null,
          "value_text": "7.1",
          "unit_text": "%",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": -0.032,
        "unit": "% per year",
        "n_points": 6,
        "span_days": 700,
        "first_date": "2024-04-01",
        "last_date": "2026-03-02",
        "observation_ids": [
          58,
          64,
          70,
          76,
          82,
          88
        ],
        "excluded_points": [
          {
            "date": "2023-06-12",
            "observation_ids": [
              34
            ],
            "reason": "on or before the end of the expected-effect window of Metformin started 2023-10-02 (window ends 2024-03-30)"
          },
          {
            "date": "2023-09-14",
            "observation_ids": [
              40
            ],
            "reason": "on or before the end of the expected-effect window of Metformin started 2023-10-02 (window ends 2024-03-30)"
          },
          {
            "date": "2023-11-16",
            "observation_ids": [
              46
            ],
            "reason": "on or before the end of the expected-effect window of Metformin started 2023-10-02 (window ends 2024-03-30)"
          },
          {
            "date": "2024-02-15",
            "observation_ids": [
              52
            ],
            "reason": "on or before the end of the expected-effect window of Metformin started 2023-10-02 (window ends 2024-03-30)"
          }
        ],
        "status": "ok"
      }
    },
    {
      "analyte_id": "fasting_glucose",
      "name": "Fasting Plasma Glucose",
      "canonical_unit": "mg/dL",
      "rcv_percent": 14.9,
      "rcv_status": "unverified",
      "status": "ok",
      "baseline": 148.0,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16"
      ],
      "baseline_observation_ids": [
        33,
        39,
        45
      ],
      "points": [
        {
          "observation_id": 33,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 152.0,
          "comparator": null,
          "value_text": "152",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 39,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 148.0,
          "comparator": null,
          "value_text": "148",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 5,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 45,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 146.0,
          "comparator": null,
          "value_text": "146",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 51,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 136.0,
          "comparator": null,
          "value_text": "136",
          "unit_text": "mg/dL",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 57,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 134.0,
          "comparator": null,
          "value_text": "134",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 63,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 131.0,
          "comparator": null,
          "value_text": "131",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 5,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 69,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 130.0,
          "comparator": null,
          "value_text": "130",
          "unit_text": "mg/dL",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 11,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 75,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 132.0,
          "comparator": null,
          "value_text": "132",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 81,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 130.0,
          "comparator": null,
          "value_text": "130",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 5,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 87,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 133.0,
          "comparator": null,
          "value_text": "133",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": -7.022,
        "unit": "mg/dL per year",
        "n_points": 10,
        "span_days": 994,
        "first_date": "2023-06-12",
        "last_date": "2026-03-02",
        "observation_ids": [
          33,
          39,
          45,
          51,
          57,
          63,
          69,
          75,
          81,
          87
        ],
        "excluded_points": [],
        "status": "ok"
      }
    },
    {
      "analyte_id": "creatinine",
      "name": "Serum Creatinine",
      "canonical_unit": "mg/dL",
      "rcv_percent": 15.0,
      "rcv_status": "unverified",
      "status": "ok",
      "baseline": 1.11,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16"
      ],
      "baseline_observation_ids": [
        35,
        41,
        47
      ],
      "points": [
        {
          "observation_id": 35,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 1.1,
          "comparator": null,
          "value_text": "1.10",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 41,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 1.13,
          "comparator": null,
          "value_text": "1.13",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 7,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 47,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 1.11,
          "comparator": null,
          "value_text": "1.11",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 53,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 1.11,
          "comparator": null,
          "value_text": "1.11",
          "unit_text": "mg/dL",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 15,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 59,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 1.29,
          "comparator": null,
          "value_text": "1.29",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14,
          "censored": false,
          "in_window": [
            2
          ]
        },
        {
          "observation_id": 65,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 1.35,
          "comparator": null,
          "value_text": "1.35",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 7,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 71,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 1.31,
          "comparator": null,
          "value_text": "1.31",
          "unit_text": "mg/dL",
          "lab": "Varnika Clinical Labs",
          "page": 2,
          "line": 7,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 77,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 1.35,
          "comparator": null,
          "value_text": "1.35",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 83,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 1.41,
          "comparator": null,
          "value_text": "1.41",
          "unit_text": "mg/dL",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 7,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 89,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 1.49,
          "comparator": null,
          "value_text": "1.49",
          "unit_text": "mg/dl",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 14,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": 0.091,
        "unit": "mg/dL per year",
        "n_points": 5,
        "span_days": 630,
        "first_date": "2024-06-10",
        "last_date": "2026-03-02",
        "observation_ids": [
          65,
          71,
          77,
          83,
          89
        ],
        "excluded_points": [
          {
            "date": "2023-06-12",
            "observation_ids": [
              35
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2023-09-14",
            "observation_ids": [
              41
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2023-11-16",
            "observation_ids": [
              47
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2024-02-15",
            "observation_ids": [
              53
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2024-04-01",
            "observation_ids": [
              59
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          }
        ],
        "status": "ok"
      }
    },
    {
      "analyte_id": "egfr",
      "name": "eGFR (CKD-EPI 2021)",
      "canonical_unit": "mL/min/1.73m²",
      "rcv_percent": 15.4,
      "rcv_status": "unverified",
      "status": "ok",
      "baseline": 78.42,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16"
      ],
      "baseline_observation_ids": [
        36,
        42,
        48
      ],
      "points": [
        {
          "observation_id": 36,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 79.28,
          "comparator": null,
          "value_text": "79",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 42,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 76.76,
          "comparator": null,
          "value_text": "77",
          "unit_text": "mL/min/1.73m2",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 8,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 48,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 78.42,
          "comparator": null,
          "value_text": "78",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 54,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 77.94,
          "comparator": null,
          "value_text": "78",
          "unit_text": "mL/min/1.73m²",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 60,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 65.08,
          "comparator": null,
          "value_text": "65",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": [
            2
          ]
        },
        {
          "observation_id": 66,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 61.62,
          "comparator": null,
          "value_text": "62",
          "unit_text": "mL/min/1.73m2",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 8,
          "censored": false,
          "in_window": [
            3
          ]
        },
        {
          "observation_id": 72,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 63.88,
          "comparator": null,
          "value_text": "64",
          "unit_text": "mL/min/1.73m²",
          "lab": "Varnika Clinical Labs",
          "page": 2,
          "line": 8,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 78,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 61.24,
          "comparator": null,
          "value_text": "61",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 84,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 58.12,
          "comparator": null,
          "value_text": "58",
          "unit_text": "mL/min/1.73m2",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 8,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 90,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 54.06,
          "comparator": null,
          "value_text": "54",
          "unit_text": "mL/min/1.73m2",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 16,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": -7.081,
        "unit": "mL/min/1.73m² per year",
        "n_points": 4,
        "span_days": 503,
        "first_date": "2024-10-15",
        "last_date": "2026-03-02",
        "observation_ids": [
          72,
          78,
          84,
          90
        ],
        "excluded_points": [
          {
            "date": "2023-06-12",
            "observation_ids": [
              36
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2023-09-14",
            "observation_ids": [
              42
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2023-11-16",
            "observation_ids": [
              48
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-02-15",
            "observation_ids": [
              54
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-04-01",
            "observation_ids": [
              60
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-06-10",
            "observation_ids": [
              66
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          }
        ],
        "status": "ok"
      }
    },
    {
      "analyte_id": "uacr",
      "name": "Urine Albumin/Creatinine Ratio",
      "canonical_unit": "mg/g",
      "rcv_percent": 87.0,
      "rcv_status": "unverified",
      "status": "ok",
      "baseline": 122.0,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16"
      ],
      "baseline_observation_ids": [
        38,
        44,
        50
      ],
      "points": [
        {
          "observation_id": 38,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 118.0,
          "comparator": null,
          "value_text": "118",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 21,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 44,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 126.0,
          "comparator": null,
          "value_text": "126",
          "unit_text": "mg/g",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 10,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 50,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 122.0,
          "comparator": null,
          "value_text": "122",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 21,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 56,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 131.0,
          "comparator": null,
          "value_text": "131",
          "unit_text": "mg/g",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 62,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 148.0,
          "comparator": null,
          "value_text": "148",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 21,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 68,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 142.0,
          "comparator": null,
          "value_text": "142",
          "unit_text": "mg/g",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 10,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 74,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 139.0,
          "comparator": null,
          "value_text": "139",
          "unit_text": "mg/g",
          "lab": "Varnika Clinical Labs",
          "page": 2,
          "line": 10,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 80,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 151.0,
          "comparator": null,
          "value_text": "151",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 21,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 86,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 160.0,
          "comparator": null,
          "value_text": "160",
          "unit_text": "mg/g",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 10,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 92,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 172.0,
          "comparator": null,
          "value_text": "172",
          "unit_text": "mg/g",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 21,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": 18.599,
        "unit": "mg/g per year",
        "n_points": 10,
        "span_days": 994,
        "first_date": "2023-06-12",
        "last_date": "2026-03-02",
        "observation_ids": [
          38,
          44,
          50,
          56,
          62,
          68,
          74,
          80,
          86,
          92
        ],
        "excluded_points": [],
        "status": "ok"
      }
    },
    {
      "analyte_id": "potassium",
      "name": "Serum Potassium",
      "canonical_unit": "mmol/L",
      "rcv_percent": 11.8,
      "rcv_status": "unverified",
      "status": "ok",
      "baseline": 4.5,
      "baseline_note": null,
      "baseline_dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16"
      ],
      "baseline_observation_ids": [
        37,
        43,
        49
      ],
      "points": [
        {
          "observation_id": 37,
          "report_id": 5,
          "date": "2023-06-12",
          "value": 4.5,
          "comparator": null,
          "value_text": "4.5",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 43,
          "report_id": 6,
          "date": "2023-09-14",
          "value": 4.6,
          "comparator": null,
          "value_text": "4.6",
          "unit_text": "mmol/L",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 49,
          "report_id": 7,
          "date": "2023-11-16",
          "value": 4.5,
          "comparator": null,
          "value_text": "4.5",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 55,
          "report_id": 8,
          "date": "2024-02-15",
          "value": 4.6,
          "comparator": null,
          "value_text": "4.6",
          "unit_text": "mmol/L",
          "lab": "Varnika Clinical Labs",
          "page": 1,
          "line": 17,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 61,
          "report_id": 9,
          "date": "2024-04-01",
          "value": 4.9,
          "comparator": null,
          "value_text": "4.9",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": [
            2
          ]
        },
        {
          "observation_id": 67,
          "report_id": 10,
          "date": "2024-06-10",
          "value": 4.9,
          "comparator": null,
          "value_text": "4.9",
          "unit_text": "mmol/L",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 73,
          "report_id": 11,
          "date": "2024-10-15",
          "value": 4.8,
          "comparator": null,
          "value_text": "4.8",
          "unit_text": "mmol/L",
          "lab": "Varnika Clinical Labs",
          "page": 2,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 79,
          "report_id": 12,
          "date": "2025-03-10",
          "value": 4.9,
          "comparator": null,
          "value_text": "4.9",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 85,
          "report_id": 13,
          "date": "2025-09-01",
          "value": 5.0,
          "comparator": null,
          "value_text": "5.0",
          "unit_text": "mmol/L",
          "lab": "Kestrelline Labs",
          "page": 1,
          "line": 9,
          "censored": false,
          "in_window": []
        },
        {
          "observation_id": 91,
          "report_id": 14,
          "date": "2026-03-02",
          "value": 5.0,
          "comparator": null,
          "value_text": "5.0",
          "unit_text": "mmol/l",
          "lab": "ASTERLANE DIAGNOSTICS",
          "page": 1,
          "line": 18,
          "censored": false,
          "in_window": []
        }
      ],
      "slope": {
        "per_year": 0.095,
        "unit": "mmol/L per year",
        "n_points": 5,
        "span_days": 630,
        "first_date": "2024-06-10",
        "last_date": "2026-03-02",
        "observation_ids": [
          67,
          73,
          79,
          85,
          91
        ],
        "excluded_points": [
          {
            "date": "2023-06-12",
            "observation_ids": [
              37
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2023-09-14",
            "observation_ids": [
              43
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2023-11-16",
            "observation_ids": [
              49
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2024-02-15",
            "observation_ids": [
              55
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          },
          {
            "date": "2024-04-01",
            "observation_ids": [
              61
            ],
            "reason": "on or before the end of the expected-effect window of Ramipril started 2024-03-04 (window ends 2024-05-03)"
          }
        ],
        "status": "ok"
      }
    }
  ]
}
```

### `GET /patients/{patient_id}/flags`: all flags, newest first

`compared.from` / `compared.to` hold the values compared (`from.label` is `previous result` or
`baseline`); for the slope rule `compared.slope` holds the slope instead. `change_percent` is rounded
to 1 decimal and is the number compared with the threshold. `message` is a plain sentence for the UI.
In this example the last report's eGFR is only 7% below the one before (within the RCV), but the
slope since the drug windows ended is below -5 per year, so `KDIGO_RAPID_EGFR` fires:

<!-- example: flags response 200 -->
```json
{
  "patient_id": 3,
  "flags": [
    {
      "id": "RCV_BASELINE:hba1c:2026-03-02",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2026-03-02",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2026-03-02",
          "value": 7.1,
          "observation_ids": [
            88
          ],
          "report_ids": [
            14
          ]
        },
        "slope": null
      },
      "change_abs": -1.7,
      "change_percent": -19.3,
      "observation_ids": [
        34,
        40,
        88
      ],
      "report_ids": [
        5,
        6,
        14
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2026-03-02"
      ],
      "message": "HbA1c fell 19.3% from the baseline (8.8 → 7.1 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2026-03-02",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2026-03-02",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2026-03-02",
          "value": 54.06,
          "observation_ids": [
            90
          ],
          "report_ids": [
            14
          ]
        },
        "slope": null
      },
      "change_abs": -24.36,
      "change_percent": -31.1,
      "observation_ids": [
        36,
        42,
        48,
        90
      ],
      "report_ids": [
        5,
        6,
        7,
        14
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2026-03-02"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 31.1% from the baseline (78.42 → 54.06 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2026-03-02",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2026-03-02",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2026-03-02",
          "value": 1.49,
          "observation_ids": [
            89
          ],
          "report_ids": [
            14
          ]
        },
        "slope": null
      },
      "change_abs": 0.38,
      "change_percent": 34.2,
      "observation_ids": [
        35,
        41,
        47,
        89
      ],
      "report_ids": [
        5,
        6,
        7,
        14
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2026-03-02"
      ],
      "message": "Serum Creatinine rose 34.2% from the baseline (1.11 → 1.49 mg/dL), more than its reference change value of 15%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "KDIGO_RAPID_EGFR:egfr:2026-03-02",
      "rule_id": "KDIGO_RAPID_EGFR",
      "level": "guideline",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2026-03-02",
      "threshold": {
        "type": "slope_per_year",
        "value": -5.0,
        "rcv_status": null
      },
      "compared": {
        "from": null,
        "to": null,
        "slope": {
          "per_year": -7.081,
          "n_points": 4,
          "span_days": 503,
          "first_date": "2024-10-15",
          "last_date": "2026-03-02"
        }
      },
      "change_abs": null,
      "change_percent": null,
      "observation_ids": [
        72,
        78,
        84,
        90
      ],
      "report_ids": [
        11,
        12,
        13,
        14
      ],
      "dates": [
        "2024-10-15",
        "2025-03-10",
        "2025-09-01",
        "2026-03-02"
      ],
      "message": "eGFR is falling by 7.1 mL/min/1.73m² per year over 503 days (4 results), faster than the KDIGO threshold of 5 per year.",
      "expected_effect": null,
      "drug_events_since_baseline": [],
      "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD: a sustained eGFR decline of more than 5 mL/min/1.73 m2 per year is a rapid decline."
    },
    {
      "id": "RCV_BASELINE:hba1c:2025-09-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2025-09-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2025-09-01",
          "value": 6.9,
          "observation_ids": [
            82
          ],
          "report_ids": [
            13
          ]
        },
        "slope": null
      },
      "change_abs": -1.9,
      "change_percent": -21.6,
      "observation_ids": [
        34,
        40,
        82
      ],
      "report_ids": [
        5,
        6,
        13
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2025-09-01"
      ],
      "message": "HbA1c fell 21.6% from the baseline (8.8 → 6.9 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2025-09-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2025-09-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2025-09-01",
          "value": 58.12,
          "observation_ids": [
            84
          ],
          "report_ids": [
            13
          ]
        },
        "slope": null
      },
      "change_abs": -20.3,
      "change_percent": -25.9,
      "observation_ids": [
        36,
        42,
        48,
        84
      ],
      "report_ids": [
        5,
        6,
        7,
        13
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2025-09-01"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 25.9% from the baseline (78.42 → 58.12 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2025-09-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2025-09-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2025-09-01",
          "value": 1.41,
          "observation_ids": [
            83
          ],
          "report_ids": [
            13
          ]
        },
        "slope": null
      },
      "change_abs": 0.3,
      "change_percent": 27.0,
      "observation_ids": [
        35,
        41,
        47,
        83
      ],
      "report_ids": [
        5,
        6,
        7,
        13
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2025-09-01"
      ],
      "message": "Serum Creatinine rose 27.0% from the baseline (1.11 → 1.41 mg/dL), more than its reference change value of 15%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_BASELINE:hba1c:2025-03-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2025-03-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2025-03-10",
          "value": 7.0,
          "observation_ids": [
            76
          ],
          "report_ids": [
            12
          ]
        },
        "slope": null
      },
      "change_abs": -1.8,
      "change_percent": -20.5,
      "observation_ids": [
        34,
        40,
        76
      ],
      "report_ids": [
        5,
        6,
        12
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2025-03-10"
      ],
      "message": "HbA1c fell 20.5% from the baseline (8.8 → 7 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2025-03-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2025-03-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2025-03-10",
          "value": 61.24,
          "observation_ids": [
            78
          ],
          "report_ids": [
            12
          ]
        },
        "slope": null
      },
      "change_abs": -17.18,
      "change_percent": -21.9,
      "observation_ids": [
        36,
        42,
        48,
        78
      ],
      "report_ids": [
        5,
        6,
        7,
        12
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2025-03-10"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 21.9% from the baseline (78.42 → 61.24 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2025-03-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2025-03-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2025-03-10",
          "value": 1.35,
          "observation_ids": [
            77
          ],
          "report_ids": [
            12
          ]
        },
        "slope": null
      },
      "change_abs": 0.24,
      "change_percent": 21.6,
      "observation_ids": [
        35,
        41,
        47,
        77
      ],
      "report_ids": [
        5,
        6,
        7,
        12
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2025-03-10"
      ],
      "message": "Serum Creatinine rose 21.6% from the baseline (1.11 → 1.35 mg/dL), more than its reference change value of 15%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_BASELINE:hba1c:2024-10-15",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2024-10-15",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2024-10-15",
          "value": 6.9,
          "observation_ids": [
            70
          ],
          "report_ids": [
            11
          ]
        },
        "slope": null
      },
      "change_abs": -1.9,
      "change_percent": -21.6,
      "observation_ids": [
        34,
        40,
        70
      ],
      "report_ids": [
        5,
        6,
        11
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2024-10-15"
      ],
      "message": "HbA1c fell 21.6% from the baseline (8.8 → 6.9 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2024-10-15",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2024-10-15",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-10-15",
          "value": 63.88,
          "observation_ids": [
            72
          ],
          "report_ids": [
            11
          ]
        },
        "slope": null
      },
      "change_abs": -14.54,
      "change_percent": -18.5,
      "observation_ids": [
        36,
        42,
        48,
        72
      ],
      "report_ids": [
        5,
        6,
        7,
        11
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-10-15"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 18.5% from the baseline (78.42 → 63.88 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2024-10-15",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2024-10-15",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-10-15",
          "value": 1.31,
          "observation_ids": [
            71
          ],
          "report_ids": [
            11
          ]
        },
        "slope": null
      },
      "change_abs": 0.2,
      "change_percent": 18.0,
      "observation_ids": [
        35,
        41,
        47,
        71
      ],
      "report_ids": [
        5,
        6,
        7,
        11
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-10-15"
      ],
      "message": "Serum Creatinine rose 18.0% from the baseline (1.11 → 1.31 mg/dL), more than its reference change value of 15%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_BASELINE:hba1c:2024-06-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2024-06-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2024-06-10",
          "value": 7.0,
          "observation_ids": [
            64
          ],
          "report_ids": [
            10
          ]
        },
        "slope": null
      },
      "change_abs": -1.8,
      "change_percent": -20.5,
      "observation_ids": [
        34,
        40,
        64
      ],
      "report_ids": [
        5,
        6,
        10
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2024-06-10"
      ],
      "message": "HbA1c fell 20.5% from the baseline (8.8 → 7 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2024-06-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2024-06-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-06-10",
          "value": 61.62,
          "observation_ids": [
            66
          ],
          "report_ids": [
            10
          ]
        },
        "slope": null
      },
      "change_abs": -16.8,
      "change_percent": -21.4,
      "observation_ids": [
        36,
        42,
        48,
        66
      ],
      "report_ids": [
        5,
        6,
        7,
        10
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-06-10"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 21.4% from the baseline (78.42 → 61.62 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": {
        "event_id": 3,
        "drug": "Empagliflozin",
        "drug_class": "sglt2i",
        "note": "a small initial eGFR dip (a few mL/min) is expected after starting an SGLT2 inhibitor, then eGFR usually stabilises",
        "source": "KDIGO 2024 CKD guideline; DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27): the initial eGFR dip after starting an SGLT2 inhibitor is expected and is not a reason to stop it.",
        "window": {
          "start": "2024-05-13",
          "end": "2024-08-04"
        }
      },
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2024-06-10",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2024-06-10",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-06-10",
          "value": 1.35,
          "observation_ids": [
            65
          ],
          "report_ids": [
            10
          ]
        },
        "slope": null
      },
      "change_abs": 0.24,
      "change_percent": 21.6,
      "observation_ids": [
        35,
        41,
        47,
        65
      ],
      "report_ids": [
        5,
        6,
        7,
        10
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-06-10"
      ],
      "message": "Serum Creatinine rose 21.6% from the baseline (1.11 → 1.35 mg/dL), more than its reference change value of 15%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_PREV:egfr:2024-04-01",
      "rule_id": "RCV_PREV",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2024-04-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "previous result",
          "value": 77.94,
          "dates": [
            "2024-02-15"
          ],
          "observation_ids": [
            54
          ],
          "report_ids": [
            8
          ],
          "note": null
        },
        "to": {
          "date": "2024-04-01",
          "value": 65.08,
          "observation_ids": [
            60
          ],
          "report_ids": [
            9
          ]
        },
        "slope": null
      },
      "change_abs": -12.86,
      "change_percent": -16.5,
      "observation_ids": [
        54,
        60
      ],
      "report_ids": [
        8,
        9
      ],
      "dates": [
        "2024-02-15",
        "2024-04-01"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 16.5% from the previous result (77.94 → 65.08 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": {
        "event_id": 2,
        "drug": "Ramipril",
        "drug_class": "acei_arb",
        "note": "an eGFR fall is expected after starting an ACE inhibitor or ARB (the creatinine rise seen through the eGFR formula)",
        "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (Kidney Int 2024;105(4S):S117-S314): continue ACEi/ARB unless serum creatinine rises by more than 30% within 4 weeks of starting or increasing the dose.",
        "window": {
          "start": "2024-03-11",
          "end": "2024-05-03"
        }
      },
      "drug_events_since_baseline": [],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_PREV:creatinine:2024-04-01",
      "rule_id": "RCV_PREV",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2024-04-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "previous result",
          "value": 1.11,
          "dates": [
            "2024-02-15"
          ],
          "observation_ids": [
            53
          ],
          "report_ids": [
            8
          ],
          "note": null
        },
        "to": {
          "date": "2024-04-01",
          "value": 1.29,
          "observation_ids": [
            59
          ],
          "report_ids": [
            9
          ]
        },
        "slope": null
      },
      "change_abs": 0.18,
      "change_percent": 16.2,
      "observation_ids": [
        53,
        59
      ],
      "report_ids": [
        8,
        9
      ],
      "dates": [
        "2024-02-15",
        "2024-04-01"
      ],
      "message": "Serum Creatinine rose 16.2% from the previous result (1.11 → 1.29 mg/dL), more than its reference change value of 15%.",
      "expected_effect": {
        "event_id": 2,
        "drug": "Ramipril",
        "drug_class": "acei_arb",
        "note": "within the ≤30% rise expected after ACEi/ARB start",
        "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (Kidney Int 2024;105(4S):S117-S314): continue ACEi/ARB unless serum creatinine rises by more than 30% within 4 weeks of starting or increasing the dose.",
        "window": {
          "start": "2024-03-11",
          "end": "2024-05-03"
        }
      },
      "drug_events_since_baseline": [],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_BASELINE:hba1c:2024-04-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2024-04-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2024-04-01",
          "value": 7.2,
          "observation_ids": [
            58
          ],
          "report_ids": [
            9
          ]
        },
        "slope": null
      },
      "change_abs": -1.6,
      "change_percent": -18.2,
      "observation_ids": [
        34,
        40,
        58
      ],
      "report_ids": [
        5,
        6,
        9
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2024-04-01"
      ],
      "message": "HbA1c fell 18.2% from the baseline (8.8 → 7.2 %), more than its reference change value of 6.3%.",
      "expected_effect": null,
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:egfr:2024-04-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "egfr",
      "analyte_name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "direction": "fall",
      "date": "2024-04-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.4,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 78.42,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            36,
            42,
            48
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-04-01",
          "value": 65.08,
          "observation_ids": [
            60
          ],
          "report_ids": [
            9
          ]
        },
        "slope": null
      },
      "change_abs": -13.34,
      "change_percent": -17.0,
      "observation_ids": [
        36,
        42,
        48,
        60
      ],
      "report_ids": [
        5,
        6,
        7,
        9
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-04-01"
      ],
      "message": "eGFR (CKD-EPI 2021) fell 17.0% from the baseline (78.42 → 65.08 mL/min/1.73m²), more than its reference change value of 15.4%.",
      "expected_effect": {
        "event_id": 2,
        "drug": "Ramipril",
        "drug_class": "acei_arb",
        "note": "an eGFR fall is expected after starting an ACE inhibitor or ARB (the creatinine rise seen through the eGFR formula)",
        "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (Kidney Int 2024;105(4S):S117-S314): continue ACEi/ARB unless serum creatinine rises by more than 30% within 4 weeks of starting or increasing the dose.",
        "window": {
          "start": "2024-03-11",
          "end": "2024-05-03"
        }
      },
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "Propagated from the creatinine RCV: 1 - (1 + RCV_creatinine)^-1.200 (Scr above kappa). Not an independently published RCV"
    },
    {
      "id": "RCV_BASELINE:creatinine:2024-04-01",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "creatinine",
      "analyte_name": "Serum Creatinine",
      "unit": "mg/dL",
      "direction": "rise",
      "date": "2024-04-01",
      "threshold": {
        "type": "rcv_percent",
        "value": 15.0,
        "rcv_status": "unverified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 1.11,
          "dates": [
            "2023-06-12",
            "2023-09-14",
            "2023-11-16"
          ],
          "observation_ids": [
            35,
            41,
            47
          ],
          "report_ids": [
            5,
            6,
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-04-01",
          "value": 1.29,
          "observation_ids": [
            59
          ],
          "report_ids": [
            9
          ]
        },
        "slope": null
      },
      "change_abs": 0.18,
      "change_percent": 16.2,
      "observation_ids": [
        35,
        41,
        47,
        59
      ],
      "report_ids": [
        5,
        6,
        7,
        9
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2023-11-16",
        "2024-04-01"
      ],
      "message": "Serum Creatinine rose 16.2% from the baseline (1.11 → 1.29 mg/dL), more than its reference change value of 15%.",
      "expected_effect": {
        "event_id": 2,
        "drug": "Ramipril",
        "drug_class": "acei_arb",
        "note": "within the ≤30% rise expected after ACEi/ARB start",
        "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (Kidney Int 2024;105(4S):S117-S314): continue ACEi/ARB unless serum creatinine rises by more than 30% within 4 weeks of starting or increasing the dose.",
        "window": {
          "start": "2024-03-11",
          "end": "2024-05-03"
        }
      },
      "drug_events_since_baseline": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV"
    },
    {
      "id": "RCV_PREV:hba1c:2024-02-15",
      "rule_id": "RCV_PREV",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2024-02-15",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "previous result",
          "value": 8.6,
          "dates": [
            "2023-11-16"
          ],
          "observation_ids": [
            46
          ],
          "report_ids": [
            7
          ],
          "note": null
        },
        "to": {
          "date": "2024-02-15",
          "value": 7.4,
          "observation_ids": [
            52
          ],
          "report_ids": [
            8
          ]
        },
        "slope": null
      },
      "change_abs": -1.2,
      "change_percent": -14.0,
      "observation_ids": [
        46,
        52
      ],
      "report_ids": [
        7,
        8
      ],
      "dates": [
        "2023-11-16",
        "2024-02-15"
      ],
      "message": "HbA1c fell 14.0% from the previous result (8.6 → 7.4 %), more than its reference change value of 6.3%.",
      "expected_effect": {
        "event_id": 1,
        "drug": "Metformin",
        "drug_class": "biguanide",
        "note": "an HbA1c fall is expected about 3 months after starting metformin",
        "source": "ADA Standards of Care in Diabetes (section 6, Glycemic Goals): reassess HbA1c about 3 months after a change in glucose-lowering therapy.",
        "window": {
          "start": "2023-12-31",
          "end": "2024-03-30"
        }
      },
      "drug_events_since_baseline": [],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    },
    {
      "id": "RCV_BASELINE:hba1c:2024-02-15",
      "rule_id": "RCV_BASELINE",
      "level": "change",
      "analyte_id": "hba1c",
      "analyte_name": "HbA1c",
      "unit": "%",
      "direction": "fall",
      "date": "2024-02-15",
      "threshold": {
        "type": "rcv_percent",
        "value": 6.3,
        "rcv_status": "verified"
      },
      "compared": {
        "from": {
          "label": "baseline",
          "value": 8.8,
          "dates": [
            "2023-06-12",
            "2023-09-14"
          ],
          "observation_ids": [
            34,
            40
          ],
          "report_ids": [
            5,
            6
          ],
          "note": null
        },
        "to": {
          "date": "2024-02-15",
          "value": 7.4,
          "observation_ids": [
            52
          ],
          "report_ids": [
            8
          ]
        },
        "slope": null
      },
      "change_abs": -1.4,
      "change_percent": -15.9,
      "observation_ids": [
        34,
        40,
        52
      ],
      "report_ids": [
        5,
        6,
        8
      ],
      "dates": [
        "2023-06-12",
        "2023-09-14",
        "2024-02-15"
      ],
      "message": "HbA1c fell 15.9% from the baseline (8.8 → 7.4 %), more than its reference change value of 6.3%.",
      "expected_effect": {
        "event_id": 1,
        "drug": "Metformin",
        "drug_class": "biguanide",
        "note": "an HbA1c fall is expected about 3 months after starting metformin",
        "source": "ADA Standards of Care in Diabetes (section 6, Glycemic Goals): reassess HbA1c about 3 months after a change in glucose-lowering therapy.",
        "window": {
          "start": "2023-12-31",
          "end": "2024-03-30"
        }
      },
      "drug_events_since_baseline": [
        {
          "event_id": 1,
          "drug": "Metformin",
          "drug_class": "biguanide",
          "change": "start",
          "date": "2023-10-02"
        }
      ],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed"
    }
  ]
}
```

### `GET /medications/{medication_id}/response`: lab values before and after one medication event

For each value the drug's class is expected to move: `before` is the last result on or before the
event date (at most 180 days earlier), `after` the first result inside the class's window. `status`:
`assessed`, `too early to assess` (no result yet past the window start), `no baseline` (no `before`)
or `no result in window`. `confounders` are the other medication events from 90 days before this one
up to the `after` result. A drug not in the catalogue returns an empty `analytes` list and a `note`.

Example: empagliflozin, where ramipril had been started 63 days earlier:

<!-- example: medication-response response 200 -->
```json
{
  "event": {
    "event_id": 3,
    "drug": "Empagliflozin",
    "drug_class": "sglt2i",
    "change": "start",
    "date": "2024-05-06",
    "generic": "empagliflozin",
    "dose_text": "10 mg OD",
    "drug_class_name": "SGLT2 inhibitor"
  },
  "note": null,
  "analytes": [
    {
      "analyte_id": "egfr",
      "name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "expected": {
        "direction": "fall",
        "note": "a small initial eGFR dip (a few mL/min) is expected after starting an SGLT2 inhibitor, then eGFR usually stabilises",
        "source": "KDIGO 2024 CKD guideline; DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27): the initial eGFR dip after starting an SGLT2 inhibitor is expected and is not a reason to stop it.",
        "status": "unverified",
        "applies": true
      },
      "window": {
        "start": "2024-05-13",
        "end": "2024-08-04"
      },
      "before": {
        "date": "2024-04-01",
        "value": 65.08,
        "observation_ids": [
          60
        ],
        "report_ids": [
          9
        ]
      },
      "after": {
        "date": "2024-06-10",
        "value": 61.62,
        "observation_ids": [
          66
        ],
        "report_ids": [
          10
        ]
      },
      "change_abs": -3.46,
      "change_percent": -5.3,
      "rcv_percent": 15.4,
      "rcv_status": "unverified",
      "beyond_rcv": false,
      "expected_effect": {
        "event_id": 3,
        "drug": "Empagliflozin",
        "drug_class": "sglt2i",
        "note": "a small initial eGFR dip (a few mL/min) is expected after starting an SGLT2 inhibitor, then eGFR usually stabilises",
        "source": "KDIGO 2024 CKD guideline; DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27): the initial eGFR dip after starting an SGLT2 inhibitor is expected and is not a reason to stop it.",
        "window": {
          "start": "2024-05-13",
          "end": "2024-08-04"
        }
      },
      "confounders": [
        {
          "event_id": 2,
          "drug": "Ramipril",
          "drug_class": "acei_arb",
          "change": "start",
          "date": "2024-03-04",
          "days_from_event": -63
        }
      ],
      "status": "assessed"
    }
  ]
}
```

## Errors

`409` duplicate upload (the same file, for any patient):

<!-- example: upload-duplicate response 409 -->
```json
{
  "detail": {
    "message": "this report was already uploaded",
    "report_id": 1,
    "patient_id": 1
  }
}
```

`422` damaged or password-protected PDF:

<!-- example: upload-unreadable response 422 -->
```json
{
  "detail": "could not read this PDF: it is damaged or password-protected"
}
```
`422` scanned PDF (no text layer):

<!-- example: upload-scanned response 422 -->
```json
{
  "detail": "scanned reports are not supported yet"
}
```

`415` not a PDF:

<!-- example: upload-not-pdf response 415 -->
```json
{
  "detail": "only PDF files are supported"
}
```

`404` unknown patient or report:

<!-- example: not-found response 404 -->
```json
{
  "detail": "patient not found"
}
```

`422` invalid request body (FastAPI validation; `detail` lists each problem):

<!-- example: validation-error response 422 -->
```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": [
        "body",
        "sex"
      ],
      "msg": "Input should be 'male' or 'female'",
      "input": "unknown",
      "ctx": {
        "expected": "'male' or 'female'"
      }
    }
  ]
}
```
