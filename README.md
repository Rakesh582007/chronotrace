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
| `frontend/` | React + Vite + Recharts doctor interface |
| `data/` | Analyte dictionary and condition packs (small config files only) |
| `docs/` | Architecture and decision log |

## Data policy

- Demo and training data are synthetic. No real patient data is stored in this repository.
- Real reports used for the test set stay local in `data/real_reports/`, which is git-ignored.
- Trained model weights are published to the Hugging Face Hub, not committed here.

## Setup

Setup instructions will be added as each component lands. Copy `.env.example` to `.env` and fill in your keys; never commit `.env`.

## Status

- [x] Step 1 – Analyte dictionary
- [ ] Step 2 – Synthetic report generator
- [ ] Step 3 – Model training
- [ ] Step 4 – Extraction pipeline
- [ ] Step 5 – Database and normalisation
- [ ] Step 6 – Trend engine and medication response
- [ ] Step 7 – LLM summaries
- [ ] Step 8 – Frontend
- [ ] Step 9 – Demo patient and real-report evaluation
- [ ] Step 10 – Pitch and demo checklist
