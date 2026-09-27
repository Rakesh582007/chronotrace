"""End-to-end check of extraction + normalisation (steps 4-5) on the held-out synthetic reports.

Usage:
  python ml/evaluate_pipeline.py                  # the test split (held-out layout families)
  python ml/evaluate_pipeline.py --real           # also print the table for PDFs in data/real_reports/

For every dictionary test printed on a report, the pipeline must produce an observation on the same
page and line with the right analyte AND the right canonical value (eGFR: within 1 of the printed
value, since it is recomputed from creatinine). Failures are grouped by cause. Report dates and lab
names are checked against the generator's own values (rebuilt from its seed).

Writes ml/results/step45_pipeline.json (synthetic results only; nothing from real reports).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ML = Path(__file__).resolve().parent
ROOT = ML.parent
sys.path.insert(0, str(ML))
sys.path.insert(0, str(ROOT))

from backend import normalise as nm  # noqa: E402
from backend.extraction import extract_report  # noqa: E402
from backend.extraction.tagger import get_tagger  # noqa: E402
from generator import generate_reports as gen  # noqa: E402
from generator import layouts  # noqa: E402

GENERATED = ML / "generated"
OUT = ML / "results" / "step45_pipeline.json"
TARGET = 0.98


def truth_meta(seed: int, report_id: str, family: str):
    """The collected date and lab name the generator used for this report."""
    import random
    index = int(report_id[1:])
    rng = random.Random(f"{seed}:{index}")
    fake = gen._faker()
    fake.seed_instance(rng.getrandbits(32))
    report = layouts.build_content(rng, fake, layouts.FAMILIES_BY_NAME[family], report_id)
    return report.people["collected"].date(), report.lab["name"]


def close(a: float, b: float, analyte: str) -> bool:
    if analyte == "egfr":
        return abs(a - b) <= 1.0
    return abs(a - b) <= 1e-6 * max(1.0, abs(b))


def failure_cause(t: dict, o, ex, asm_lines: dict) -> str:
    key = (t["page"], t["line"])
    if o is None:
        skipped = next((s for s in ex.skipped if (s.page, s.line) == key), None)
        if skipped:
            return f"skipped: {skipped.reason}"
        if key in asm_lines["continuation"]:
            return "attached to the result above as a continuation line"
        return "not a result (no value tagged in the value column)"
    if o.analyte_id is None:
        return "name matches two analytes" if o.status == nm.NEEDS_REVIEW else f"name not matched ({o.test_text!r})"
    if o.analyte_id != t["analyte_id"]:
        return f"wrong analyte ({o.analyte_id} for {t['analyte_id']})"
    if o.status == nm.NEEDS_REVIEW:
        return f"needs review: {o.status_reason.split(' for ')[0]}"
    if o.value_text != t["value"]:
        return "value text differs from what was printed"
    if o.unit_text != t["unit"]:
        return "unit text differs from what was printed"
    return "canonical value differs"


def evaluate_synthetic(tagger) -> dict:
    rows = [json.loads(line) for line in open(GENERATED / "labels.jsonl", encoding="utf-8")]
    manifest = json.loads((GENERATED / "manifest.json").read_text(encoding="utf-8"))
    test = [r for r in rows if r["split"] == "test"]
    by_report: dict[str, list[dict]] = defaultdict(list)
    for r in test:
        by_report[r["report_id"]].append(r)

    n_truth = n_ok = 0
    causes: Counter = Counter()
    examples: list[dict] = []
    spurious: list[dict] = []
    date_ok = lab_ok = 0
    labels: Counter = Counter()
    layouts_seen: Counter = Counter()
    for i, (rid, rrows) in enumerate(sorted(by_report.items()), 1):
        truth = [{"page": r["page"], "line": r["row"] + 1, "analyte_id": r["analyte_id"],
                  "canonical": r["canonical_value"], "value": r["truth"]["value"], "unit": r["truth"]["unit"],
                  "test": r["truth"]["test"]} for r in rrows if r["analyte_id"]]
        any_truth = next(r["truth"] for r in rrows if r["truth"])
        true_date, true_lab = truth_meta(manifest["seed"], rid, rrows[0]["layout_family"])
        patient = nm.Patient(any_truth["sex"], true_date.year - any_truth["age"])

        ex = extract_report(GENERATED / "pdfs" / f"{rid}.pdf", tagger)
        observations, _ = nm.normalise(ex.results, patient, ex.meta.date)
        at = {(o.page, o.line): o for o in observations}
        cont = {(r.page, n) for r in ex.results for n in r.continuation_lines}
        date_ok += ex.meta.date == true_date
        lab_ok += ex.meta.lab == true_lab
        labels[ex.meta.date_label] += 1
        layouts_seen[ex.layout] += 1

        truth_keys = {(t["page"], t["line"]) for t in truth}
        for t in truth:
            n_truth += 1
            o = at.get((t["page"], t["line"]))
            if o is not None and o.analyte_id == t["analyte_id"] and o.canonical_value is not None \
                    and close(o.canonical_value, t["canonical"], t["analyte_id"]):
                n_ok += 1
                continue
            cause = failure_cause(t, o, ex, {"continuation": cont})
            causes[cause] += 1
            if len(examples) < 25:
                examples.append({"report": rid, "page": t["page"], "line": t["line"], "printed": t["test"],
                                 "value": t["value"], "unit": t["unit"], "cause": cause,
                                 "got": None if o is None else {"test": o.test_text, "value": o.value_text,
                                                                "unit": o.unit_text, "analyte": o.analyte_id,
                                                                "canonical": o.canonical_value}})
        for o in observations:
            if o.analyte_id and (o.page, o.line) not in truth_keys:
                spurious.append({"report": rid, "page": o.page, "line": o.line, "test": o.test_text,
                                 "analyte": o.analyte_id})
        if i % 50 == 0:
            print(f"  {i}/{len(by_report)} reports", flush=True)

    n = len(by_report)
    return {
        "reports": n, "layout_families": manifest["test_families"],
        "dictionary_tests": n_truth, "correct": n_ok, "accuracy": round(n_ok / n_truth, 5), "target": TARGET,
        "failures_by_cause": dict(causes.most_common()), "failure_examples": examples,
        "spurious_tracked_results": {"count": len(spurious), "examples": spurious[:10]},
        "collected_date_correct": f"{date_ok}/{n}", "date_labels": dict(labels), "lab_name_correct": f"{lab_ok}/{n}",
        "layouts": dict(layouts_seen), "model": getattr(tagger, "source", "?"),
    }


def print_real(tagger, pages: set[int] | None) -> None:
    for pdf in sorted((ROOT / "data" / "real_reports").glob("*.pdf")):
        ex = extract_report(pdf, tagger)
        obs, not_results = nm.normalise(ex.results, nm.Patient("female", 1980), ex.meta.date)
        print(f"\n== {pdf.name}: {ex.pages} pages, layout {ex.layout}, date {ex.meta.date} ({ex.meta.date_label}), "
              f"lab {'found' if ex.meta.lab else 'not found'}")
        print(f"  {'pg':<3}{'ln':<4}{'test':<28}{'value':<8}{'unit':<14}{'range':<24}{'analyte':<18}{'status':<13}reason")
        for o in obs:
            if pages and o.page not in pages:
                continue
            print(f"  {o.page:<3}{o.line:<4}{o.test_text[:27]:<28}{o.value_text[:7]:<8}{o.unit_text[:13]:<14}"
                  f"{o.range_text[:23]:<24}{str(o.analyte_id):<18}{o.status:<13}{o.status_reason}")
        skipped = [(s.page, s.line, s.text, s.reason) for s in ex.skipped] + list(not_results)
        for page, line, text, reason in sorted(skipped):
            if pages and page not in pages:
                continue
            header = reason.startswith(("page header", "repeated"))
            print(f"  skipped p{page} l{line}: {'[page header row]' if header else text!r}: {reason}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="End-to-end check of extraction + normalisation.")
    ap.add_argument("--real", action="store_true", help="also print tables for data/real_reports/*.pdf")
    ap.add_argument("--pages", default="", help="with --real: only these pages, e.g. 3-5")
    args = ap.parse_args(argv)

    tagger = get_tagger()
    res = evaluate_synthetic(tagger)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")

    print(f"\nHeld-out synthetic reports: {res['reports']} ({', '.join(res['layout_families'])})")
    print(f"Dictionary tests with correct analyte AND canonical value: {res['correct']}/{res['dictionary_tests']} "
          f"= {res['accuracy']:.2%}  (target >= {TARGET:.0%}: {'met' if res['accuracy'] >= TARGET else 'NOT met'})")
    print("Failures by cause:" + ("" if res["failures_by_cause"] else " none"))
    for cause, n in res["failures_by_cause"].items():
        print(f"  {n:>4}  {cause}")
    print(f"Spurious tracked results (tracked analyte where none was printed): {res['spurious_tracked_results']['count']}")
    print(f"Collected date correct: {res['collected_date_correct']}  labels: {res['date_labels']}")
    print(f"Lab name correct: {res['lab_name_correct']}   layouts: {res['layouts']}")
    for e in res["failure_examples"][:10]:
        print(f"  e.g. {e['report']} p{e['page']} l{e['line']} {e['printed']!r} {e['value']} {e['unit']}: {e['cause']}"
              f"  got {e['got']}")
    print(f"Wrote {OUT}")

    if args.real:
        pages = None
        if args.pages:
            lo, _, hi = args.pages.partition("-")
            pages = set(range(int(lo), int(hi or lo) + 1))
        if not list((ROOT / "data" / "real_reports").glob("*.pdf")):
            print("\nNo PDFs in data/real_reports/.")
        print_real(tagger, pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
