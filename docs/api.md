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
    "uploaded_at": "2026-09-27T15:38:03Z",
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
    "uploaded_at": "2026-09-27T15:38:03Z",
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
    "uploaded_at": "2026-09-27T15:38:03Z",
    "confirmed_at": "2026-09-27T15:38:03Z"
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
