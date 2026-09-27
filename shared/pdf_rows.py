"""Read a PDF's text layer into rows of words.

The generator labels training rows with this code (ml/generator/labeler.py) and the backend
builds inference rows with it (backend/extraction), so the model sees the same row
boundaries and word splits at inference as in training. Change it in one place only.
"""

from __future__ import annotations

import pdfplumber

WORD_SETTINGS = dict(x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=False)
ROW_TOLERANCE = 3.0


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
    """[(page number, page height, rows)] for every page. Each word has text, x0, x1, top, bottom."""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            out.append((n, float(page.height), group_rows(page.extract_words(**WORD_SETTINGS))))
    return out
