# Decision log

Each entry records what was decided and why, so anyone on the team can answer a judge's "why did you do it this way?"

| # | Decision | Why |
| --- | --- | --- |
| 1 | Any chronic condition, tagged per patient (replaces the oncology-only ONCOTRACK pitch) | Cancer response is judged on imaging (RECIST), which a lab-report pipeline cannot read |
| 2 | Flag change from the patient's own baseline; printed reference range is context only | Chronic patients are always out of range, so range-based flags become noise |
| 3 | A change counts only if it exceeds the reference change value (e.g. ~14% for creatinine) | Smaller changes are within normal lab and biological variation |
| 4 | Trained model is used for extraction only (DistilBERT, row-level NER) | Learning helps with messy report layouts; clinical judgement needs verifiable rules |
| 5 | Training data is generated synthetically with automatic labels; real reports are the test set only | Synthetic data is valid for learning layouts, and a real-report test set keeps the accuracy number honest |
| 6 | Trend math is done in code; the LLM only summarises computed flags | LLMs are unreliable at reasoning over long patient histories |
| 7 | "Drug effectiveness per body type" dropped; replaced by "response after medication change" with no score | Regression to the mean, unknown adherence and confounding by indication make a score misleading; "body type" is not a validated drug-response variable |
| 8 | Stack: FastAPI, SQLite, React + Vite + Recharts, pdfplumber/EasyOCR, pandas/scipy, hosted LLM | Fits a 24-hour build on one RTX 3050 laptop, with an 8 GB laptop as backup demo machine |
| 9 | Patient age for eGFR is report year minus birth year (`Patient` stores only `birth_year`) | Asking for a full birth date adds friction and identifying data. The age can be up to 1 year too high before the birthday; at 0.9938 per year in CKD-EPI 2021 that moves eGFR by about 0.6%, well inside its 15.4% reference change value |
| 10 | Trends and flags are computed on every request, not stored | They can never go stale after an edit, a newly confirmed report or a deleted medication; the whole history of one patient is small |
| 11 | The slope skips results up to the end of the last expected-effect window of a drug that affects the analyte | The planned eGFR dip after starting an ACEi/ARB or SGLT2 inhibitor would otherwise read as progression (demo patient: naive slope -9.8/yr, true post-start slope -7.1/yr) |
