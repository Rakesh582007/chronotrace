"""Table columns from the report's column-header line.

Lab reports print a header such as "Investigation | Observed Value | Flag | Units | Biological
Reference Interval" above the results. Its word positions tell which column every later word
belongs to, which is what separates a real result row from a line where pdfplumber merged a
left-hand note ("Method :HEXOKINASE") with a right-hand range continuation ("100 - 125 mg/dl").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("test", "value", "unit", "range", "flag", "method")

# Header words, lowercased with punctuation removed. Covers the synthetic generator's label sets
# and common Indian report headers.
KEYWORDS: dict[str, set[str]] = {
    "test": {"test", "tests", "investigation", "investigations", "parameter", "parameters", "description",
             "examination", "name", "analyte"},
    "value": {"result", "results", "value", "values", "observed", "observation", "reading"},
    "unit": {"unit", "units", "units(s)", "unit(s)", "uom"},
    "range": {"reference", "ref", "range", "ranges", "interval", "intervals", "normal", "biological", "bio"},
    "flag": {"flag", "flags", "hl", "h/l", "status", "remark", "remarks", "abnormal"},
    "method": {"method", "methods", "technique", "methodology"},
}
_WORD = re.compile(r"[^a-z/()]+")


def keyword_kind(text: str) -> str | None:
    w = _WORD.sub("", text.lower())
    w_plain = w.replace("(", "").replace(")", "")
    for kind, words in KEYWORDS.items():
        if w in words or w_plain in words:
            return kind
    return None


@dataclass
class Cell:
    kind: str | None
    x0: float
    x1: float
    text: str


@dataclass
class Columns:
    cells: list[Cell]                # left to right
    bounds: list[float]              # bounds[i] = left edge of cells[i] (bounds[0] = -inf)
    header_text: str

    def column_at(self, x: float) -> str | None:
        kind = None
        for cell, left in zip(self.cells, self.bounds):
            if x >= left:
                kind = cell.kind
        return kind

    def column_of(self, word: dict) -> str | None:
        """Column containing the word's centre."""
        return self.column_at((word["x0"] + word["x1"]) / 2)

    def column_of_start(self, word: dict) -> str | None:
        """Column containing the word's first character."""
        return self.column_at(word["x0"] + 1)

    def has(self, kind: str) -> bool:
        return any(c.kind == kind for c in self.cells)

    def header_x0(self, kind: str) -> float | None:
        """Where the header text of a column starts."""
        for cell in self.cells:
            if cell.kind == kind:
                return cell.x0
        return None

    def left_edge(self, kind: str) -> float | None:
        for cell, left in zip(self.cells, self.bounds):
            if cell.kind == kind:
                return left
        return None


def header_columns(words: list[dict]) -> Columns | None:
    """Columns if this row is a table header (needs a test column and a value column), else None."""
    if not words or any(ch.isdigit() for w in words for ch in w["text"]):
        return None
    cells: list[Cell] = []
    for w in words:
        kind = keyword_kind(w["text"])
        cur = cells[-1] if cells else None
        if cur is not None and (kind is None or cur.kind in (None, kind)) and w["x0"] - cur.x1 < 40:
            cur.kind = cur.kind or kind
            cur.x1 = max(cur.x1, w["x1"])
            cur.text += " " + w["text"]
        else:
            cells.append(Cell(kind, w["x0"], w["x1"], w["text"]))
    kinds = [c.kind for c in cells]
    if "test" not in kinds or "value" not in kinds or kinds.count("test") > 1 or len(cells) < 2:
        return None
    if kinds[0] != "test":
        return None
    # Header cells are separated by column gaps; a prose line ("Test results relate only to ...")
    # has single spaces between its words.
    if len(words) > 14 or any(b.x0 - a.x1 < 8 for a, b in zip(cells, cells[1:])) or cells[1].x0 - cells[0].x1 < 15:
        return None
    bounds = [float("-inf")]
    for a, b in zip(cells, cells[1:]):
        # Closer to the next header's start: values are often centred or right-aligned under a
        # header that starts to their left, and long test names can reach towards the value column.
        bounds.append(a.x1 + 0.6 * max(0.0, b.x0 - a.x1))
    return Columns(cells, bounds, " ".join(w["text"] for w in words))
