"""Read a rendered PDF back with pdfplumber and tag every word BIO-style.

Tags come from the Fragments recorded while drawing: each word pdfplumber extracts is
matched to the fragment whose box contains it. A report is only accepted when every word
matches exactly one fragment and each fragment's words spell its text exactly.

Rows come from shared.pdf_rows, which the backend also uses at inference time.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root, for the "shared" package
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pdf_rows import ROW_TOLERANCE, WORD_SETTINGS, extract_rows, group_rows  # noqa: E402,F401

from .layouts import Fragment, TestRow  # noqa: E402

ENTITY_KINDS = ("TEST", "VALUE", "UNIT", "RANGE", "FLAG")
TAGS = ["O"] + [f"{p}-{k}" for k in ENTITY_KINDS for p in ("B", "I")]


def _match(word: dict, frags: list[Fragment], page_h: float) -> Fragment | None:
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    best, best_dy = None, None
    for f in frags:
        if not (f.x0 - 0.5 <= cx <= f.x1 + 0.5):
            continue
        dy = abs(cy - (page_h - f.baseline - 0.3 * f.size))
        if dy <= 0.45 * f.size and (best_dy is None or dy < best_dy):
            best, best_dy = f, dy
    return best


def label_pdf(pdf_path, fragments: list[Fragment], rows: dict[int, TestRow]) -> tuple[list[dict], dict]:
    """Return (row records, stats). Stats count words and any alignment problems."""
    by_page: dict[int, list[Fragment]] = defaultdict(list)
    for f in fragments:
        by_page[f.page].append(f)

    records: list[dict] = []
    stats = {"words": 0, "unmatched_words": 0, "fragment_mismatches": 0, "mixed_rows": 0}
    frag_words: dict[int, list[str]] = defaultdict(list)

    for page_no, page_h, page_rows in extract_rows(pdf_path):
        frags = by_page.get(page_no, [])
        for row_index, words in enumerate(page_rows):
            tokens, tags, row_ids = [], [], set()
            seen_in_row: set[int] = set()
            for w in words:
                stats["words"] += 1
                f = _match(w, frags, page_h)
                tokens.append(w["text"])
                if f is None:
                    stats["unmatched_words"] += 1
                    tags.append("O")
                    continue
                frag_words[id(f)].append(w["text"])
                if f.kind == "O":
                    tags.append("O")
                else:
                    tags.append(("I-" if id(f) in seen_in_row else "B-") + f.kind)
                    row_ids.add(f.row_id)
                seen_in_row.add(id(f))
            if len(row_ids) > 1:
                stats["mixed_rows"] += 1
            row = rows.get(next(iter(row_ids))) if len(row_ids) == 1 else None
            records.append({
                "page": page_no,
                "row": row_index,
                "tokens": tokens,
                "tags": tags,
                "analyte_id": row.analyte_id if row else None,
                "canonical_value": row.canonical_value if row else None,
                "truth": row.truth() if row else None,
            })

    for f in fragments:
        if frag_words.get(id(f), []) != f.text.split():
            stats["fragment_mismatches"] += 1
    return records, stats


def entity_text(tokens: list[str], tags: list[str], kind: str) -> str:
    """Join the tokens tagged B-/I-kind (used by checks and tests)."""
    return " ".join(t for t, g in zip(tokens, tags) if g.endswith("-" + kind))


def bio_ok(tags: list[str]) -> bool:
    """I-X must follow B-X or I-X."""
    prev = "O"
    for t in tags:
        if t not in TAGS:
            return False
        if t.startswith("I-") and prev[2:] != t[2:]:
            return False
        prev = t
    return True
