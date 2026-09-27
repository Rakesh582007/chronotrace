"""Compare the trained NER model with the rule baseline on val (seen layouts) and test (held-out).

The baseline is reported as "rules (generator vocabulary)": it knows every test name, unit and
method string the synthetic generator uses, so on synthetic data it is an upper bound, not a
realistic competitor. The real comparison is on real reports (step 9).

Usage:  python ml/evaluate_ner.py [--model ml/models/chronotrace-ner] [--out ml/results/step3_metrics.json]

For each system and split:
  - seqeval entity precision / recall / F1 per type and overall (micro), strict IOB2
  - exact value accuracy: test rows whose extracted VALUE text equals the printed value exactly
  - row accuracy: rows whose tags are all correct
  - per layout family: FLAG recall and overall F1
CPU latency of the model: a child process with CUDA hidden (CUDA_VISIBLE_DEVICES=-1) and 4 threads tags 500 test rows
one at a time (tokenize + forward + decode) and reports mean ms/row.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ML = Path(__file__).resolve().parent
DEFAULT_MODEL = ML / "models" / "chronotrace-ner"
DEFAULT_OUT = ML / "results" / "step3_metrics.json"
KINDS = ("TEST", "VALUE", "UNIT", "RANGE", "FLAG")
LATENCY_ROWS = 500
CPU_THREADS = 4
CPU_TARGET_MS = 25.0
SYSTEMS = {
    "model": "DistilBERT NER (this model)",
    "rules": "rules (generator vocabulary): baseline_rules.py, which knows every test name, unit and "
             "method string the synthetic generator uses; an upper bound on synthetic data",
}
NOTES = [
    "All data is synthetic. The rules baseline knows the generator's full vocabulary, so it is an upper "
    "bound on synthetic data; the real model-vs-rules comparison is on real reports (step 9).",
    "The flag-position fix (commit 3649ebe) was prompted by error analysis on the held-out test families "
    "(flag_emphasis, inline_unit), so the post-fix test score is not fully blind. Hyperparameters were not "
    "changed. Pre-fix numbers are kept under before_flag_fix.",
    "After the flag fix, the first retrain kept epoch 1 because val entity F1 tied at 1.0000 in all "
    "epochs. That checkpoint's test results were printed once before checkpoint selection was changed "
    "(commit 9be245a: ties broken by lower val loss). The selection change was prompted by the val tie, "
    "not by those test numbers, and they are not reported here.",
]


def cpu_latency(model_dir: Path, labels: Path, n_rows: int) -> dict:
    """Run in a child process with CUDA_VISIBLE_DEVICES=-1 (see main)."""
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    import ner_data as nd

    assert not torch.cuda.is_available()
    torch.set_num_threads(CPU_THREADS)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForTokenClassification.from_pretrained(model_dir).eval()
    rows = nd.load_rows(labels, "test")[:n_rows]
    cpu = torch.device("cpu")
    for r in rows[:20]:   # warm-up
        nd.predict(model, tokenizer, [r], cpu, batch_size=1)
    times = []
    for r in rows:
        t0 = time.perf_counter()
        nd.predict(model, tokenizer, [r], cpu, batch_size=1)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {"rows": len(rows), "threads": CPU_THREADS, "batch_size": 1,
            "mean_ms_per_row": round(statistics.mean(times), 2),
            "p50_ms": round(times[len(times) // 2], 2), "p95_ms": round(times[int(len(times) * 0.95)], 2),
            "target_ms": CPU_TARGET_MS, "meets_target": statistics.mean(times) < CPU_TARGET_MS}


def score(rows: list[dict], pred: list[list[str]]) -> dict:
    from seqeval.metrics import classification_report
    from seqeval.scheme import IOB2

    from generator.labeler import entity_text

    gold = [r["tags"] for r in rows]
    rep = classification_report(gold, pred, mode="strict", scheme=IOB2, output_dict=True, zero_division=0)
    out = {k: {"precision": round(rep[k]["precision"], 5), "recall": round(rep[k]["recall"], 5),
               "f1": round(rep[k]["f1-score"], 5), "support": int(rep[k]["support"])}
           for k in KINDS if k in rep}
    m = rep["micro avg"]
    out["overall"] = {"precision": round(m["precision"], 5), "recall": round(m["recall"], 5),
                      "f1": round(m["f1-score"], 5), "support": int(m["support"])}
    value_rows = [(r, p) for r, p in zip(rows, pred) if r["truth"]]
    exact = sum(entity_text(r["tokens"], p, "VALUE") == r["truth"]["value"] for r, p in value_rows)
    out["exact_value_accuracy"] = round(exact / len(value_rows), 5)
    out["exact_value_rows"] = f"{exact}/{len(value_rows)}"
    out["row_accuracy"] = round(sum(g == p for g, p in zip(gold, pred)) / len(rows), 5)
    out["rows"] = len(rows)
    return out


def by_family(rows: list[dict], pred: list[list[str]]) -> dict:
    out = {}
    for fam in sorted({r["layout_family"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["layout_family"] == fam]
        sc = score([rows[i] for i in idx], [pred[i] for i in idx])
        flag = sc.get("FLAG", {"recall": None, "support": 0})
        out[fam] = {"rows": len(idx), "overall_f1": sc["overall"]["f1"],
                    "flag_recall": flag["recall"], "flag_support": flag["support"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the NER model against the rule baseline.")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--labels", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cpu-latency-only", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    import ner_data as nd

    labels = args.labels or nd.DEFAULT_LABELS
    if args.cpu_latency_only:
        print(json.dumps(cpu_latency(args.model, labels, LATENCY_ROWS)))
        return 0

    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    import baseline_rules

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForTokenClassification.from_pretrained(args.model).to(device)

    metrics: dict = {"model_dir": args.model.name, "scheme": "seqeval strict IOB2, micro average",
                     "systems": SYSTEMS, "notes": NOTES}
    preds: dict = {}
    for split in ("val", "test"):
        rows = nd.load_rows(labels, split)
        preds[split] = {"model": nd.predict(model, tokenizer, rows, device),
                        "rules": [baseline_rules.tag_row(r["tokens"]) for r in rows]}
        metrics[split] = {s: score(rows, p) for s, p in preds[split].items()}
        metrics[split]["by_family"] = {s: by_family(rows, p) for s, p in preds[split].items()}
        metrics[split]["layout_families"] = sorted({r["layout_family"] for r in rows})

    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1"}   # "" is unset on Windows
    child = subprocess.run([sys.executable, __file__, "--cpu-latency-only", "--model", str(args.model),
                            "--labels", str(labels)], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=True)
    metrics["cpu_latency"] = json.loads(child.stdout.strip().splitlines()[-1])

    log_path = args.model / "training_log.json"
    if log_path.exists():
        metrics["training"] = json.loads(log_path.read_text(encoding="utf-8"))
    if args.out.exists():   # keep the pre-fix record across re-runs
        previous = json.loads(args.out.read_text(encoding="utf-8"))
        if "before_flag_fix" in previous:
            metrics["before_flag_fix"] = previous["before_flag_fix"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    # ---- table
    print("rules = rules (generator vocabulary): knows every name/unit the generator uses, "
          "so an upper bound on synthetic data")
    print(f"{'entity F1':<22}{'val model':>11}{'val rules':>11}{'test model':>12}{'test rules':>12}")
    for k in (*KINDS, "overall"):
        cells = [metrics[s][sys_][k]["f1"] for s in ("val", "test") for sys_ in ("model", "rules")]
        print(f"{k:<22}" + "".join(f"{c:>11.4f}" if i < 2 else f"{c:>12.4f}" for i, c in enumerate(cells)))
    for key, label in (("exact_value_accuracy", "exact value accuracy"), ("row_accuracy", "row accuracy")):
        cells = [metrics[s][sys_][key] for s in ("val", "test") for sys_ in ("model", "rules")]
        print(f"{label:<22}" + "".join(f"{c:>11.4f}" if i < 2 else f"{c:>12.4f}" for i, c in enumerate(cells)))
    print(f"(val = seen layouts, {metrics['val']['model']['rows']} rows; test = held-out "
          f"{', '.join(metrics['test']['layout_families'])}, {metrics['test']['model']['rows']} rows)")
    print("\nHeld-out family      FLAG recall model / rules   overall F1 model / rules")
    for fam, m in metrics["test"]["by_family"]["model"].items():
        r = metrics["test"]["by_family"]["rules"][fam]
        print(f"  {fam:<18} {m['flag_recall']:.4f} / {r['flag_recall']:.4f} ({m['flag_support']} flags)"
              f"   {m['overall_f1']:.4f} / {r['overall_f1']:.4f}")
    lat = metrics["cpu_latency"]
    print(f"\nCPU latency ({lat['threads']} threads, batch 1, {lat['rows']} test rows): mean {lat['mean_ms_per_row']} ms/row, "
          f"p50 {lat['p50_ms']}, p95 {lat['p95_ms']}  (target < {lat['target_ms']:.0f} ms: "
          f"{'met' if lat['meets_target'] else 'NOT met'})")

    test_rows = nd.load_rows(labels, "test")
    wrong = [(r, p) for r, p in zip(test_rows, preds["test"]["model"]) if p != r["tags"]]
    print(f"\nTest rows where the model is wrong: {len(wrong)}" + ("" if wrong else " (none)"))
    per_report: dict[str, int] = {}
    shown = []
    for r, p in wrong:   # at most 2 rows per report, so the sample is not all one report
        if per_report.get(r["report_id"], 0) < 2 and len(shown) < 10:
            per_report[r["report_id"]] = per_report.get(r["report_id"], 0) + 1
            shown.append((r, p))
    for r, p in shown:
        print(f"  {r['report_id']} ({r['layout_family']})")
        print("    " + "  ".join(f"{t}[{g}{'' if g == q else ' -> ' + q}]" for t, g, q in zip(r["tokens"], r["tags"], p)))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
