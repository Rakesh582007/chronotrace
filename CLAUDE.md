# ChronoTrace – working rules for Claude

ChronoTrace is a doctor-facing tool for BME Ignite Hackfest 2026 (Track II, BME x AI). It merges chronic patients' lab reports from different labs into one time series, flags changes from the patient's own baseline, and shows lab response after medication changes. See `README.md` for the pipeline and `docs/decisions.md` for why each design choice was made.

## Workflow: confirm each step

- Work follows the 10 steps in `README.md`, one at a time.
- For each step: propose the plan, wait for the user's confirmation, build, show the result, then wait for confirmation again before pushing.
- Never push, merge or delete a branch without an explicit "push" / "merge" from the user.
- When a step is merged, tick it in the README status list.

## Git rules

- Author: `Rakesh582007 <gdrakesh2018@gmail.com>` (set in repo config). Credit Claude with a `Co-Authored-By` trailer only.
- Commit messages use Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`. One logical change per commit.
- One branch per step (`step-1-analytes`, `step-2-generator`, ...), merged into `main` through a pull request. `main` must always run.
- Small repo-housekeeping changes (docs, config) may go straight to `main` after confirmation.
- Before pushing from a shallow clone, fetch `origin main` and rebase if needed.

## Never commit

- `.env` or any API key or token
- Real patient reports (they live in git-ignored `data/real_reports/`)
- Generated datasets (`ml/generated/`) or model weights (published to the Hugging Face Hub instead)
- `venv/`, `node_modules/`, local databases

## Design guardrails (from `docs/decisions.md`)

- Trend math is computed in code (baseline, reference change value, slope). The LLM only writes summaries from computed flags and never decides thresholds.
- The trained model is used for report extraction only.
- No drug "effectiveness score" and no dose recommendations. Show observed lab change after a medication event, for the clinician to interpret.
- Every flag must link to its source report and the rule that fired.
- Demo and training data are synthetic.

## Hardware constraints

- Main machine: RTX 3050 (6 GB VRAM), 16 GB RAM, Windows 11. Training must fit: fp16, small batches, short sequences.
- Backup demo machine: 8 GB RAM, no GPU. The app, including model inference on CPU, must run there.
- Optional: remote workstation (2x RTX 3090) via remote desktop for training only.

## Stack

FastAPI + SQLite (SQLModel) · React + Vite + Tailwind + Recharts · pdfplumber, EasyOCR · Hugging Face Transformers (DistilBERT) · pandas, scipy · hosted LLM API for summaries.
