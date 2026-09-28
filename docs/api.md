# ChronoTrace API

Reference for the frontend (step 8). Everything the UI needs is here: each endpoint has a complete
example request and the complete response it produced. The examples come from real runs on synthetic
patients (type 2 diabetes + chronic kidney disease) and are checked in the test suite
(`tests/test_api_contract.py`): every response below must have exactly the same keys and value
types as the running API, so this file and the code cannot drift apart.

## Basics

- Run locally from the repo root: `uvicorn backend.main:app --reload` → `http://127.0.0.1:8000`.
  Interactive docs are at `/docs`. CORS allows `http://localhost:5173` (Vite) only.
- **Sign-in**: every endpoint except `POST /auth/login` needs `Authorization: Bearer <token>`; without a
  valid token it answers `401`. Tokens last 12 hours. Data belongs to the signed-in doctor: another
  doctor's patient, report, document or medication answers `404`, as if it did not exist. The app refuses
  to start without `DEMO_DOCTOR_NAME`, `DEMO_DOCTOR_USER`, `DEMO_DOCTOR_PASSWORD` and `AUTH_SECRET`
  (at least 32 characters) in `.env`; that doctor is created on startup.
- JSON everywhere except uploads (multipart form) and files (PDF, PNG, JPG). Dates are `YYYY-MM-DD`;
  timestamps are ISO 8601 in UTC. Ids are integers; `patient_code` (`CT-0001`) is what the UI shows.
- Errors are `{"detail": ...}` where `detail` is a string or an object (see [Errors](#errors)).
- Database: SQLite file `backend/chronotrace.db` (git-ignored), or `CHRONOTRACE_DB` (SQLAlchemy URL).
  The app refuses to start on a database created by an older version; rebuild the demo data with
  `python -m backend.demo.seed --reset` (four synthetic patients, through this API).
- Files (report PDFs, prescriptions, notes, photos, rendered pages): `backend/uploads/` (git-ignored), or
  `CHRONOTRACE_UPLOADS`.
- Summaries: Gemini through `LLM_PROVIDER=gemini`, `LLM_API_KEY` and `LLM_MODEL` in `.env`. When the model
  answers 429/503 it is retried after 2 s and 5 s, then `LLM_MODEL_FALLBACKS` are tried in order; one call
  stops after about 60 s. The summary's `model` is the model that wrote it.
- Model: `ml/models/chronotrace-ner` if present, else the Hugging Face Hub model
  `Rip-Shadw/chronotrace-report-ner`; `CHRONOTRACE_MODEL` overrides both. It loads on the first upload
  (a few seconds) and runs on CPU.

## How the screens use it

0. **Sign in**: `POST /auth/login` → keep `token`; `GET /auth/me` for the doctor's name.
1. **Patients**: `GET /patients?sort=needs_review` (cards with flag counts, latest report date, report and
   lab counts), `POST /patients`, `POST`/`GET /patients/{id}/photo`.
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
8. **Overview**: `GET /patients/{id}/systems`: one card per body system with its status and headline value.
9. **Documents**: `GET /patients/{id}/documents` (lab reports, prescriptions, notes), `POST` a prescription
   or note, `GET /documents/{id}/file` to open one, `DELETE` one.
10. **Source preview**: `GET /reports/{id}/pages/{n}.png` with each observation's `bbox` to highlight the
    printed row a value came from.
11. **Summary**: `GET /patients/{id}/summaries/latest?period=…` shows the saved one;
    `POST /patients/{id}/summaries` writes a new one.

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
| `bbox` | number[4] or null | `[x0, top, x1, bottom]` of the printed row in PDF points from the page's top left; multiply by 110/72 for pixels of the page PNG. null for rows added by the doctor |
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
| `pages` | int | number of pages |
| `page_width`, `page_height` | number or null | first page in PDF points: the frame of each observation's `bbox` |
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

### `POST /auth/login`: sign in

The only endpoint without a token. A wrong username and a wrong password get the same `401`.

<!-- example: login request -->
```json
{
  "username": "dr.example",
  "password": "example-password"
}
```

Response `200` (the doc shows `<signed token>` in place of the token):

<!-- example: login response 200 -->
```json
{
  "token": "<signed token>",
  "doctor": {
    "id": 1,
    "name": "Dr. A. Example"
  }
}
```

<!-- example: login-failed request -->
```json
{
  "username": "dr.example",
  "password": "not-the-password"
}
```

<!-- example: login-failed response 401 -->
```json
{
  "detail": "Username or password is incorrect"
}
```

Any other endpoint without a valid token:

<!-- example: unauthorized response 401 -->
```json
{
  "detail": "sign in required"
}
```

### `GET /auth/me`: the signed-in doctor

<!-- example: me response 200 -->
```json
{
  "id": 1,
  "name": "Dr. A. Example"
}
```

### `POST /patients`: create a patient

`sex` is `male` or `female` (needed for eGFR). `birth_year` is used for the age in eGFR. The patient gets
the next `patient_code` (`CT-0001`, `CT-0002`, ...) and belongs to the signed-in doctor.

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
  "patient_code": "CT-0001",
  "name": "Ravi Kumar",
  "sex": "male",
  "birth_year": 1966,
  "conditions": [
    "type 2 diabetes",
    "CKD stage 3"
  ],
  "has_photo": false
}
```

### `GET /patients`: list patients

The signed-in doctor's patients, as cards. The counts come from the same engine as
`GET /patients/{id}/flags`: `guideline_flags`, `change_flags` (change flags without an expected drug
effect), `expected_flags` (change flags explained by an expected drug effect); `report_count` and
`lab_count` count confirmed reports. `?sort=` is `needs_review` (default: guideline flags, then change
flags, then the latest report first), `name` (A-Z) or `latest_report` (newest first).

Response `200`:

<!-- example: list-patients response 200 -->
```json
[
  {
    "id": 3,
    "patient_code": "CT-0003",
    "name": "K. Selvam",
    "sex": "male",
    "birth_year": 1968,
    "conditions": [
      "type 2 diabetes",
      "chronic kidney disease"
    ],
    "has_photo": false,
    "guideline_flags": 1,
    "change_flags": 3,
    "expected_flags": 2,
    "latest_report_date": "2026-03-02",
    "report_count": 10,
    "lab_count": 3
  },
  {
    "id": 1,
    "patient_code": "CT-0001",
    "name": "Ravi Kumar",
    "sex": "male",
    "birth_year": 1966,
    "conditions": [
      "type 2 diabetes",
      "CKD stage 3"
    ],
    "has_photo": true,
    "guideline_flags": 0,
    "change_flags": 1,
    "expected_flags": 0,
    "latest_report_date": "2024-04-11",
    "report_count": 2,
    "lab_count": 1
  },
  {
    "id": 2,
    "patient_code": "CT-0002",
    "name": "Edge Case",
    "sex": "male",
    "birth_year": 1967,
    "conditions": [
      "type 2 diabetes",
      "CKD stage 3"
    ],
    "has_photo": false,
    "guideline_flags": 0,
    "change_flags": 0,
    "expected_flags": 0,
    "latest_report_date": null,
    "report_count": 0,
    "lab_count": 0
  }
]
```

### `POST /patients/{patient_id}/photo`: add or replace the patient's photo

Multipart form with `file`: JPG or PNG (checked by content), at most 5 MB (`413`), otherwise `415`.
Returns the patient with `has_photo: true`.

<!-- example: upload-photo response 200 -->
```json
{
  "id": 1,
  "patient_code": "CT-0001",
  "name": "Ravi Kumar",
  "sex": "male",
  "birth_year": 1966,
  "conditions": [
    "type 2 diabetes",
    "CKD stage 3"
  ],
  "has_photo": true
}
```

### `GET /patients/{patient_id}/photo`: the photo

The image (`image/jpeg` or `image/png`), or `404` when there is none:

<!-- example: photo-missing response 404 -->
```json
{
  "detail": "no photo for this patient"
}
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
    "page_width": 612.0,
    "page_height": 792.0,
    "status": "extracted",
    "uploaded_at": "2026-09-28T06:04:33Z",
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
      "bbox": [
        46.0,
        280.1,
        522.4,
        288.1
      ],
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
      "bbox": [
        46.0,
        306.1,
        547.3,
        314.1
      ],
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
      "bbox": [
        46.0,
        332.1,
        470.4,
        340.1
      ],
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
      "bbox": [
        46.0,
        348.1,
        465.9,
        356.1
      ],
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
      "bbox": [
        46.0,
        364.1,
        456.8,
        372.1
      ],
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
      "bbox": [
        46.0,
        380.1,
        470.4,
        388.1
      ],
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
      "bbox": [
        46.0,
        396.1,
        486.8,
        404.1
      ],
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
      "bbox": [
        46.0,
        412.1,
        474.8,
        420.1
      ],
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
      "bbox": [
        46.0,
        428.1,
        474.8,
        436.1
      ],
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
    "page_width": 612.0,
    "page_height": 792.0,
    "status": "extracted",
    "uploaded_at": "2026-09-28T06:04:33Z",
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
      "bbox": [
        46.0,
        280.1,
        522.4,
        288.1
      ],
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
      "bbox": [
        46.0,
        306.1,
        547.3,
        314.1
      ],
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
      "bbox": [
        46.0,
        332.1,
        470.4,
        340.1
      ],
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
      "bbox": [
        46.0,
        348.1,
        465.9,
        356.1
      ],
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
      "bbox": [
        46.0,
        364.1,
        456.8,
        372.1
      ],
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
      "bbox": [
        46.0,
        380.1,
        470.4,
        388.1
      ],
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
      "bbox": [
        46.0,
        396.1,
        486.8,
        404.1
      ],
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
      "bbox": [
        46.0,
        412.1,
        474.8,
        420.1
      ],
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
      "bbox": [
        46.0,
        428.1,
        474.8,
        436.1
      ],
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
    "page_width": 612.0,
    "page_height": 792.0,
    "status": "confirmed",
    "uploaded_at": "2026-09-28T06:04:33Z",
    "confirmed_at": "2026-09-28T06:04:33Z"
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
      "bbox": [
        46.0,
        280.1,
        522.4,
        288.1
      ],
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
      "bbox": [
        46.0,
        306.1,
        547.3,
        314.1
      ],
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
      "bbox": [
        46.0,
        332.1,
        470.4,
        340.1
      ],
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
      "bbox": [
        46.0,
        348.1,
        465.9,
        356.1
      ],
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
      "bbox": [
        46.0,
        364.1,
        456.8,
        372.1
      ],
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
      "bbox": [
        46.0,
        380.1,
        470.4,
        388.1
      ],
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
      "bbox": [
        46.0,
        396.1,
        486.8,
        404.1
      ],
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
      "bbox": [
        46.0,
        412.1,
        474.8,
        420.1
      ],
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
      "bbox": [
        46.0,
        428.1,
        474.8,
        436.1
      ],
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
      "bbox": null,
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
    "patient_code": "CT-0001",
    "name": "Ravi Kumar",
    "sex": "male",
    "birth_year": 1966,
    "conditions": [
      "type 2 diabetes",
      "CKD stage 3"
    ],
    "has_photo": false
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
- **RCV flags** (`level: "change"`): `RCV_PREV` (change from the previous result, for every result) and
  `RCV_BASELINE` (change of the **latest** result from the baseline) beyond the analyte's reference change
  value (RCV). The baseline itself is in `/trends` for the chart. Analytes without an RCV
  (post-prandial glucose, `rcv_status: "not established"`) get a trend but no RCV flags; an
  `rcv_status` of `unverified` means the RCV's source is not yet checked (show it).
- **Expected effect**: a change inside the window after a drug start whose class is expected to move
  that value in that direction carries `expected_effect` (drug, note, source). `RCV_BASELINE` flags
  also list `drug_events_since_baseline`.
- **Slope** (per year): only on results after the last drug's expected-effect window, so a planned
  drug dip is not counted as a trend. It needs 3 results over at least 365 days (`status: "ok"`);
  otherwise `"not enough span"` / `"not enough points"`.
- **KDIGO_RAPID_EGFR** (`level: "guideline"`, the only guideline rule): eGFR slope below -5
  mL/min/1.73 m² per year (KDIGO 2012 definition of rapid progression).
- **Different labs**: when the compared values come from different labs, the flag or comparison has
  `cross_lab: true` and `cross_lab_note` ("values from different labs; between-lab variation is larger
  than the RCV assumes"). The threshold is not changed; show the note next to the flag.
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
    "patient_code": "CT-0003",
    "name": "K. Selvam",
    "sex": "male",
    "birth_year": 1968,
    "conditions": [
      "type 2 diabetes",
      "chronic kidney disease"
    ],
    "has_photo": false
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
      },
      "target": {
        "low": null,
        "high": 7.0,
        "label": "< 7%",
        "source": "ADA Standards of Care in Diabetes 2025, section 6 (Glycemic Goals): HbA1c goal < 7% for many non-pregnant adults; goals are individualised",
        "status": "verified"
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
      },
      "target": {
        "low": 80.0,
        "high": 130.0,
        "label": "80–130 mg/dL",
        "source": "ADA Standards of Care in Diabetes 2025, section 6: preprandial capillary glucose 80–130 mg/dL for many non-pregnant adults; goals are individualised",
        "status": "verified"
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
          "in_window": [
            3
          ]
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
        "per_year": 0.131,
        "unit": "mg/dL per year",
        "n_points": 4,
        "span_days": 503,
        "first_date": "2024-10-15",
        "last_date": "2026-03-02",
        "observation_ids": [
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
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2023-09-14",
            "observation_ids": [
              41
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2023-11-16",
            "observation_ids": [
              47
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-02-15",
            "observation_ids": [
              53
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-04-01",
            "observation_ids": [
              59
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          },
          {
            "date": "2024-06-10",
            "observation_ids": [
              65
            ],
            "reason": "on or before the end of the expected-effect window of Empagliflozin started 2024-05-06 (window ends 2024-08-04)"
          }
        ],
        "status": "ok"
      },
      "target": null
    },
    {
      "analyte_id": "egfr",
      "name": "eGFR (CKD-EPI 2021)",
      "canonical_unit": "mL/min/1.73m²",
      "rcv_percent": 20.0,
      "rcv_status": "verified",
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
      },
      "target": {
        "low": 60.0,
        "high": null,
        "label": "≥ 60",
        "source": "KDIGO 2024 CKD guideline, GFR categories: G1–G2 are eGFR ≥ 60 mL/min/1.73 m²; G3a–G5 are below 60",
        "status": "verified"
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
      },
      "target": {
        "low": null,
        "high": 30.0,
        "label": "< 30 mg/g",
        "source": "KDIGO 2024 CKD guideline, albuminuria categories: A1 is ACR < 30 mg/g",
        "status": "verified"
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
      },
      "target": {
        "low": 3.5,
        "high": 5.0,
        "label": "3.5–5.0 mmol/L",
        "source": "Usual adult reference interval; lab-specific",
        "status": "unverified"
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
slope since the drug windows ended is below -5 per year, so `KDIGO_RAPID_EGFR` fires. The demo's reports
alternate between three labs, so every comparison here is `cross_lab`:

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
          "labs": [
            "ASTERLANE DIAGNOSTICS",
            "Kestrelline Labs"
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
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
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
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "target": {
        "low": null,
        "high": 7.0,
        "label": "< 7%",
        "source": "ADA Standards of Care in Diabetes 2025, section 6 (Glycemic Goals): HbA1c goal < 7% for many non-pregnant adults; goals are individualised",
        "status": "verified"
      },
      "target_direction": "toward",
      "lab_change": null
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
        "value": 20.0,
        "rcv_status": "verified"
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
          "labs": [
            "ASTERLANE DIAGNOSTICS",
            "Kestrelline Labs"
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
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
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
      "message": "eGFR (CKD-EPI 2021) fell 31.1% from the baseline (78.42 → 54.06 mL/min/1.73m²), more than its reference change value of 20%.",
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
      "source": "KDIGO 2024 CKD guideline, Practice Point 2.1.3: \"For people with CKD, a change in eGFR of >20% on a subsequent test exceeds the expected variability and warrants evaluation.\"",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "target": {
        "low": 60.0,
        "high": null,
        "label": "≥ 60",
        "source": "KDIGO 2024 CKD guideline, GFR categories: G1–G2 are eGFR ≥ 60 mL/min/1.73 m²; G3a–G5 are below 60",
        "status": "verified"
      },
      "target_direction": "away",
      "lab_change": null
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
          "labs": [
            "ASTERLANE DIAGNOSTICS",
            "Kestrelline Labs"
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
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
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
        },
        {
          "event_id": 3,
          "drug": "Empagliflozin",
          "drug_class": "sglt2i",
          "change": "start",
          "date": "2024-05-06"
        }
      ],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "target": null,
      "target_direction": null,
      "lab_change": null
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
      "message": "eGFR fell by 7.1 mL/min/1.73m² per year over 503 days (4 results since the last drug window), faster than the KDIGO threshold of 5 per year.",
      "expected_effect": null,
      "drug_events_since_baseline": [],
      "source": "KDIGO 2012 definition of rapid progression (> 5 mL/min/1.73 m²/yr)",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation adds uncertainty to the slope",
      "target": {
        "low": 60.0,
        "high": null,
        "label": "≥ 60",
        "source": "KDIGO 2024 CKD guideline, GFR categories: G1–G2 are eGFR ≥ 60 mL/min/1.73 m²; G3a–G5 are below 60",
        "status": "verified"
      },
      "target_direction": "away",
      "lab_change": null
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
          "labs": [
            "Varnika Clinical Labs"
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
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
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
        "source": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD (Kidney Int 2024;105(4S):S117-S314), Practice Point 3.6.4: \"Continue ACEi or ARB therapy unless serum creatinine rises by more than 30% within 4 weeks following initiation of treatment or an increase in dose.\" See also Practice Point 2.1.4 (eGFR changes of more than 30% after starting hemodynamically active therapies).",
        "window": {
          "start": "2024-03-11",
          "end": "2024-05-03"
        }
      },
      "drug_events_since_baseline": [],
      "source": "CVi: EFLM Biological Variation Database (not checked this session); CVa: assumed, replace with lab IQC CV",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "target": null,
      "target_direction": null,
      "lab_change": {
        "from_lab": "Varnika Clinical Labs",
        "to_lab": "ASTERLANE DIAGNOSTICS",
        "same_lab_agrees": false,
        "same_lab_report_ids": [
          7
        ],
        "note": "This change coincides with a change of lab, from Varnika Clinical Labs to ASTERLANE DIAGNOSTICS. Results from ASTERLANE DIAGNOSTICS alone show a change as well (2023-11-16: 1.11)."
      }
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
          "labs": [
            "ASTERLANE DIAGNOSTICS"
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
          ],
          "labs": [
            "Varnika Clinical Labs"
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
        "source": "ADA Standards of Care in Diabetes (section 6, Glycemic Goals): HbA1c reflects about the previous 3 months, so the effect of a change in glucose-lowering therapy shows in HbA1c about 3 months later.",
        "window": {
          "start": "2023-12-31",
          "end": "2024-03-30"
        }
      },
      "drug_events_since_baseline": [],
      "source": "Median CVi in healthy subjects 1.7% (IQR 1.3–2.2), systematic review of 111 studies, PLOS ONE 2023, https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0289085; CVa assumed",
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "target": {
        "low": null,
        "high": 7.0,
        "label": "< 7%",
        "source": "ADA Standards of Care in Diabetes 2025, section 6 (Glycemic Goals): HbA1c goal < 7% for many non-pregnant adults; goals are individualised",
        "status": "verified"
      },
      "target_direction": "toward",
      "lab_change": {
        "from_lab": "ASTERLANE DIAGNOSTICS",
        "to_lab": "Varnika Clinical Labs",
        "same_lab_agrees": false,
        "same_lab_report_ids": [
          9
        ],
        "note": "This change coincides with a change of lab, from ASTERLANE DIAGNOSTICS to Varnika Clinical Labs. Results from ASTERLANE DIAGNOSTICS alone show a change as well (2024-04-01: 7.2)."
      }
    }
  ]
}
```

### `GET /medications/{medication_id}/response`: lab values before and after one medication event

For each value the drug's class is expected to move: `before` is the **mean of the last 2-3 results**
on or before the event date, at most 180 days earlier and after any earlier drug event that affects
the same value (`before_values` lists them; `before_note: "single prior value"` when there was only
one). `after` is the first result inside the class's window. `cross_lab` marks a before/after pair
from different labs. Every drug start carries `caveat` ("If this treatment was started
because of a high value, some change is expected anyway (regression to the mean). Adherence is not
recorded."). `status`:
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
  "caveat": "If this treatment was started because of a high value, some change is expected anyway (regression to the mean). Adherence is not recorded.",
  "analytes": [
    {
      "analyte_id": "egfr",
      "name": "eGFR (CKD-EPI 2021)",
      "unit": "mL/min/1.73m²",
      "expected": {
        "direction": "fall",
        "note": "a small initial eGFR dip (a few mL/min) is expected after starting an SGLT2 inhibitor, then eGFR usually stabilises",
        "source": "KDIGO 2024 CKD guideline, Practice Point 3.7.3: \"...the reversible decrease in eGFR on initiation is generally not an indication to discontinue therapy.\" See also Practice Point 2.1.4 (eGFR changes of more than 30% after starting hemodynamically active therapies). Trials: DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27).",
        "status": "verified",
        "applies": true
      },
      "window": {
        "start": "2024-05-13",
        "end": "2024-08-04"
      },
      "before": {
        "label": "mean before the event",
        "value": 65.08,
        "dates": [
          "2024-04-01"
        ],
        "observation_ids": [
          60
        ],
        "report_ids": [
          9
        ],
        "labs": [
          "ASTERLANE DIAGNOSTICS"
        ],
        "note": null
      },
      "before_values": [
        {
          "date": "2024-04-01",
          "value": 65.08,
          "observation_ids": [
            60
          ],
          "report_ids": [
            9
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
          ]
        }
      ],
      "before_note": "single prior value",
      "after": {
        "date": "2024-06-10",
        "value": 61.62,
        "observation_ids": [
          66
        ],
        "report_ids": [
          10
        ],
        "labs": [
          "Kestrelline Labs"
        ]
      },
      "change_abs": -3.46,
      "change_percent": -5.3,
      "rcv_percent": 20.0,
      "rcv_status": "verified",
      "beyond_rcv": false,
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "expected_effect": {
        "event_id": 3,
        "drug": "Empagliflozin",
        "drug_class": "sglt2i",
        "note": "a small initial eGFR dip (a few mL/min) is expected after starting an SGLT2 inhibitor, then eGFR usually stabilises",
        "source": "KDIGO 2024 CKD guideline, Practice Point 3.7.3: \"...the reversible decrease in eGFR on initiation is generally not an indication to discontinue therapy.\" See also Practice Point 2.1.4 (eGFR changes of more than 30% after starting hemodynamically active therapies). Trials: DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27).",
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
      "status": "assessed",
      "target_direction": "within",
      "verdict": "seen",
      "verdict_note": "Expected fall seen: eGFR (CKD-EPI 2021) fell 5.3% (a small change is expected)."
    },
    {
      "analyte_id": "creatinine",
      "name": "Serum Creatinine",
      "unit": "mg/dL",
      "expected": {
        "direction": "rise",
        "note": "a small initial creatinine rise is expected after starting an SGLT2 inhibitor (the same change as the eGFR dip)",
        "source": "KDIGO 2024 CKD guideline, Practice Point 3.7.3: \"...the reversible decrease in eGFR on initiation is generally not an indication to discontinue therapy.\" See also Practice Point 2.1.4 (eGFR changes of more than 30% after starting hemodynamically active therapies). Trials: DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27).",
        "status": "verified",
        "applies": true
      },
      "window": {
        "start": "2024-05-13",
        "end": "2024-08-04"
      },
      "before": {
        "label": "mean before the event",
        "value": 1.29,
        "dates": [
          "2024-04-01"
        ],
        "observation_ids": [
          59
        ],
        "report_ids": [
          9
        ],
        "labs": [
          "ASTERLANE DIAGNOSTICS"
        ],
        "note": null
      },
      "before_values": [
        {
          "date": "2024-04-01",
          "value": 1.29,
          "observation_ids": [
            59
          ],
          "report_ids": [
            9
          ],
          "labs": [
            "ASTERLANE DIAGNOSTICS"
          ]
        }
      ],
      "before_note": "single prior value",
      "after": {
        "date": "2024-06-10",
        "value": 1.35,
        "observation_ids": [
          65
        ],
        "report_ids": [
          10
        ],
        "labs": [
          "Kestrelline Labs"
        ]
      },
      "change_abs": 0.06,
      "change_percent": 4.7,
      "rcv_percent": 15.0,
      "rcv_status": "unverified",
      "beyond_rcv": false,
      "cross_lab": true,
      "cross_lab_note": "values from different labs; between-lab variation is larger than the RCV assumes",
      "expected_effect": {
        "event_id": 3,
        "drug": "Empagliflozin",
        "drug_class": "sglt2i",
        "note": "a small initial creatinine rise is expected after starting an SGLT2 inhibitor (the same change as the eGFR dip)",
        "source": "KDIGO 2024 CKD guideline, Practice Point 3.7.3: \"...the reversible decrease in eGFR on initiation is generally not an indication to discontinue therapy.\" See also Practice Point 2.1.4 (eGFR changes of more than 30% after starting hemodynamically active therapies). Trials: DAPA-CKD (Heerspink et al., N Engl J Med 2020;383:1436-46); EMPA-KIDNEY (N Engl J Med 2023;388:117-27).",
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
      "status": "assessed",
      "target_direction": null,
      "verdict": "seen",
      "verdict_note": "Expected rise seen: Serum Creatinine rose 4.7% (a small change is expected)."
    }
  ]
}
```

## Body systems, documents, report pages and summaries (step 7)

### `GET /patients/{patient_id}/systems`: one card per body system

Every system in `data/analytes.yaml` (Kidney, Glucose control, Electrolytes, Lipids, Liver, Thyroid, Blood
count), in card order, computed from the same trends and flags as `/trends` and `/flags` (whole history):

- `status`: `guideline` (a guideline flag), `changed` (a change flag, with or without an expected drug
  effect), `stable` (results, no flag) or `no_data`.
- `headline`: the system's headline analyte (eGFR, HbA1c, potassium, LDL, ALT, TSH, haemoglobin) with its
  latest value (`report_id` is its source), `baseline`, `change_vs_baseline_percent` (the latest date's
  mean against the baseline, only after the baseline period; as `RCV_BASELINE` compares them) and `slope`.
  `latest` is null when the headline analyte has no result even if other analytes of the system do.
- `analytes_with_data` and `flag_counts` (`guideline`, `change`, `expected`, as in the patient list).

<!-- example: systems response 200 -->
```json
{
  "patient_id": 3,
  "systems": [
    {
      "id": "kidney",
      "name": "Kidney",
      "order": 1,
      "status": "guideline",
      "headline": {
        "analyte_id": "egfr",
        "name": "eGFR (CKD-EPI 2021)",
        "unit": "mL/min/1.73m²",
        "latest": {
          "date": "2026-03-02",
          "value": 54.06,
          "value_text": "54",
          "comparator": null,
          "censored": false,
          "report_id": 14
        },
        "baseline": 78.42,
        "change_vs_baseline_percent": -31.1,
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
        },
        "target": {
          "low": 60.0,
          "high": null,
          "label": "≥ 60",
          "source": "KDIGO 2024 CKD guideline, GFR categories: G1–G2 are eGFR ≥ 60 mL/min/1.73 m²; G3a–G5 are below 60",
          "status": "verified"
        },
        "target_direction": "away"
      },
      "analytes_with_data": [
        {
          "analyte_id": "creatinine",
          "name": "Serum Creatinine"
        },
        {
          "analyte_id": "egfr",
          "name": "eGFR (CKD-EPI 2021)"
        },
        {
          "analyte_id": "uacr",
          "name": "Urine Albumin/Creatinine Ratio"
        }
      ],
      "flag_counts": {
        "guideline": 1,
        "change": 2,
        "expected": 1
      }
    },
    {
      "id": "glucose",
      "name": "Glucose control",
      "order": 2,
      "status": "changed",
      "headline": {
        "analyte_id": "hba1c",
        "name": "HbA1c",
        "unit": "%",
        "latest": {
          "date": "2026-03-02",
          "value": 7.1,
          "value_text": "7.1",
          "comparator": null,
          "censored": false,
          "report_id": 14
        },
        "baseline": 8.8,
        "change_vs_baseline_percent": -19.3,
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
        },
        "target": {
          "low": null,
          "high": 7.0,
          "label": "< 7%",
          "source": "ADA Standards of Care in Diabetes 2025, section 6 (Glycemic Goals): HbA1c goal < 7% for many non-pregnant adults; goals are individualised",
          "status": "verified"
        },
        "target_direction": "toward"
      },
      "analytes_with_data": [
        {
          "analyte_id": "hba1c",
          "name": "HbA1c"
        },
        {
          "analyte_id": "fasting_glucose",
          "name": "Fasting Plasma Glucose"
        }
      ],
      "flag_counts": {
        "guideline": 0,
        "change": 1,
        "expected": 1
      }
    },
    {
      "id": "electrolytes",
      "name": "Electrolytes",
      "order": 3,
      "status": "stable",
      "headline": {
        "analyte_id": "potassium",
        "name": "Serum Potassium",
        "unit": "mmol/L",
        "latest": {
          "date": "2026-03-02",
          "value": 5.0,
          "value_text": "5.0",
          "comparator": null,
          "censored": false,
          "report_id": 14
        },
        "baseline": 4.5,
        "change_vs_baseline_percent": 11.1,
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
        },
        "target": {
          "low": 3.5,
          "high": 5.0,
          "label": "3.5–5.0 mmol/L",
          "source": "Usual adult reference interval; lab-specific",
          "status": "unverified"
        },
        "target_direction": "within"
      },
      "analytes_with_data": [
        {
          "analyte_id": "potassium",
          "name": "Serum Potassium"
        }
      ],
      "flag_counts": {
        "guideline": 0,
        "change": 0,
        "expected": 0
      }
    },
    {
      "id": "lipids",
      "name": "Lipids",
      "order": 4,
      "status": "no_data",
      "headline": {
        "analyte_id": "ldl",
        "name": "LDL Cholesterol",
        "unit": "mg/dL",
        "latest": null,
        "baseline": null,
        "change_vs_baseline_percent": null,
        "slope": null,
        "target": {
          "low": null,
          "high": 100.0,
          "label": "< 100 mg/dL",
          "source": "ADA Standards of Care 2025, section 10 (general LDL goal < 100 mg/dL; lower goals for higher risk)",
          "status": "unverified"
        },
        "target_direction": null
      },
      "analytes_with_data": [],
      "flag_counts": {
        "guideline": 0,
        "change": 0,
        "expected": 0
      }
    },
    {
      "id": "liver",
      "name": "Liver",
      "order": 5,
      "status": "no_data",
      "headline": {
        "analyte_id": "alt",
        "name": "ALT (SGPT)",
        "unit": "U/L",
        "latest": null,
        "baseline": null,
        "change_vs_baseline_percent": null,
        "slope": null,
        "target": null,
        "target_direction": null
      },
      "analytes_with_data": [],
      "flag_counts": {
        "guideline": 0,
        "change": 0,
        "expected": 0
      }
    },
    {
      "id": "thyroid",
      "name": "Thyroid",
      "order": 6,
      "status": "no_data",
      "headline": {
        "analyte_id": "tsh",
        "name": "TSH",
        "unit": "mIU/L",
        "latest": null,
        "baseline": null,
        "change_vs_baseline_percent": null,
        "slope": null,
        "target": {
          "low": 0.4,
          "high": 4.0,
          "label": "0.4–4.0 mIU/L",
          "source": "ATA 2014 hypothyroidism guideline (Jonklaas et al., Thyroid 2014;24:1670-1751): treatment aims for TSH within the reference range; range is lab-specific",
          "status": "unverified"
        },
        "target_direction": null
      },
      "analytes_with_data": [],
      "flag_counts": {
        "guideline": 0,
        "change": 0,
        "expected": 0
      }
    },
    {
      "id": "blood_count",
      "name": "Blood count",
      "order": 7,
      "status": "no_data",
      "headline": {
        "analyte_id": "haemoglobin",
        "name": "Haemoglobin",
        "unit": "g/dL",
        "latest": null,
        "baseline": null,
        "change_vs_baseline_percent": null,
        "slope": null,
        "target": null,
        "target_direction": null
      },
      "analytes_with_data": [],
      "flag_counts": {
        "guideline": 0,
        "change": 0,
        "expected": 0
      }
    }
  ]
}
```

### `POST /patients/{patient_id}/documents`: store a prescription or a doctor's note

Multipart form: `kind` (`prescription` or `doctor_note`), `file` (PDF, JPG or PNG, checked by content,
at most 15 MB), optional `document_date` (`YYYY-MM-DD`). The file is stored and never read. Lab reports
are uploaded with `POST /patients/{id}/reports` (which also keeps the PDF as a `lab_report` document);
`kind=lab_report` here answers `422`.

<!-- example: upload-document response 201 -->
```json
{
  "id": 5,
  "patient_id": 1,
  "kind": "prescription",
  "filename": "prescription.pdf",
  "sha256": "f782f61973da5ab8450e412fd5f0a47fb859c3e926a21b60431e930e70fc92aa",
  "size": 1880,
  "uploaded_at": "2026-09-28T06:04:36Z",
  "document_date": "2024-01-10",
  "report_id": null,
  "report_status": null
}
```

The same file again (for any of this doctor's patients):

<!-- example: document-duplicate response 409 -->
```json
{
  "detail": {
    "message": "this file was already uploaded",
    "document_id": 5,
    "patient_id": 1
  }
}
```

Not a PDF, JPG or PNG:

<!-- example: document-wrong-type response 415 -->
```json
{
  "detail": "only PDF, JPG and PNG files are accepted"
}
```

### `GET /patients/{patient_id}/documents`: the patient's documents, newest first

`report_id` and `report_status` (`extracted` or `confirmed`) are set for lab reports.

<!-- example: list-documents response 200 -->
```json
[
  {
    "id": 5,
    "patient_id": 1,
    "kind": "prescription",
    "filename": "prescription.pdf",
    "sha256": "f782f61973da5ab8450e412fd5f0a47fb859c3e926a21b60431e930e70fc92aa",
    "size": 1880,
    "uploaded_at": "2026-09-28T06:04:36Z",
    "document_date": "2024-01-10",
    "report_id": null,
    "report_status": null
  },
  {
    "id": 3,
    "patient_id": 1,
    "kind": "lab_report",
    "filename": "undated.pdf",
    "sha256": "3f078beb1ffbecefa803a427a5afc0c06affe5525a827aa2c3b8e381ecd742ac",
    "size": 2558,
    "uploaded_at": "2026-09-28T06:04:35Z",
    "document_date": null,
    "report_id": 3,
    "report_status": "extracted"
  },
  {
    "id": 2,
    "patient_id": 1,
    "kind": "lab_report",
    "filename": "demo_t2d_ckd_2.pdf",
    "sha256": "f9b2e876080ee27f54393719fd5f4d4f6b9ceceb8d858b1ef50d96219dfd04c9",
    "size": 2634,
    "uploaded_at": "2026-09-28T06:04:34Z",
    "document_date": "2024-04-11",
    "report_id": 2,
    "report_status": "confirmed"
  },
  {
    "id": 1,
    "patient_id": 1,
    "kind": "lab_report",
    "filename": "demo_t2d_ckd_1.pdf",
    "sha256": "a1eb3c683aa8154f14349153ea0d236dcf0bf86578b19829809591c7e0f45821",
    "size": 2633,
    "uploaded_at": "2026-09-28T06:04:33Z",
    "document_date": "2024-01-08",
    "report_id": 1,
    "report_status": "confirmed"
  }
]
```

### `GET /documents/{document_id}/file`: open a document

The stored file (`application/pdf`, `image/jpeg` or `image/png`), shown inline with its file name.

### `DELETE /documents/{document_id}`: delete a document

`204` and the file is removed. An unconfirmed lab report goes with its report and extracted values. A lab
report with confirmed values is part of the timeline and cannot be deleted:

<!-- example: delete-confirmed-report response 409 -->
```json
{
  "detail": {
    "message": "this lab report has confirmed values in the timeline and cannot be deleted",
    "report_id": 1
  }
}
```

### `GET /reports/{report_id}/pages/{page}.png`: a report page as an image

Page `page` (1-based) of the report's PDF rendered at 110 dpi (pixels = PDF points × 110/72), made once
and then served from a cache. Draw each observation's `bbox` (scaled by 110/72) on it to show the printed
row. A page outside the report, or a report whose PDF was not kept, answers `404`:

<!-- example: page-not-found response 404 -->
```json
{
  "detail": "page 99 not found (the report has 1)"
}
```

### `POST /patients/{patient_id}/summaries`: write a summary

`period`: `since_last_visit` (the second-latest confirmed report date to the latest; flags after the
previous visit), `all` (first to latest report) or `range` (with `from` and `to`, holding at least one
confirmed report). The LLM is given only facts computed by the trend engine: the patient's code, sex, age
and recorded conditions, report labels `R1`, `R2`, ... (numbered over the whole history, with dates and
labs), flags, trends, medication events and responses, and data notes. It never sees the name, a PDF or
any text printed on a report. Before saving, code checks the answer: every number must be in the facts,
every cited report must exist, every medication row must be a recorded event, and no advice, judgement,
diagnosis or causal wording is allowed. A rejected answer is retried once with the errors listed.

In `content`, `report_ids` are report ids; `reports` gives each one's `label` for the chips (`R7–R10`).
`basis` counts what the summary was written from. The examples below were written by a fixed test answer,
not a live model.

<!-- example: create-summary request -->
```json
{
  "period": "all"
}
```

<!-- example: create-summary response 201 -->
```json
{
  "id": 1,
  "patient_id": 3,
  "period": "all",
  "from": "2023-06-12",
  "to": "2026-03-02",
  "created_at": "2026-09-28T06:04:41Z",
  "model": "fake-llm",
  "facts_sha256": "593f870a9d35ff9774958a80835b13c68d65c7e3c6aa9696c36d3a1017a8c5f8",
  "content": {
    "key_finding": {
      "text": "eGFR fell by 7.1 mL/min/1.73 m² per year from October 2024 to March 2026 (63.9 to 54.1 over 4 results, 503 days), faster than the KDIGO 2012 threshold of 5 per year.",
      "report_ids": [
        11,
        12,
        13,
        14
      ]
    },
    "sections": [
      {
        "title": "Kidney",
        "sentences": [
          {
            "text": "eGFR is 31% below the baseline (78.4 to 54.1) and creatinine is 34% above it (1.11 to 1.49 mg/dL); the values come from different labs.",
            "report_ids": [
              5,
              6,
              7,
              14
            ]
          }
        ]
      },
      {
        "title": "Glucose control",
        "sentences": [
          {
            "text": "HbA1c fell from a baseline of 8.8% to 7.1%.",
            "report_ids": [
              5,
              6,
              14
            ]
          }
        ]
      }
    ],
    "medication_rows": [
      {
        "date": "2023-10-02",
        "drug": "Metformin",
        "dose": "500 mg BD",
        "observed": "HbA1c -15.9% (mean 8.8 to 7.4); expected fall"
      },
      {
        "date": "2024-03-04",
        "drug": "Ramipril",
        "dose": "2.5 mg OD",
        "observed": "Creatinine +15.5%, within the ≤30% rise expected after ACEi/ARB start"
      },
      {
        "date": "2024-05-06",
        "drug": "Empagliflozin",
        "dose": "10 mg OD",
        "observed": "eGFR fell after the start"
      }
    ],
    "data_notes": [
      "Reports come from 3 labs; between-lab variation is larger than the change thresholds assume.",
      "Adherence is not recorded."
    ],
    "reports": [
      {
        "report_id": 5,
        "label": "R1",
        "date": "2023-06-12",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 6,
        "label": "R2",
        "date": "2023-09-14",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 7,
        "label": "R3",
        "date": "2023-11-16",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 8,
        "label": "R4",
        "date": "2024-02-15",
        "lab": "Varnika Clinical Labs"
      },
      {
        "report_id": 9,
        "label": "R5",
        "date": "2024-04-01",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 10,
        "label": "R6",
        "date": "2024-06-10",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 11,
        "label": "R7",
        "date": "2024-10-15",
        "lab": "Varnika Clinical Labs"
      },
      {
        "report_id": 12,
        "label": "R8",
        "date": "2025-03-10",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 13,
        "label": "R9",
        "date": "2025-09-01",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 14,
        "label": "R10",
        "date": "2026-03-02",
        "lab": "ASTERLANE DIAGNOSTICS"
      }
    ],
    "basis": {
      "flags": 6,
      "medication_responses": 3,
      "reports": 10,
      "labs": 3
    }
  }
}
```

When the second answer also fails a check (or the model times out twice), nothing is saved and the
response is `502` with the last saved summary of the same period (or null), so the page can keep showing
it with its date. `503` has the same shape when the LLM is not configured.

<!-- example: summary-failed request -->
```json
{
  "period": "all"
}
```

<!-- example: summary-failed response 502 -->
```json
{
  "detail": "the summary could not be written after 2 attempts: key_finding: the number 9.4 is not in the facts (\"eGFR fell by 9.4 per year; consider a review.\"); key_finding: uses the word(s) 'consider' (\"eGFR fell by 9.4 per year; consider a review.\")",
  "last_saved": {
    "id": 1,
    "patient_id": 3,
    "period": "all",
    "from": "2023-06-12",
    "to": "2026-03-02",
    "created_at": "2026-09-28T06:04:41Z",
    "model": "fake-llm",
    "facts_sha256": "593f870a9d35ff9774958a80835b13c68d65c7e3c6aa9696c36d3a1017a8c5f8",
    "content": {
      "key_finding": {
        "text": "eGFR fell by 7.1 mL/min/1.73 m² per year from October 2024 to March 2026 (63.9 to 54.1 over 4 results, 503 days), faster than the KDIGO 2012 threshold of 5 per year.",
        "report_ids": [
          11,
          12,
          13,
          14
        ]
      },
      "sections": [
        {
          "title": "Kidney",
          "sentences": [
            {
              "text": "eGFR is 31% below the baseline (78.4 to 54.1) and creatinine is 34% above it (1.11 to 1.49 mg/dL); the values come from different labs.",
              "report_ids": [
                5,
                6,
                7,
                14
              ]
            }
          ]
        },
        {
          "title": "Glucose control",
          "sentences": [
            {
              "text": "HbA1c fell from a baseline of 8.8% to 7.1%.",
              "report_ids": [
                5,
                6,
                14
              ]
            }
          ]
        }
      ],
      "medication_rows": [
        {
          "date": "2023-10-02",
          "drug": "Metformin",
          "dose": "500 mg BD",
          "observed": "HbA1c -15.9% (mean 8.8 to 7.4); expected fall"
        },
        {
          "date": "2024-03-04",
          "drug": "Ramipril",
          "dose": "2.5 mg OD",
          "observed": "Creatinine +15.5%, within the ≤30% rise expected after ACEi/ARB start"
        },
        {
          "date": "2024-05-06",
          "drug": "Empagliflozin",
          "dose": "10 mg OD",
          "observed": "eGFR fell after the start"
        }
      ],
      "data_notes": [
        "Reports come from 3 labs; between-lab variation is larger than the change thresholds assume.",
        "Adherence is not recorded."
      ],
      "reports": [
        {
          "report_id": 5,
          "label": "R1",
          "date": "2023-06-12",
          "lab": "ASTERLANE DIAGNOSTICS"
        },
        {
          "report_id": 6,
          "label": "R2",
          "date": "2023-09-14",
          "lab": "Kestrelline Labs"
        },
        {
          "report_id": 7,
          "label": "R3",
          "date": "2023-11-16",
          "lab": "ASTERLANE DIAGNOSTICS"
        },
        {
          "report_id": 8,
          "label": "R4",
          "date": "2024-02-15",
          "lab": "Varnika Clinical Labs"
        },
        {
          "report_id": 9,
          "label": "R5",
          "date": "2024-04-01",
          "lab": "ASTERLANE DIAGNOSTICS"
        },
        {
          "report_id": 10,
          "label": "R6",
          "date": "2024-06-10",
          "lab": "Kestrelline Labs"
        },
        {
          "report_id": 11,
          "label": "R7",
          "date": "2024-10-15",
          "lab": "Varnika Clinical Labs"
        },
        {
          "report_id": 12,
          "label": "R8",
          "date": "2025-03-10",
          "lab": "ASTERLANE DIAGNOSTICS"
        },
        {
          "report_id": 13,
          "label": "R9",
          "date": "2025-09-01",
          "lab": "Kestrelline Labs"
        },
        {
          "report_id": 14,
          "label": "R10",
          "date": "2026-03-02",
          "lab": "ASTERLANE DIAGNOSTICS"
        }
      ],
      "basis": {
        "flags": 6,
        "medication_responses": 3,
        "reports": 10,
        "labs": 3
      }
    }
  }
}
```

A period without confirmed reports:

<!-- example: summary-bad-period request -->
```json
{
  "period": "range",
  "from": "2022-01-01",
  "to": "2022-12-31"
}
```

<!-- example: summary-bad-period response 422 -->
```json
{
  "detail": "there is no confirmed report in this range"
}
```

### `GET /patients/{patient_id}/summaries/latest`: the last saved summary

`?period=since_last_visit|range|all` (required). `404` when none was saved for that period.

<!-- example: latest-summary response 200 -->
```json
{
  "id": 1,
  "patient_id": 3,
  "period": "all",
  "from": "2023-06-12",
  "to": "2026-03-02",
  "created_at": "2026-09-28T06:04:41Z",
  "model": "fake-llm",
  "facts_sha256": "593f870a9d35ff9774958a80835b13c68d65c7e3c6aa9696c36d3a1017a8c5f8",
  "content": {
    "key_finding": {
      "text": "eGFR fell by 7.1 mL/min/1.73 m² per year from October 2024 to March 2026 (63.9 to 54.1 over 4 results, 503 days), faster than the KDIGO 2012 threshold of 5 per year.",
      "report_ids": [
        11,
        12,
        13,
        14
      ]
    },
    "sections": [
      {
        "title": "Kidney",
        "sentences": [
          {
            "text": "eGFR is 31% below the baseline (78.4 to 54.1) and creatinine is 34% above it (1.11 to 1.49 mg/dL); the values come from different labs.",
            "report_ids": [
              5,
              6,
              7,
              14
            ]
          }
        ]
      },
      {
        "title": "Glucose control",
        "sentences": [
          {
            "text": "HbA1c fell from a baseline of 8.8% to 7.1%.",
            "report_ids": [
              5,
              6,
              14
            ]
          }
        ]
      }
    ],
    "medication_rows": [
      {
        "date": "2023-10-02",
        "drug": "Metformin",
        "dose": "500 mg BD",
        "observed": "HbA1c -15.9% (mean 8.8 to 7.4); expected fall"
      },
      {
        "date": "2024-03-04",
        "drug": "Ramipril",
        "dose": "2.5 mg OD",
        "observed": "Creatinine +15.5%, within the ≤30% rise expected after ACEi/ARB start"
      },
      {
        "date": "2024-05-06",
        "drug": "Empagliflozin",
        "dose": "10 mg OD",
        "observed": "eGFR fell after the start"
      }
    ],
    "data_notes": [
      "Reports come from 3 labs; between-lab variation is larger than the change thresholds assume.",
      "Adherence is not recorded."
    ],
    "reports": [
      {
        "report_id": 5,
        "label": "R1",
        "date": "2023-06-12",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 6,
        "label": "R2",
        "date": "2023-09-14",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 7,
        "label": "R3",
        "date": "2023-11-16",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 8,
        "label": "R4",
        "date": "2024-02-15",
        "lab": "Varnika Clinical Labs"
      },
      {
        "report_id": 9,
        "label": "R5",
        "date": "2024-04-01",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 10,
        "label": "R6",
        "date": "2024-06-10",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 11,
        "label": "R7",
        "date": "2024-10-15",
        "lab": "Varnika Clinical Labs"
      },
      {
        "report_id": 12,
        "label": "R8",
        "date": "2025-03-10",
        "lab": "ASTERLANE DIAGNOSTICS"
      },
      {
        "report_id": 13,
        "label": "R9",
        "date": "2025-09-01",
        "lab": "Kestrelline Labs"
      },
      {
        "report_id": 14,
        "label": "R10",
        "date": "2026-03-02",
        "lab": "ASTERLANE DIAGNOSTICS"
      }
    ],
    "basis": {
      "flags": 6,
      "medication_responses": 3,
      "reports": 10,
      "labs": 3
    }
  }
}
```

## Targets, expected-vs-observed and changes of lab (step 9)

Fields added to existing responses (no new endpoints):

- `target` on each trend, flag and system headline: the analyte's guideline goal from `data/analytes.yaml`
  (`low` and/or `high`, `label` such as `"< 7%"`, `source`, `status`), or `null` when the analyte has none
  (creatinine, for example). It is context, like the reference range; flags still come from the baseline.
- `target_direction` on flags, system headlines and medication responses: `toward`, `away`, `within` or
  `unchanged`: whether the later value is closer to the target range than the earlier one. It describes
  position against a guideline goal, never whether a change is good; the UI shows it with an arrow and the
  target's label and source.
- `lab_change` on `RCV_PREV` flags whose two results come from different labs: `from_lab`, `to_lab`,
  `same_lab_agrees` (a result from the same lab on the other side of the step is within the reference change
  value of the earlier one: the change may reflect the labs rather than the patient), `same_lab_report_ids`
  and a `note` to show as is. `null` otherwise.
- `verdict` and `verdict_note` on each medication response entry (drug starts that were assessed):
  `seen` (the expected direction, beyond the reference change value, or any change that way for an effect the
  catalogue marks `size: small`), `not seen` (within the reference change value), `opposite` (the other way,
  beyond it), `above expected` (beyond the class's `max_expected_percent`). `null` when the entry was not
  assessed or the event is not a start.

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
