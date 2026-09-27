"""Step 4: read a lab-report PDF into results (test, value, unit, range, flag) with their page and line."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def read_lines(pdf_path) -> tuple[list[tuple[int, list[Line]]], dict[int, float]]:
    """Rows of every page (built by the same code that labelled the training data) and page heights."""
    pages, heights = [], {}
    for page_no, height, rows in extract_rows(pdf_path):
        pages.append((page_no, [Line(page_no, i, row, ["O"] * len(row)) for i, row in enumerate(rows, 1)]))
        heights[page_no] = height
    return pages, heights


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
    header_rows = [ln.text for ln in all_lines if ln.page == 1 and (1, ln.line) in asm.page_header_lines]
    meta = read_metadata(header_rows, [ln.text for ln in all_lines])
    return Extraction(asm.results, asm.skipped, meta, asm.layout, asm.header_text, len(pages))
