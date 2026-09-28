"""Turn tagged PDF rows into results, continuation lines and skipped lines.

Input: pages of rows (shared.pdf_rows) with a BIO tag per word from the NER model.

With a column header (the usual case) a row is a result only if
  - its first word starts in the test-name column, and
  - a word the model tagged VALUE sits in the value column, in its own cell.
Every other row after a result on the same page is a continuation of that result: its
range-column words extend the result's reference range, everything else becomes a note
("Method :HEXOKINASE", "Specimen: SERUM", accreditation codes). Continuations stop at a large
vertical gap, unless the row is still in the range column (long interpretive ranges).

Without a header the model's tags decide alone (TEST + VALUE = result) and the report is marked
layout "no header".

Rows above the column header, and rows repeated identically on several pages, are the page
header/footer (patient block, lab address) and never become results. Every row that has a
model-tagged VALUE and is not a result or a continuation is listed in `skipped` with a reason,
so nothing is dropped silently.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .columns import Columns, header_columns

LEADER = re.compile(r"^[.·_:\-]{3,}$")
COMPARATOR_WORDS = {"<", ">", "<=", ">=", "≤", "≥"}
SEX_LABEL = re.compile(r"^(m|f|male|female|men|women|adult|child)\s*:?$", re.I)
RESULT_WORDS = {"negative", "positive", "nil", "absent", "present", "reactive", "non-reactive", "nonreactive",
                "non", "trace", "detected", "not", "normal", "abnormal"}
BIG_GAP = 2.5          # x median line pitch: a gap this large ends a result's continuation lines
RANGE_GAP = 4.0        # ... except for rows still in the range column, up to this many pitches
MIN_CELL_GAP = 5.0     # points between the test name and the value cell (prose lines have ~3)

LAYOUT_HEADER = "header"
LAYOUT_NO_HEADER = "no header"


@dataclass
class Line:
    page: int
    line: int                     # 1-based row number on the page
    words: list[dict]             # pdfplumber words (text, x0, x1, top, bottom)
    tags: list[str]

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)

    @property
    def top(self) -> float:
        return self.words[0]["top"]

    def has(self, kind: str) -> bool:
        return any(t.endswith("-" + kind) for t in self.tags)


@dataclass
class Result:
    test_text: str
    value_text: str
    unit_text: str
    range_text: str
    flag_text: str
    page: int
    line: int
    row_text: str
    range_lines: list[str] = field(default_factory=list)   # first range line + continuation range lines
    notes: list[str] = field(default_factory=list)          # Method / Specimen / codes / other text
    continuation_lines: list[int] = field(default_factory=list)   # line numbers attached to this result
    bbox: list[float] | None = None     # [x0, top, x1, bottom] of the row's words, PDF points from the top left


@dataclass
class Skipped:
    page: int
    line: int
    text: str
    reason: str


@dataclass
class Assembly:
    results: list[Result]
    skipped: list[Skipped]
    layout: str
    header_text: str | None
    page_header_lines: set[tuple[int, int]]   # (page, line) of rows treated as page header/footer


def _join(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def clean_range(words: list[dict]) -> str:
    """First range line without its interpretation: "74 - 99 mg/dl : Normal." -> "74 - 99 mg/dl".

    A colon that comes after a number ends the range; sex labels ("M:", "F:") do not.
    """
    out: list[str] = []
    seen_number = False
    for w in words:
        t = w["text"]
        if SEX_LABEL.match(t):
            out.append(t)
            continue
        if seen_number and (t == ":" or t == ":-" or t.startswith(":")):
            break
        if seen_number and t.endswith(":") and len(t) > 1:
            out.append(t[:-1])
            break
        out.append(t)
        seen_number = seen_number or any(ch.isdigit() for ch in t)
    return " ".join(out).strip()


def _pitch(rows: list[list[dict]]) -> float:
    """Typical distance between consecutive lines: the median gap, at most twice the text height
    (a sparse page has few gaps, and its median would be too large)."""
    gaps = [b[0]["top"] - a[0]["top"] for a, b in zip(rows, rows[1:])]
    gaps = [g for g in gaps if 3 < g < 40]
    heights = [w["bottom"] - w["top"] for r in rows for w in r if w["bottom"] > w["top"]]
    cap = 2 * statistics.median(heights) if heights else 24.0
    return min(statistics.median(gaps), cap) if gaps else min(12.0, cap)


def _repeated_rows(pages: list[tuple[int, list[Line]]]) -> set[tuple[int, int]]:
    """(page, line) of rows printed identically at the same height on two or more pages: the page
    header and footer. Body lines such as "Method :CALCULATED" repeat too, but not at the same height."""
    where: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for page, lines in pages:
        for ln in lines:
            where.setdefault((ln.text, round(ln.top / 2)), []).append((page, ln.line))
    out: set[tuple[int, int]] = set()
    for spots in where.values():
        if len({p for p, _ in spots}) >= 2:
            out.update(spots)
    return out


def _is_heading(ln: Line, test_x: float | None) -> bool:
    """A section title ("LIPID PROFILE", "BLOOD - BIOCHEMISTRY"): upper case, no digits or colon,
    starting left of the test names above it."""
    text = ln.text
    letters = [ch for ch in text if ch.isalpha()]
    return (test_x is not None and ln.words[0]["x0"] < test_x - 6 and len(ln.words) <= 6 and bool(letters)
            and all(ch.isupper() for ch in letters) and not any(ch.isdigit() or ch == ":" for ch in text))


# ---------------------------------------------------------------- header mode

def row_columns(ln: Line, cols: Columns) -> list[str | None]:
    """Column of each word, by position; then words only a space apart stay in one cell, since table
    cells are separated by column gaps. So a long test name that reaches into the value column's
    bounds stays the test name (up to the value header), and "% of total Hb" stays one unit even
    where "Hb" runs past the unit column."""
    col = [cols.column_of(w) for w in ln.words]
    if cols.column_of_start(ln.words[0]) == "test":
        col[0] = "test"
    value_x0 = cols.header_x0("value")
    for i in range(1, len(ln.words)):
        w, prev = ln.words[i], ln.words[i - 1]
        if w["x0"] - prev["x1"] >= MIN_CELL_GAP or col[i] == col[i - 1]:
            continue
        if col[i - 1] == "test" and value_x0 is not None and w["x0"] >= value_x0:
            continue            # the test-name run stops at the value header
        col[i] = col[i - 1]
    return col


def _value_cell(ln: Line, col: list[str | None]) -> list[int]:
    """Indexes of the value-column words, if they form their own cell (a column gap before them)."""
    idx = [i for i, c in enumerate(col) if c == "value"]
    if not idx or idx[0] == 0 or ln.words[idx[0]]["x0"] - ln.words[idx[0] - 1]["x1"] < MIN_CELL_GAP:
        return []
    return idx


def _header_result(ln: Line, cols: Columns) -> Result | None:
    words, tags = ln.words, ln.tags
    col = row_columns(ln, cols)
    if col[0] != "test" or cols.column_of_start(words[0]) != "test":
        return None
    cell = _value_cell(ln, col)
    value_idx = [i for i in cell if tags[i].endswith("-VALUE")]
    if not value_idx:
        return None      # no model-tagged value in a value cell (or prose running across the columns)

    test_words = []
    for w, c, t in zip(words, col, tags):
        if c != "test" or t.endswith("-VALUE"):
            break
        if not LEADER.match(w["text"]):
            test_words.append(w)
    if not test_words:
        return None

    # Value: VALUE-tagged words in the value column, with a comparator word just before them.
    start = value_idx[0]
    if start > 0 and col[start - 1] == "value" and words[start - 1]["text"] in COMPARATOR_WORDS:
        start -= 1
    value_words = [words[start]] + [words[i] for i in value_idx if i > start]

    in_range = [w for w, c, t in zip(words, col, tags) if c == "range" and not t.endswith("-FLAG")]
    flag_words = [w for w, c, t in zip(words, col, tags) if t.endswith("-FLAG") and c != "range"]
    if not flag_words and cols.has("flag"):
        flag_words = [w for w, c in zip(words, col) if c == "flag"]
    if cols.has("unit"):
        unit_words = [w for w, c, t in zip(words, col, tags) if c == "unit" and not t.endswith("-FLAG")]
    else:
        unit_words = [w for w, c, t in zip(words, col, tags) if t.endswith("-UNIT") and c != "range"]
    if not cols.has("range"):
        in_range = [w for w, t in zip(words, tags) if t.endswith("-RANGE")]

    return Result(
        test_text=_join(test_words), value_text=_join(value_words), unit_text=_join(unit_words),
        range_text=clean_range(in_range), flag_text=_join(flag_words), page=ln.page, line=ln.line,
        row_text=ln.text, range_lines=[_join(in_range)] if in_range else [],
    )


def _result_shaped(ln: Line, cols: Columns) -> bool:
    """A test name, then its own value cell holding a number or a result word ("Negative"), or any
    value cell followed by a unit or a numeric range: a result row, whatever the model's tags."""
    if cols.column_of_start(ln.words[0]) != "test":
        return False
    col = row_columns(ln, cols)
    idx = _value_cell(ln, col)
    if not idx:
        return False
    cell = [ln.words[i]["text"] for i in idx]
    if any(ch.isdigit() for t in cell for ch in t) or cell[0].lower().strip(".,:") in RESULT_WORDS:
        return True
    unit_or_range = [w["text"] for w, c in zip(ln.words, col) if c in ("unit", "range")]
    return any(ch.isdigit() for t in unit_or_range for ch in t) or any(c == "unit" for c in col)


def _shaped_reason(ln: Line, cols: Columns) -> str:
    col = row_columns(ln, cols)
    idx = _value_cell(ln, col)
    cell = " ".join(ln.words[i]["text"] for i in idx)
    kinds = {ln.tags[i].split("-")[-1] for i in idx if ln.tags[i] != "O"}
    if "RANGE" in kinds:
        return (f"looks like a result row, but the model tagged the value cell '{cell}' as a range, not a value "
                "(values with < or > were not in its training data)")
    return f"looks like a result row, but the model did not tag the value cell '{cell}' as a value"


def _attach_header_mode(res: Result, ln: Line, cols: Columns) -> None:
    rng = [w for w in ln.words if cols.column_of(w) == "range"]
    other = [w for w in ln.words if cols.column_of(w) != "range"]
    if rng:
        res.range_lines.append(_join(rng))
    if other:
        res.notes.append(_join(other))


# ---------------------------------------------------------------- no-header mode

def _spans(ln: Line, kind: str) -> list[list[dict]]:
    spans: list[list[dict]] = []
    for w, t in zip(ln.words, ln.tags):
        if t == "B-" + kind or (t == "I-" + kind and not spans):
            spans.append([w])
        elif t == "I-" + kind:
            spans[-1].append(w)
    return spans


def _tag_result(ln: Line) -> Result | None:
    tests, values = _spans(ln, "TEST"), _spans(ln, "VALUE")
    if not tests or not values:
        return None
    first = lambda k: _join(_spans(ln, k)[0]) if _spans(ln, k) else ""  # noqa: E731
    ranges = _spans(ln, "RANGE")
    return Result(
        test_text=_join(tests[0]), value_text=_join(values[0]), unit_text=first("UNIT"),
        range_text=clean_range(ranges[0]) if ranges else "", flag_text=first("FLAG"),
        page=ln.page, line=ln.line, row_text=ln.text, range_lines=[_join(ranges[0])] if ranges else [],
    )


def _attach_tag_mode(res: Result, ln: Line) -> None:
    rng = [w for w, t in zip(ln.words, ln.tags) if t.endswith("-RANGE")]
    other = [w for w, t in zip(ln.words, ln.tags) if not t.endswith("-RANGE")]
    if rng:
        res.range_lines.append(_join(rng))
    if other:
        res.notes.append(_join(other))


# ---------------------------------------------------------------- driver

FOOTER_ZONE = 0.85     # rows below this fraction of the page height are footer candidates


def assemble(pages: list[tuple[int, list[Line]]], heights: dict[int, float] | None = None) -> Assembly:
    """pages: [(page number, lines)] in reading order; heights: page heights in points."""
    headers = {(ln.page, ln.line): header_columns(ln.words) for _, lines in pages for ln in lines}
    headers = {k: v for k, v in headers.items() if v is not None}
    layout = LAYOUT_HEADER if headers else LAYOUT_NO_HEADER
    repeated = _repeated_rows(pages)

    results: list[Result] = []
    skipped: list[Skipped] = []
    page_header: set[tuple[int, int]] = set()
    cols: Columns | None = None
    header_text = None

    for page, lines in pages:
        pitch = _pitch([ln.words for ln in lines])
        first_header = min((ln.line for ln in lines if (page, ln.line) in headers), default=None)
        current: Result | None = None     # result that continuation lines attach to
        current_x: float | None = None    # x of that result's first word
        open_block = False
        seen_result = False
        footer_top = FOOTER_ZONE * (heights or {}).get(page, 792.0)
        prev_top = None

        for ln in lines:
            key = (page, ln.line)
            gap = ln.top - prev_top if prev_top is not None else 0.0
            prev_top = ln.top

            if key in headers:
                cols = headers[key]
                header_text = header_text or cols.header_text
                current, open_block = None, False
                continue
            if first_header is not None and ln.line < first_header and cols is None:
                # Above the first table header of the report: report and patient header. (On later
                # pages the table may continue before a new header; the repeated page header is
                # caught below.)
                page_header.add(key)
                if ln.has("VALUE"):
                    skipped.append(Skipped(page, ln.line, ln.text, "page header: above the results table"))
                continue
            if key in repeated and (not seen_result or ln.top > footer_top):
                page_header.add(key)
                if ln.has("VALUE"):
                    skipped.append(Skipped(page, ln.line, ln.text,
                                           "repeated on several pages (page header or footer)"))
                continue

            res = _header_result(ln, cols) if cols is not None else _tag_result(ln)
            if res is not None:
                results.append(res)
                current, open_block, current_x = res, True, ln.words[0]["x0"]
                seen_result = True
                continue
            if cols is not None and _result_shaped(ln, cols):
                # A test name with its own value cell, but the model did not tag a value there.
                skipped.append(Skipped(page, ln.line, ln.text, _shaped_reason(ln, cols)))
                current, open_block = None, False
                continue

            # Not a result: a continuation of the result above, or not part of any result.
            if current is not None and _is_heading(ln, current_x):
                open_block = False
            first_col = cols.column_of_start(ln.words[0]) if cols is not None else None
            in_range_col = first_col == "range"
            # With columns, continuation lines start in the test column (method, specimen, codes) or the
            # range column (more range lines); a line starting mid-table ("* End of Report *") is neither.
            starts_ok = cols is None or first_col in ("test", "range")
            if current is not None and open_block and starts_ok and (gap <= BIG_GAP * pitch
                                                                     or (in_range_col and gap <= RANGE_GAP * pitch)):
                if cols is not None:
                    _attach_header_mode(current, ln, cols)
                else:
                    _attach_tag_mode(current, ln)
                current.continuation_lines.append(ln.line)
                continue
            open_block = False
            if ln.has("VALUE"):
                skipped.append(Skipped(page, ln.line, ln.text, _why_not(ln, cols, current)))

    return Assembly(results, skipped, layout, header_text, page_header)


def _why_not(ln: Line, cols: Columns | None, current: Result | None) -> str:
    if cols is None:
        if not ln.has("TEST"):
            return "no test name on this line"
        return "not attached to a result: no result above it on this page" if current is None \
            else "not attached to a result: too far below the previous result"
    first_col = cols.column_of_start(ln.words[0])
    col = row_columns(ln, cols)
    if first_col != "test":
        return f"starts in the {first_col or 'unlabelled'} column, not the test-name column, " \
               "and no result above it to attach to"
    if not any(c == "value" and t.endswith("-VALUE") for c, t in zip(col, ln.tags)):
        return "the number tagged as a value is not in the value column"
    return "value cell is not separated from the test name (text running across columns)"
