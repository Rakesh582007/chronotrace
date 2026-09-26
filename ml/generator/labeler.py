"""Read a rendered PDF back with pdfplumber and tag every word BIO-style.

Tags come from the Fragments recorded while drawing: each word pdfplumber extracts is
matched to the fragment whose box contains it. A report is only accepted when every word
matches exactly one fragment and each fragment's words spell its text exactly.

The same WORD_SETTINGS and row grouping must be used at inference time (step 4).
"""

from __future__ import annotations

from collections import defaultdict

import pdfplumber

from .layouts import Fragment, TestRow

WORD_SETTINGS = dict(x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=False)
ROW_TOLERANCE = 3.0
ENTITY_KINDS = ("TEST", "VALUE", "UNIT", "RANGE", "FLAG")
TAGS = ["O"] + [f"{p}-{k}" for k in ENTITY_KINDS for p in ("B", "I")]


def group_rows(words: list[dict], tol: float = ROW_TOLERANCE) -> list[list[dict]]:
    """Group words whose top edges are within `tol` points into rows, left to right."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def extract_rows(pdf_path) -> list[tuple[int, float, list[list[dict]]]]:
    """[(page number, page height, rows)] for every page."""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            out.append((n, float(page.height), group_rows(page.extract_words(**WORD_SETTINGS))))
    return out


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
