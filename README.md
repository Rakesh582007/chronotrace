# ChronoTrace

Longitudinal lab-report analysis for chronic disease patients. ChronoTrace merges a patient's reports from different labs into one time series, flags changes from the patient's own baseline that exceed normal lab variation, and shows how lab values responded after each medication change.

Built for BME Ignite Hackfest 2026, Track II (BME x AI). Decision support only: every flag shows its source report and the rule behind it, and all clinical decisions stay with the doctor.

## How it works

1. **Extract** – a fine-tuned DistilBERT model labels each report row as test, value, unit and reference range. The doctor confirms extracted values.
2. **Normalise** – tests are mapped to a shared dictionary (LOINC codes) and units are converted, so reports from different labs line up.
3. **Analyse** – rules and statistics, not AI: personal baseline, change beyond reference change value, slope over 3+ reports, optional condition packs with guideline thresholds.
4. **Medication response** – drug start, stop and dose changes are marked on each lab chart with the before/after change. No effectiveness score.
5. **Summarise** – an LLM writes plain-language summaries from the computed flags only.

## Repository layout

| Folder | Contents |
| --- | --- |
| `backend/` | FastAPI app, database, normalisation, trend engine |
| `ml/` | Synthetic report generator, training notebook, evaluation |
| `shared/` | PDF row reading and model tag decoding used by both `ml/` and `backend/` |
| `frontend/` | React + Vite + Recharts doctor interface |
| `data/` | Analyte dictionary and condition packs (small config files only) |
| `docs/` | Architecture and decision log |

## Data policy

- Demo and training data are synthetic. No real patient data is stored in this repository.
- Real reports used for the test set stay local in `data/real_reports/`, which is git-ignored.
- Trained model weights are published to the Hugging Face Hub, not committed here.

## Setup

Setup instructions will be added as each component lands. Copy `.env.example` to `.env` and fill in your keys; never commit `.env`.

## Training

The extraction model is DistilBERT fine-tuned on synthetic reports (step 3). Install torch first,
then the ML requirements:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128   # GPU (CUDA 12.8)
pip install torch --index-url https://download.pytorch.org/whl/cpu     # or CPU only
pip install -r requirements.txt -r requirements-ml.txt
```

Then generate the data, check it, train, and evaluate against the rule baseline:

```bash
python ml/generator/generate_reports.py --n 1000 --seed 42   # -> ml/generated/ (git-ignored)
python ml/check_dataset.py                                   # must pass 16/16
python ml/train_ner.py                                       # -> ml/models/chronotrace-ner/ (git-ignored)
python ml/evaluate_ner.py                                    # -> ml/results/step3_metrics.json
python ml/push_to_hub.py                                     # optional: upload with model card (needs HF_TOKEN in .env)
```

Training takes about 4 minutes on an RTX 3050 (6 GB, 1.6 GB peak VRAM). Results: [`ml/results/step3_metrics.json`](ml/results/step3_metrics.json).

## Backend (extraction, normalisation, API)

```bash
pip install -r requirements.txt -r requirements-ml.txt       # plus torch (see Training)
python -m backend.demo.seed --reset                          # four synthetic demo patients, through the API
uvicorn backend.main:app --reload                            # http://127.0.0.1:8000, docs at /docs
```

The API is documented for the frontend in [`docs/api.md`](docs/api.md) (checked against the running
API by `tests/test_api_contract.py`). Every endpoint except sign-in needs the demo doctor's token; CORS
allows `http://localhost:5173` only. `--reset` rebuilds the demo database and empties the uploads folder
(needed after a schema change: the API refuses to start on an outdated database).

Required in `.env` (see `.env.example`): `DEMO_DOCTOR_NAME`, `DEMO_DOCTOR_USER`, `DEMO_DOCTOR_PASSWORD`,
`AUTH_SECRET` (at least 32 characters) for the demo login, and `LLM_PROVIDER=gemini`, `LLM_API_KEY`,
`LLM_MODEL` for summaries. Optional environment variables:

| Variable | Default |
| --- | --- |
| `CHRONOTRACE_MODEL` | `ml/models/chronotrace-ner` if present, else the Hub model `Rip-Shadw/chronotrace-report-ner` |
| `CHRONOTRACE_DB` | `sqlite:///backend/chronotrace.db` (git-ignored) |
| `CHRONOTRACE_UPLOADS` | `backend/uploads/` (git-ignored): report PDFs, prescriptions, notes, photos, page images |

How a report is read: pdfplumber rows (the same code that built the training data, `shared/pdf_rows.py`)
are tagged by the model; the table's column-header line then decides which rows are results (a
model-tagged value in the value column) and which are continuation lines (method, specimen, extra
range lines). Test names are matched to `data/analytes.yaml`, values converted to canonical units, and
eGFR recomputed from creatinine. Nothing is dropped silently: every line with a value is a result, a
continuation, or listed as skipped with the reason. Scanned PDFs (no text layer) are not supported yet.

End-to-end check on the held-out synthetic reports (and a table for any PDF in the git-ignored
`data/real_reports/`):

```bash
python ml/evaluate_pipeline.py --real --pages 3-5              # -> ml/results/step45_pipeline.json
python tests/fixtures/make_fixtures.py                         # rebuild the test-fixture PDFs
```

## Status

- [x] Step 1 – Analyte dictionary
- [x] Step 2 – Synthetic report generator
- [x] Step 3 – Model training
- [x] Step 4 – Extraction pipeline
- [x] Step 5 – Database and normalisation
- [x] Step 6 – Trend engine and medication response
- [ ] Step 7 – LLM summaries
- [ ] Step 8 – Frontend
- [ ] Step 9 – Demo patient and real-report evaluation
- [ ] Step 10 – Pitch and demo checklist
