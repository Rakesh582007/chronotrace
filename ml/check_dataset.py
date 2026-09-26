"""Check a generated dataset before training.

Usage:  python ml/check_dataset.py [--dir ml/generated] [--min-rows 300]

Hard checks (exit 1 if any fails):
  - tags well-formed (one per token, valid BIO)
  - rows per analyte >= --min-rows
  - every synonym and every unit in data/analytes.yaml used at least once
  - every reference-range format used at least once
  - labelled rows match a fresh pdfplumber read of the PDFs (100%)
  - tagged fields match what was drawn, and printed values convert to canonical_value
  - held-out layout families appear only in the test split; no report in two splits
  - no real lab brand names anywhere in the extracted text
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # ml/, so "generator" imports

from generator import dictionary as d  # noqa: E402
from generator import values as v  # noqa: E402
from generator.brands import find_brands  # noqa: E402
from generator.labeler import ENTITY_KINDS, bio_ok, entity_text, extract_rows  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parent / "generated"


def load(dir_: Path) -> tuple[list[dict], dict]:
    with open(dir_ / "labels.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    manifest = json.loads((dir_ / "manifest.json").read_text(encoding="utf-8"))
    return rows, manifest


def _reextract(args: tuple[str, str]) -> tuple[str, list[list[str]]]:
    rid, path = args
    return rid, [[w["text"] for w in row] for _, _, rows in extract_rows(path) for row in rows]


def run_checks(dir_: Path, min_rows: int = 300, workers: int = 1) -> tuple[list[tuple[str, bool, str]], dict]:
    """Return ([(check name, passed, detail)], report dict with the counts behind them)."""
    rows, manifest = load(dir_)
    analytes = d.analytes()
    results: list[tuple[str, bool, str]] = []
    info: dict = {}

    def check(name: str, ok: bool, detail: str):
        results.append((name, bool(ok), detail))

    # 1. Tag format
    bad_tags = [r for r in rows if len(r["tokens"]) != len(r["tags"]) or not bio_ok(r["tags"])]
    check("tags well-formed", not bad_tags, f"{len(rows) - len(bad_tags)}/{len(rows)} rows")

    test_rows = [r for r in rows if r["analyte_id"]]
    info["rows_total"] = len(rows)
    info["test_rows"] = len(test_rows)

    # 2. Rows per analyte
    per_analyte = Counter(r["analyte_id"] for r in test_rows)
    info["rows_per_analyte"] = {a: per_analyte.get(a, 0) for a in analytes}
    low = {a: n for a, n in info["rows_per_analyte"].items() if n < min_rows}
    check(f"rows per analyte >= {min_rows}", not low,
          f"min {min(info['rows_per_analyte'].values())} ({min(info['rows_per_analyte'], key=info['rows_per_analyte'].get)})"
          + (f"; below: {low}" if low else ""))

    # 3. Synonym and unit coverage (all splits), plus what training never sees
    used_syn, used_unit = defaultdict(Counter), defaultdict(Counter)
    train_syn, train_unit = defaultdict(set), defaultdict(set)
    for r in test_rows:
        t = r["truth"]
        used_syn[r["analyte_id"]][t["synonym"]] += 1
        used_unit[r["analyte_id"]][t["unit_key"]] += 1
        if r["split"] == "train":
            train_syn[r["analyte_id"]].add(t["synonym"])
            train_unit[r["analyte_id"]].add(t["unit_key"])
    missing_syn, missing_unit, not_in_train = [], [], []
    n_syn = n_unit = 0
    for aid, a in analytes.items():
        for s in list(a["synonyms"]) + d.basis_synonyms(a):
            n_syn += 1
            if not used_syn[aid][s]:
                missing_syn.append(f"{aid}:{s}")
            elif s not in train_syn[aid]:
                not_in_train.append(f"{aid}:{s}")
        for c in a["conversions"]:
            n_unit += 1
            if not used_unit[aid][c["unit"]]:
                missing_unit.append(f"{aid}:{c['unit']}")
            elif c["unit"] not in train_unit[aid]:
                not_in_train.append(f"{aid}:{c['unit']}")
    check("every synonym used", not missing_syn,
          f"{n_syn - len(missing_syn)}/{n_syn}" + (f"; missing {missing_syn}" if missing_syn else ""))
    check("every unit used", not missing_unit,
          f"{n_unit - len(missing_unit)}/{n_unit}" + (f"; missing {missing_unit}" if missing_unit else ""))
    info["not_in_train"] = not_in_train

    # 4. Reference-range formats
    formats = Counter(r["truth"]["range_format"] for r in test_rows)
    info["range_formats"] = dict(formats.most_common())
    missing_fmt = [f for f in v.RANGE_FORMATS if not formats[f]]
    check("every range format used", not missing_fmt,
          ", ".join(f"{k}={n}" for k, n in formats.most_common()))

    # 5. Labelled tokens == a fresh pdfplumber read
    by_report: dict[str, list[list[str]]] = defaultdict(list)
    for r in rows:
        by_report[r["report_id"]].append(r["tokens"])
    tasks = [(rid, str(dir_ / "pdfs" / f"{rid}.pdf")) for rid in by_report]
    if workers > 1:
        with Pool(workers) as pool:
            fresh = dict(pool.imap_unordered(_reextract, tasks, chunksize=8))
    else:
        fresh = dict(map(_reextract, tasks))
    matched = sum(
        sum(1 for a, b in zip(by_report[rid], fresh[rid]) if a == b)
        for rid in by_report if len(by_report[rid]) == len(fresh[rid])
    )
    pct = 100.0 * matched / len(rows) if rows else 0.0
    check("labelled rows match pdfplumber text", matched == len(rows), f"{pct:.2f}% ({matched}/{len(rows)} rows)")

    # 6. Tagged fields spell what was drawn; values convert back to canonical_value
    field_bad, value_bad, flag_bad = [], [], []
    for r in test_rows:
        t = r["truth"]
        a = analytes[r["analyte_id"]]
        for kind, key in zip(ENTITY_KINDS, ("test", "value", "unit", "range", "flag")):
            if entity_text(r["tokens"], r["tags"], kind) != t[key]:
                field_bad.append((r["report_id"], r["page"], r["row"], kind))
        got = d.to_canonical(a, v.parse_number(t["value"]), t["unit_key"], t["basis"])
        if abs(got - r["canonical_value"]) > 1e-6 * max(1.0, abs(got)):
            value_bad.append((r["report_id"], r["analyte_id"]))
        expected = v.flag_for(a, r["canonical_value"], t["sex"])  # "H", "L" or ""
        printed = {"H": "H", "High": "H", "*H": "H", "L": "L", "Low": "L", "*L": "L", "": ""}[t["flag"]]
        if t["abnormal"] != bool(expected) or (t["flag_column"] and printed != expected):
            flag_bad.append((r["report_id"], r["analyte_id"]))
    check("tagged fields match drawn text", not field_bad,
          f"{len(test_rows) * 5 - len(field_bad)}/{len(test_rows) * 5} fields" + (f"; e.g. {field_bad[:3]}" if field_bad else ""))
    check("values convert to canonical_value", not value_bad,
          f"{len(test_rows) - len(value_bad)}/{len(test_rows)} values")
    check("H/L flags match value and range", not flag_bad,
          f"{len(test_rows) - len(flag_bad)}/{len(test_rows)} rows")
    abnormal = sum(1 for r in test_rows if r["truth"]["abnormal"])
    info["abnormal_share"] = abnormal / len(test_rows) if test_rows else 0.0

    # 7. Splits
    split_of: dict[str, set] = defaultdict(set)
    fam_split: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        split_of[r["report_id"]].add(r["split"])
        fam_split[r["split"]][r["layout_family"]] += 1
    multi = [rid for rid, s in split_of.items() if len(s) > 1]
    held = set(manifest["test_families"])
    leak = set(fam_split["train"]) & held or set(fam_split["val"]) & held
    only_held = set(fam_split["test"]) <= held
    reports = Counter(next(iter(s)) for s in split_of.values())
    info["reports_per_split"] = dict(reports)
    info["rows_per_split"] = dict(Counter(r["split"] for r in rows))
    non_test = reports["train"] + reports["val"]
    val_share = reports["val"] / non_test if non_test else 0.0
    check("held-out families only in test", not leak and only_held and not multi,
          f"test families {sorted(held)}; val = {val_share:.1%} of train+val")

    # 8. Real lab brands
    text_by_report: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        text_by_report[r["report_id"]].append(" ".join(r["tokens"]))
    hits = {rid: sorted(set(find_brands(" ".join(lines)))) for rid, lines in text_by_report.items()}
    hits = {k: h for k, h in hits.items() if h}
    check("no real lab brand names", not hits,
          f"scanned {len(text_by_report)} reports" + (f"; hits {dict(list(hits.items())[:5])}" if hits else ""))

    info["pages"] = manifest.get("pages")
    info["test_families"] = manifest["test_families"]
    info["layout_rows"] = dict(Counter(r["layout_family"] for r in rows))
    return results, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a generated dataset.")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--min-rows", type=int, default=300)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args(argv)

    results, info = run_checks(args.dir, args.min_rows, args.workers)

    print(f"Dataset: {args.dir}")
    print(f"  rows: {info['rows_total']}  (test rows: {info['test_rows']}, "
          f"abnormal share: {info['abnormal_share']:.1%})")
    print(f"  pages per report: {info['pages']}")
    print(f"  reports per split: {info['reports_per_split']}   rows per split: {info['rows_per_split']}")
    print(f"  held-out test families: {', '.join(info['test_families'])}")
    print("  rows per analyte:")
    items = list(info["rows_per_analyte"].items())
    for i in range(0, len(items), 4):
        print("    " + "   ".join(f"{a:<18}{n:>4}" for a, n in items[i:i + 4]))
    if info["not_in_train"]:
        print(f"  note: used, but only outside train: {', '.join(info['not_in_train'])}")
    print()
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'OK' if not failed else 'FAILED'}: {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
