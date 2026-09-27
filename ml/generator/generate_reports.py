"""Generate synthetic lab-report PDFs and row-level BIO labels.

Usage:
    python ml/generator/generate_reports.py --n 1000 --seed 42

Writes to ml/generated/ (git-ignored):
    pdfs/rNNNNN.pdf   rendered reports
    labels.jsonl      one pdfplumber row per line, with tokens and BIO tags
    manifest.json     seed, families, held-out test families, split and page counts
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # ml/, so "generator" imports

from faker import Faker  # noqa: E402

from generator import layouts  # noqa: E402
from generator.labeler import label_pdf  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "generated"
VAL_FRACTION = 0.10
N_TEST_FAMILIES = 2

_fake: Faker | None = None


def _faker() -> Faker:
    global _fake
    if _fake is None:
        _fake = Faker("en_IN")
    return _fake


def family_for(index: int) -> str:
    """Round-robin so every family gets the same number of reports."""
    return layouts.FAMILY_NAMES[index % len(layouts.FAMILY_NAMES)]


def choose_test_families(seed: int) -> list[str]:
    return sorted(random.Random(f"{seed}:test-families").sample(layouts.FAMILY_NAMES, N_TEST_FAMILIES))


def assign_splits(n: int, seed: int, test_families: list[str]) -> dict[str, str]:
    """Held-out families -> test; the rest shuffled with the seed and split 90/10."""
    ids = [f"r{i:05d}" for i in range(n)]
    split = {rid: "test" for i, rid in enumerate(ids) if family_for(i) in test_families}
    rest = [rid for rid in ids if rid not in split]
    random.Random(f"{seed}:split").shuffle(rest)
    n_val = round(len(rest) * VAL_FRACTION)
    split.update({rid: "val" for rid in rest[:n_val]})
    split.update({rid: "train" for rid in rest[n_val:]})
    return split


def make_report(task: tuple[int, int, str]) -> dict:
    """Generate, render and label one report. Deterministic in (seed, index)."""
    index, seed, out_dir = task
    rid = f"r{index:05d}"
    rng = random.Random(f"{seed}:{index}")
    fake = _faker()
    fake.seed_instance(rng.getrandbits(32))
    family = layouts.FAMILIES_BY_NAME[family_for(index)]

    report = layouts.build_content(rng, fake, family, rid)
    style = layouts.resolve_style(rng, family)
    path = Path(out_dir) / "pdfs" / f"{rid}.pdf"
    report, style, fragments, pages = layouts.render_capped(report, style, path)
    for row in report.rows():
        row.flag_column = "flag" in style.columns
    records, stats = label_pdf(path, fragments, {r.row_id: r for r in report.rows()})
    return {"report_id": rid, "family": family.name, "pages": pages, "records": records, "stats": stats,
            "lab": report.lab["name"]}


def generate(n: int, seed: int, out_dir: Path, workers: int, test_families: list[str] | None = None,
             quiet: bool = False) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    for old in (out_dir / "pdfs").glob("r*.pdf"):
        old.unlink()

    test_families = sorted(test_families or choose_test_families(seed))
    unknown = set(test_families) - set(layouts.FAMILY_NAMES)
    if unknown:
        raise ValueError(f"unknown layout families: {sorted(unknown)}")
    splits = assign_splits(n, seed, test_families)

    tasks = [(i, seed, str(out_dir)) for i in range(n)]
    totals: Counter = Counter()
    pages: Counter = Counter()
    rows_per_split: Counter = Counter()
    reports_per_split: Counter = Counter()

    def results():
        if workers <= 1:
            yield from map(make_report, tasks)
        else:
            with Pool(workers, initializer=layouts.register_fonts) as pool:
                yield from pool.imap(make_report, tasks, chunksize=4)

    with open(out_dir / "labels.jsonl", "w", encoding="utf-8") as f:
        for done, res in enumerate(results(), 1):
            split = splits[res["report_id"]]
            reports_per_split[split] += 1
            pages[res["pages"]] += 1
            totals.update(res["stats"])
            for rec in res["records"]:
                row = {"report_id": res["report_id"], "layout_family": res["family"], "split": split, **rec}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows_per_split[split] += 1
            if not quiet and (done % 100 == 0 or done == n):
                print(f"  {done}/{n} reports", flush=True)

    manifest = {
        "n_reports": n,
        "seed": seed,
        "layout_families": layouts.FAMILY_NAMES,
        "test_families": test_families,
        "val_fraction": VAL_FRACTION,
        "reports_per_split": dict(sorted(reports_per_split.items())),
        "rows_per_split": dict(sorted(rows_per_split.items())),
        "pages": {str(k): pages[k] for k in sorted(pages)},
        "alignment": dict(totals),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=1000, help="number of reports")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--test-families", default=None,
                    help="comma-separated layout families to hold out (default: 2 picked by seed)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    test_families = args.test_families.split(",") if args.test_families else None
    m = generate(args.n, args.seed, args.out, args.workers, test_families, args.quiet)
    a = m["alignment"]
    print(f"Wrote {m['n_reports']} reports to {args.out}")
    print(f"  held-out test families: {', '.join(m['test_families'])}")
    print(f"  reports per split: {m['reports_per_split']}   rows per split: {m['rows_per_split']}")
    print(f"  pages: {m['pages']}")
    print(f"  words: {a.get('words', 0)}  unmatched: {a.get('unmatched_words', 0)}  "
          f"fragment mismatches: {a.get('fragment_mismatches', 0)}  mixed rows: {a.get('mixed_rows', 0)}")
    bad = a.get("unmatched_words", 0) + a.get("fragment_mismatches", 0) + a.get("mixed_rows", 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
