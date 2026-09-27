"""Upload the trained NER model to the Hugging Face Hub with a model card.

Usage:  python ml/push_to_hub.py [--repo Rakesh582007/chronotrace-report-ner] [--private]

Reads HF_TOKEN from .env at the repo root (or the environment). The model card's numbers
come from ml/results/step3_metrics.json, so run evaluate_ner.py first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "ml" / "models" / "chronotrace-ner"
METRICS = ROOT / "ml" / "results" / "step3_metrics.json"
DEFAULT_REPO = "Rakesh582007/chronotrace-report-ner"


def read_token() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "HF_TOKEN" and value.strip():
                return value.strip().strip('"').strip("'")
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        sys.exit("HF_TOKEN not found in .env or the environment")
    return token


def model_card(m: dict, repo: str) -> str:
    kinds = ("TEST", "VALUE", "UNIT", "RANGE", "FLAG", "overall")
    rows = "\n".join(
        f"| {k} | {m['val']['model'][k]['f1']:.4f} | {m['val']['rules'][k]['f1']:.4f} "
        f"| {m['test']['model'][k]['f1']:.4f} | {m['test']['rules'][k]['f1']:.4f} |" for k in kinds)
    ev = f"| exact value accuracy | " + " | ".join(
        f"{m[s][x]['exact_value_accuracy']:.4f}" for s in ("val", "test") for x in ("model", "rules")) + " |"
    fam = "\n".join(
        f"| {f} | {r['flag_recall']:.4f} | {m['test']['by_family']['rules'][f]['flag_recall']:.4f} "
        f"| {m['before_flag_fix']['flag_recall_by_test_family'][f]['model']:.4f} |"
        for f, r in m["test"]["by_family"]["model"].items())
    b = m["before_flag_fix"]["test"]
    t, lat = m["training"], m["cpu_latency"]
    hp = t["hyperparameters"]
    return f"""---
language: en
license: apache-2.0
library_name: transformers
pipeline_tag: token-classification
base_model: distilbert-base-uncased
tags: [token-classification, lab-reports, synthetic-data]
---

# ChronoTrace report-row NER

Tags each printed row of a lab report word by word: test name (`TEST`), result (`VALUE`),
unit (`UNIT`), reference range (`RANGE`) and H/L flag (`FLAG`), as BIO tags. It is the
extraction step of ChronoTrace, a doctor-facing tool that puts a chronic patient's lab results
from different labs into one time series.

## Important limits

- **Trained on synthetic reports only.** No real patient data was used. All metrics below are
  on synthetic reports.
- **Real-report accuracy is not yet measured.** It is pending evaluation on real reports
  (ChronoTrace step 9). Do not assume the synthetic numbers carry over.
- **Extraction only.** It reads what is printed. It does not interpret results, decide what is
  abnormal, or recommend anything; trend flags in ChronoTrace are computed by separate code.
- **Not a medical device.** Not for diagnosis or treatment decisions. Extracted values must be
  checked against the source report.

## Data

Rows come from synthetic Indian-style lab reports rendered to PDF and read back with pdfplumber
(ChronoTrace step 2): {t['train_rows']:,} train rows and {t['val_rows']:,} validation rows from 8 layout families.
The test set ({m['test']['model']['rows']:,} rows) uses 2 layout families never seen in training:
{', '.join(m['test']['layout_families'])}.

## Results (synthetic data)

Entity F1 (seqeval, strict IOB2). "Rules" is `rules (generator vocabulary)`: a hand-written
tagger that knows every test name, unit and method string the synthetic generator uses. On
synthetic data it is therefore an **upper bound**, not a realistic competitor. The comparison
that matters is on real reports, which will contain names and units outside that vocabulary
(ChronoTrace step 9, pending).

| | val model | val rules | held-out test model | held-out test rules |
|---|---|---|---|---|
{rows}
{ev}

FLAG recall on the held-out families:

| family | model | rules | model before flag fix |
|---|---|---|---|
{fam}

**The held-out score is not fully blind.** A first model (same hyperparameters) was trained
on data where each layout family printed flags in one fixed position. Error analysis on the
held-out families showed it missed flags printed right after the value or unit. The generator
was then changed to vary flag position in every family, and the model was retrained with
unchanged hyperparameters (twice; see checkpoint selection below). Before that fix, held-out test overall F1 was
{b['model']['overall']['f1']:.4f} and FLAG F1 {b['model']['FLAG']['f1']:.4f} (rules: {b['rules']['overall']['f1']:.4f}).
All numbers are in `step3_metrics.json` in the ChronoTrace repository, the pre-fix ones under
`before_flag_fix`.

**Checkpoint selection was also changed after test results had been printed.** The first
retrain after the flag fix tied at val entity F1 1.0000 in every epoch, so the "higher F1 only"
rule kept epoch 1, and that checkpoint's held-out test results were printed once. Selection
was then changed to break F1 ties by lower validation loss, and the model was retrained with the
same hyperparameters and seed. The change was prompted by the validation tie, not by the test
numbers, but it came after they had been seen, so the reported test score is not fully blind on
this point either.

CPU latency: {lat['mean_ms_per_row']} ms per row (mean over {lat['rows']} rows, batch 1, {lat['threads']} threads,
on a laptop CPU; it varies with machine load).

## Training

`{hp['base_model']}`, {hp['epochs']} epochs, lr {hp['lr']}, batch {hp['batch_size']}, max length
{hp['max_length']} sub-tokens, weight decay {hp['weight_decay']}, fp16, seed {hp['seed']}. Best epoch
({t['best_epoch']}) chosen on validation entity F1. Trained on {t['device']} in {t['train_seconds']:.0f} s.

## Use

```python
from transformers import AutoTokenizer, AutoModelForTokenClassification
tok = AutoTokenizer.from_pretrained("{repo}")
model = AutoModelForTokenClassification.from_pretrained("{repo}")
words = ["Serum", "Creatinine", "1.11", "mg/dL", "0.7", "-", "1.3"]
enc = tok(words, is_split_into_words=True, return_tensors="pt")
pred = model(**enc).logits.argmax(-1)[0]
# each word's tag is the prediction at its first sub-token (enc.word_ids())
```
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Upload the NER model to the Hugging Face Hub.")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args(argv)

    from huggingface_hub import HfApi

    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    (MODEL_DIR / "README.md").write_text(model_card(metrics, args.repo), encoding="utf-8")
    api = HfApi(token=read_token())
    api.create_repo(args.repo, repo_type="model", private=args.private, exist_ok=True)
    api.upload_folder(repo_id=args.repo, folder_path=str(MODEL_DIR), repo_type="model",
                      commit_message="Upload ChronoTrace report-row NER (step 3)")
    print(f"Uploaded {MODEL_DIR} to https://huggingface.co/{args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
