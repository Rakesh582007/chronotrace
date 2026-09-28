"""Step 4: read a lab-report PDF into results (test, value, unit, range, flag) with their page and line."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from shared.pdf_rows import extract_rows

from .assemble import Assembly, Line, Result, Skipped, assemble
from .metadata import ReportMeta, read_metadata
from .tagger import Tagger, get_tagger

__all__ = ["Extraction", "Result", "Skipped", "ReportMeta", "ScannedReportError", "extract_report", "get_tagger"]

SCANNED_MESSAGE = "scanned reports are not supported yet"


class ScannedReportError(ValueError):
    """The PDF has no text layer (an image scan)."""

    def __init__(self):
        super().__init__(SCANNED_MESSAGE)


@dataclass
class Extraction:
    results: list[Result]
    skipped: list[Skipped]
    meta: ReportMeta
    layout: str                  # "header" or "no header"
    header_text: str | None
    pages: int
    page_width: float | None = None      # first page, PDF points (the frame for Result.bbox)
    page_height: float | None = None


def read_lines(pdf_path) -> tuple[list[tuple[int, list[Line]]], dict[int, float]]:
    """Rows of every page (built by the same code that labelled the training data) and page heights."""
    pages, heights = [], {}
    for page_no, height, rows in extract_rows(pdf_path):
        pages.append((page_no, [Line(page_no, i, row, ["O"] * len(row)) for i, row in enumerate(rows, 1)]))
        heights[page_no] = height
    return pages, heights


def row_bbox(words: list[dict]) -> list[float]:
    """[x0, top, x1, bottom] around a row's words, in PDF points from the page's top left (1 decimal)."""
    return [round(min(w["x0"] for w in words), 1), round(min(w["top"] for w in words), 1),
            round(max(w["x1"] for w in words), 1), round(max(w["bottom"] for w in words), 1)]


def page_size(pdf_path) -> tuple[float, float] | tuple[None, None]:
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return None, None
        return round(float(pdf.pages[0].width), 1), round(float(pdf.pages[0].height), 1)


def extract_report(pdf_path: str | Path, tagger: Tagger | None = None) -> Extraction:
    pages, heights = read_lines(pdf_path)
    n_words = sum(len(ln.words) for _, lines in pages for ln in lines)
    if n_words < 5:
        raise ScannedReportError()

    tagger = tagger or get_tagger()
    all_lines = [ln for _, lines in pages for ln in lines]
    for ln, tags in zip(all_lines, tagger.tag([[w["text"] for w in ln.words] for ln in all_lines])):
        ln.tags = tags

    asm: Assembly = assemble(pages, heights)
    rows = {(ln.page, ln.line): ln for ln in all_lines}
    for r in asm.results:
        if (r.page, r.line) in rows and rows[(r.page, r.line)].words:
            r.bbox = row_bbox(rows[(r.page, r.line)].words)
    width, height = page_size(pdf_path)
    header_rows = [ln.text for ln in all_lines if ln.page == 1 and (1, ln.line) in asm.page_header_lines]
    meta = read_metadata(header_rows, [ln.text for ln in all_lines])
    return Extraction(asm.results, asm.skipped, meta, asm.layout, asm.header_text, len(pages), width, height)
