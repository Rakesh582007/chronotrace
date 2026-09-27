"""Build report content and render it with ReportLab in one of ten layout families.

Every string drawn on the page is recorded as a Fragment (text, position, field kind), so
the labeller can later tag the words pdfplumber reads back without guessing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Callable

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import clinical
from . import dictionary as d
from . import extra_tests as xt
from . import identity as ident
from . import values as v

PAGE_W, PAGE_H = A4
MAX_PAGES = 3
INLINE_GAP = 6.0       # value -> unit gap in the inline-unit family (pdfplumber splits at > 3 pt)
LEADER_GAP = 5.0
GREY = colors.Color(0.55, 0.55, 0.55)
LIGHT = colors.Color(0.92, 0.92, 0.92)
DARK = colors.Color(0.18, 0.24, 0.33)

FONT_PRESETS = {  # regular, bold, italic, base size
    "helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", 9.0),
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", 10.0),
    "courier": ("Courier", "Courier-Bold", "Courier-Oblique", 8.5),
    "vera": ("Vera", "VeraBd", "VeraIt", 8.5),
}

LABEL_SETS = [
    {"test": "Test Name", "value": "Result", "unit": "Unit", "range": "Reference Range",
     "flag": "Flag", "method": "Method", "value_unit": "Result"},
    {"test": "Investigation", "value": "Observed Value", "unit": "Units",
     "range": "Biological Ref. Interval", "flag": "H/L", "method": "Method", "value_unit": "Observed Value"},
    {"test": "Parameter", "value": "Value", "unit": "Units", "range": "Normal Range",
     "flag": "Status", "method": "Technique", "value_unit": "Value"},
    {"test": "TEST", "value": "RESULT", "unit": "UNITS", "range": "REF. RANGE",
     "flag": "FLAG", "method": "METHOD", "value_unit": "RESULT"},
    {"test": "Test Description", "value": "Result", "unit": "Unit(s)", "range": "Reference Interval",
     "flag": "Remark", "method": "Method", "value_unit": "Result"},
]

_fonts_registered = False


def register_fonts() -> None:
    """Vera ships inside ReportLab, so the fourth font works on every machine."""
    global _fonts_registered
    if not _fonts_registered:
        for name, file in [("Vera", "Vera.ttf"), ("VeraBd", "VeraBd.ttf"), ("VeraIt", "VeraIt.ttf")]:
            pdfmetrics.registerFont(TTFont(name, file))
        _fonts_registered = True


# ---------------------------------------------------------------- content model

@dataclass
class TestRow:
    row_id: int
    analyte_id: str | None  # dictionary analyte, or None for a non-dictionary test
    extra_id: str | None    # id in extra_tests.EXTRA_TESTS for non-dictionary tests
    panel: str
    synonym: str            # name from the dictionary (or the extra test's name list)
    display: str            # as printed (maybe upper-cased)
    basis: str              # "primary" or "alternate" (urea printed as BUN)
    unit_key: str           # unit as spelled in the dictionary
    unit: str               # as printed
    value: str
    canonical_value: float | None   # None for non-dictionary tests
    range: str
    range_format: str
    flag: str
    method: str
    value_class: str        # normal, abnormal or extreme
    sex: str
    age: int
    profile: str
    flag_column: bool = True   # False when the layout has no flag column (flag is then not printed)

    @property
    def abnormal(self) -> bool:
        return self.value_class != "normal"

    def truth(self) -> dict:
        return {
            "synonym": self.synonym, "test": self.display, "extra_id": self.extra_id,
            "panel": self.panel, "basis": self.basis, "unit_key": self.unit_key, "unit": self.unit,
            "value": self.value, "range": self.range, "range_format": self.range_format,
            "flag": self.flag if self.flag_column else "", "flag_column": self.flag_column,
            "value_class": self.value_class, "abnormal": self.abnormal,
            "sex": self.sex, "age": self.age, "profile": self.profile,
        }


@dataclass
class Section:
    header: str
    rows: list[TestRow]
    notes: list[str]


@dataclass
class Report:
    report_id: str
    family: str
    profile: str
    lab: dict
    people: dict
    title: str
    sections: list[Section]

    def rows(self) -> list[TestRow]:
        return [r for s in self.sections for r in s.rows]


@dataclass
class Family:
    name: str
    base_columns: list[str]
    label_sets: list[int]
    fonts: list[str]
    headers: list[str]
    patients: list[str]
    tables: list[str]
    sections: list[str]
    col_header: list[str]
    page_formats: list[str]
    endings: list[list[str]]
    p_flag: float = 0.0
    flag_pos: str = "end"
    p_method: float = 0.0
    method_pos: str = "after_test"
    p_swap_unit_range: float = 0.0
    value_align: list[str] = field(default_factory=lambda: ["left"])
    leaders: bool = False
    p_method_line: float = 0.0
    p_notes: float = 0.3
    p_break: float = 0.1
    continuation: list[str] = field(default_factory=lambda: ["short"])
    size_delta: tuple[float, float] = (-0.5, 0.5)
    row_gap: tuple[float, float] = (1.55, 1.9)
    p_upper_tests: float = 0.15
    p_lower_units: float = 0.3
    p_bold_abnormal: float = 0.3
    p_disclaimer: float = 0.3


FAMILIES: list[Family] = [
    Family("grid_classic", ["test", "value", "unit", "range"], [0, 4], ["helvetica", "vera"],
           ["centered_banner", "boxed"], ["grid2x3", "boxed"], ["grid"], ["centered_bold"],
           ["per_section"], ["Page {i} of {n}"], [["signature"], ["signature", "end_marker"]],
           p_flag=0.2, p_method=0.1, p_swap_unit_range=0.15, value_align=["center"],
           continuation=["full"], p_break=0.3),
    Family("hrule_investigation", ["test", "value", "unit", "range"], [1], ["helvetica", "times"],
           ["left_logo"], ["table_lines"], ["hrules"], ["left_underline"],
           ["per_page"], ["Page {i} of {n}", "Page {i}/{n}"], [["signature"], ["end_marker", "signature"]],
           p_flag=0.1, p_method=0.3, method_pos="end", p_swap_unit_range=0.2, p_notes=0.5, p_break=0.35),
    Family("flag_emphasis", ["test", "value", "flag", "unit", "range"], [0, 2], ["helvetica", "vera"],
           ["boxed"], ["grid2x3"], ["banded"], ["shaded_bar"],
           ["per_section"], ["Page {i} of {n}"], [["signature"]],
           p_swap_unit_range=0.2, value_align=["right", "center"], p_bold_abnormal=0.8, p_break=0.25),
    Family("method_column", ["test", "method", "value", "unit", "range"], [0, 1, 4], ["times", "vera"],
           ["two_column"], ["inline_rows"], ["none"], ["caps_left"],
           ["per_section"], ["{i} / {n}"], [["end_marker"], ["signature", "end_marker"]],
           p_flag=0.3, p_swap_unit_range=0.2, p_break=0.3, continuation=["none"]),
    Family("range_first", ["test", "range", "value", "unit"], [2, 3], ["helvetica", "courier"],
           ["right_aligned"], ["grid2x3"], ["hrules"], ["boxed"],
           ["per_page"], ["Page {i} of {n}"], [["signature"]],
           p_flag=0.3, flag_pos="after_value", continuation=["full"], p_disclaimer=0.7, p_break=0.25),
    Family("inline_unit", ["test", "value_unit", "range"], [0, 4], ["vera", "helvetica", "times"],
           ["minimal"], ["inline_rows"], ["none"], ["centered_bold"],
           ["per_section"], ["Page {i}"], [["signature"]],
           p_flag=0.3, flag_pos="after_value", p_notes=0.4, p_break=0.2),
    Family("dotmatrix_leaders", ["test", "value", "unit", "range"], [3], ["courier"],
           ["minimal_center"], ["inline_rows"], ["none"], ["caps_left"],
           ["per_page", "none"], ["- {i} -"], [["end_marker"]],
           p_flag=0.2, leaders=True, p_break=0.3, continuation=["none"], p_upper_tests=0.6,
           p_lower_units=0.5, p_bold_abnormal=0.0),
    Family("method_line_below", ["test", "value", "unit", "range"], [0, 1], ["helvetica", "times", "vera"],
           ["left_logo", "centered_banner"], ["grid2x3"], ["hrules"], ["left_underline"],
           ["per_section"], ["Page {i} of {n}"], [["signature"], ["signature", "end_marker"]],
           p_flag=0.2, p_method_line=0.85, p_notes=0.8, p_break=0.3),
    Family("banded_header_bar", ["test", "value", "unit", "range"], [2, 4], ["vera", "helvetica"],
           ["centered_banner"], ["boxed"], ["banded_bar"], ["shaded_bar"],
           ["per_section"], ["Page {i} of {n}"], [["signature"]],
           p_flag=0.5, p_break=0.35, continuation=["full"], p_disclaimer=0.6),
    Family("compact_dense", ["test", "value", "unit", "range"], [3, 1], ["helvetica", "courier", "times", "vera"],
           ["two_column"], ["inline_rows"], ["hrules", "none"], ["left_underline"],
           ["per_page"], ["Page {i} of {n}", "Page {i}/{n}"], [["signature"], ["end_marker"]],
           p_flag=0.6, p_method=0.6, p_break=0.5, size_delta=(-1.5, -1.0), row_gap=(1.35, 1.55),
           p_notes=0.5, p_disclaimer=0.6),
]
FAMILY_NAMES = [f.name for f in FAMILIES]
FAMILIES_BY_NAME = {f.name: f for f in FAMILIES}


# ---------------------------------------------------------------- content generation

@dataclass
class _Print:
    """Report-level printing choices shared by every row."""
    two_sided: str
    high: str
    p_sex_format: float
    upper_tests: bool
    lower_units: bool
    flag_style: tuple[str, str]
    group: bool


def _unit_text(unit: str, pr: _Print) -> str:
    return unit.replace("dL", "dl").replace("mol/L", "mol/l") if pr.lower_units else unit


def _dictionary_row(rng, a: dict, panel: str, state: dict, printed_creatinine: float | None,
                    people: dict, profile: str, pr: _Print, row_id: int) -> TestRow:
    aid, sex, age = a["id"], people["sex"], people["age"]
    basis = "alternate" if d.basis_synonyms(a) and rng.random() < 0.25 else "primary"
    synonym = rng.choice(d.basis_synonyms(a) if basis == "alternate" else d.name_pool(a))
    units = [c["unit"] for c in a["conversions"]]
    unit_key = a["canonical_unit"] if rng.random() < 0.45 else rng.choice(units)

    canonical = v.egfr_from_creatinine(printed_creatinine, age, sex) if aid == "egfr" else state[aid]
    value_text = v.format_value(a, unit_key, basis, d.from_canonical(a, canonical, unit_key, basis), pr.group)
    canonical_value = d.to_canonical(a, v.parse_number(value_text), unit_key, basis)
    flag = v.flag_for(a, canonical_value, sex)
    range_text, range_format = v.format_range(
        rng, a, unit_key, basis, sex, pr.two_sided, pr.high, pr.p_sex_format, pr.group)
    return TestRow(
        row_id=row_id, analyte_id=aid, extra_id=None, panel=panel, synonym=synonym,
        display=synonym.upper() if pr.upper_tests else synonym, basis=basis,
        unit_key=unit_key, unit=_unit_text(unit_key, pr), value=value_text,
        canonical_value=round(canonical_value, 6), range=range_text, range_format=range_format,
        flag={"H": pr.flag_style[0], "L": pr.flag_style[1], "": ""}[flag],
        method=rng.choice(v.METHODS[aid]), value_class=clinical.value_class(a, canonical_value, sex),
        sex=sex, age=age, profile=profile,
    )


def _extra_row(rng, t: xt.ExtraTest, panel: str, state: dict, people: dict, profile: str,
               pr: _Print, row_id: int) -> TestRow:
    sex = people["sex"]
    name = rng.choice(t.names)
    value_text = xt.format_value(t, state[t.id])
    flag = xt.flag_for(t, v.parse_number(value_text), sex)
    range_text, range_format = xt.format_range(rng, t, sex, pr.two_sided, pr.high, pr.p_sex_format)
    return TestRow(
        row_id=row_id, analyte_id=None, extra_id=t.id, panel=panel, synonym=name,
        display=name.upper() if pr.upper_tests else name, basis="primary",
        unit_key=t.unit, unit=_unit_text(t.unit, pr), value=value_text, canonical_value=None,
        range=range_text, range_format=range_format,
        flag={"H": pr.flag_style[0], "L": pr.flag_style[1], "": ""}[flag],
        method=rng.choice(t.methods), value_class="abnormal" if flag else "normal",
        sex=sex, age=people["age"], profile=profile,
    )


def build_content(rng: random.Random, fake: Faker, family: Family, report_id: str) -> Report:
    analytes = d.analytes()
    people = ident.people(fake, rng)
    profile = clinical.choose_profile(rng)
    state = clinical.patient_state(rng, profile, people["sex"])

    chosen = clinical.choose_panels(rng, profile)
    if rng.random() < 0.7:
        chosen.sort(key=list(d.PANELS).index)

    pr = _Print(
        two_sided=rng.choice(["dash", "dash_spaced", "paren"]),
        high=rng.choice(["lt", "upto"]),
        p_sex_format=1.0 if rng.random() < 0.45 else 0.0,
        upper_tests=rng.random() < family.p_upper_tests,
        lower_units=rng.random() < family.p_lower_units,
        flag_style=rng.choice(v.FLAG_STYLES),
        group=rng.random() < 0.5,
    )

    sections: list[Section] = []
    row_id = 0
    for panel in chosen:
        dict_ids = [a for a in d.PANELS[panel] if a != "egfr" and rng.random() < 0.92]
        if not dict_ids:
            dict_ids = [rng.choice([a for a in d.PANELS[panel] if a != "egfr"])]
        if "creatinine" in dict_ids and rng.random() < 0.9:
            dict_ids.append("egfr")   # eGFR is printed with, and computed from, creatinine
        order = xt.PANEL_ORDER[panel]
        ids = sorted(xt.prune_orphans(dict_ids + xt.choose_extras(rng, panel)), key=order.index)

        rows: list[TestRow] = []
        printed_creatinine = None
        for tid in ids:
            if tid in analytes:
                row = _dictionary_row(rng, analytes[tid], panel, state, printed_creatinine,
                                      people, profile, pr, row_id)
                if tid == "creatinine":
                    printed_creatinine = row.canonical_value
            else:
                row = _extra_row(rng, xt.EXTRA_TESTS[tid], panel, state, people, profile, pr, row_id)
            rows.append(row)
            row_id += 1

        notes = []
        if rng.random() < family.p_notes:
            notes = rng.sample(ident.PANEL_NOTES[panel], rng.randint(1, 2))
            if rng.random() < 0.3:
                notes.append(rng.choice(ident.GENERIC_NOTES))
        sections.append(Section(panel, rows, notes))

    return Report(report_id, family.name, profile, ident.lab(rng), people,
                  rng.choice(ident.REPORT_TITLES), sections)


# ---------------------------------------------------------------- style

@dataclass
class Style:
    font: str
    bold: str
    italic: str
    size: float
    columns: list[str]
    labels: dict
    header: str
    patient: str
    table: str
    section: str
    col_header: str
    page_format: str
    page_pos: str
    endings: list[str]
    value_align: str
    leaders: bool
    method_line: bool
    notes: bool
    break_sections: bool
    bold_abnormal: bool
    row_rules: bool
    disclaimer: str
    continuation: str
    row_gap: float
    max_gap: float
    ml: float
    mr: float
    mt: float
    mb: float
    date_style: int
    show_title: bool


def resolve_style(rng: random.Random, fam: Family) -> Style:
    regular, bold, italic, base = FONT_PRESETS[rng.choice(fam.fonts)]
    cols = list(fam.base_columns)
    if "flag" not in cols and rng.random() < fam.p_flag:
        after = "value_unit" if "value_unit" in cols else "value"
        cols.insert(cols.index(after) + 1 if fam.flag_pos == "after_value" else len(cols), "flag")
    if "method" not in cols and rng.random() < fam.p_method:
        cols.insert(1 if fam.method_pos == "after_test" else len(cols), "method")
    if "unit" in cols and "range" in cols and rng.random() < fam.p_swap_unit_range:
        i, j = cols.index("unit"), cols.index("range")
        cols[i], cols[j] = cols[j], cols[i]
    return Style(
        font=regular, bold=bold, italic=italic,
        size=round(base + rng.uniform(*fam.size_delta), 1),
        columns=cols,
        labels=LABEL_SETS[rng.choice(fam.label_sets)],
        header=rng.choice(fam.headers),
        patient=rng.choice(fam.patients),
        table=rng.choice(fam.tables),
        section=rng.choice(fam.sections),
        col_header=rng.choice(fam.col_header),
        page_format=rng.choice(fam.page_formats),
        page_pos=rng.choice(["left", "center", "right"]),
        endings=rng.choice(fam.endings),
        value_align="left" if fam.leaders else rng.choice(fam.value_align),
        leaders=fam.leaders,
        method_line=rng.random() < fam.p_method_line,
        notes=True,
        break_sections=rng.random() < fam.p_break,
        bold_abnormal=rng.random() < fam.p_bold_abnormal,
        row_rules=rng.random() < 0.5,
        disclaimer=rng.choice(ident.DISCLAIMERS) if rng.random() < fam.p_disclaimer else "",
        continuation=rng.choice(fam.continuation),
        row_gap=rng.uniform(*fam.row_gap),
        max_gap=rng.uniform(14, 40),
        ml=rng.uniform(36, 54), mr=rng.uniform(36, 54),
        mt=rng.uniform(34, 50), mb=rng.uniform(36, 50),
        date_style=rng.randint(0, 2),
        show_title=rng.random() < 0.7,
    )


# ---------------------------------------------------------------- renderer

@dataclass
class Fragment:
    page: int
    text: str
    x0: float
    x1: float
    baseline: float      # ReportLab y (origin bottom-left)
    size: float
    kind: str            # TEST, VALUE, UNIT, RANGE, FLAG or O
    row_id: int | None


class Renderer:
    def __init__(self, path=None, report_id: str = ""):
        """With no path the renderer only measures (dry run) and draws nothing."""
        self.dry = path is None
        self.page = 1
        self.fragments: list[Fragment] = []
        if not self.dry:
            self.c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
            self.c.setTitle(f"Synthetic lab report {report_id}")
            self.c.setSubject("Synthetic report generated for ChronoTrace model training; not a real patient")
            self.c.setAuthor("ChronoTrace synthetic generator")

    @staticmethod
    def width(s: str, font: str, size: float) -> float:
        return pdfmetrics.stringWidth(s, font, size)

    def text(self, x, y, s, font, size, kind="O", row_id=None, align="left", color=colors.black) -> float:
        """Draw `s` and record it. Returns the right edge x."""
        w = self.width(s, font, size)
        x0 = x if align == "left" else (x - w if align == "right" else x - w / 2)
        if not self.dry and s.strip():
            self.c.setFont(font, size)
            self.c.setFillColor(color)
            self.c.drawString(x0, y, s)
            self.fragments.append(Fragment(self.page, s, x0, x0 + w, y, size, kind, row_id))
        return x0 + w

    def line(self, x0, y0, x1, y1, width=0.5, color=colors.black):
        if not self.dry:
            self.c.setStrokeColor(color)
            self.c.setLineWidth(width)
            self.c.line(x0, y0, x1, y1)

    def rect(self, x, y, w, h, fill=None, stroke=None, width=0.5):
        if self.dry:
            return
        if fill is not None:
            self.c.setFillColor(fill)
        if stroke is not None:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(width)
        self.c.rect(x, y, w, h, stroke=int(stroke is not None), fill=int(fill is not None))

    def new_page(self):
        self.c.showPage()
        self.page += 1

    def save(self):
        self.c.save()


@dataclass
class Block:
    height: float
    draw: Callable[[Renderer, float], None]   # draws with its top edge at y
    keep_with_next: bool = False
    break_before: bool = False


@dataclass
class Table:
    columns: list[str]
    x: dict[str, float]
    w: dict[str, float]
    size: float
    row_h: float
    x0: float
    x1: float
    gap: float


# ---------------------------------------------------------------- table geometry

def _cell_texts(row: TestRow, col: str) -> list[str]:
    return {
        "test": [row.display], "value": [row.value], "unit": [row.unit], "range": [row.range],
        "flag": [row.flag], "method": [row.method], "value_unit": [row.value, row.unit],
    }[col]


def compute_table(st: Style, report: Report) -> Table:
    rows = report.rows()
    avail = PAGE_W - st.ml - st.mr
    size = st.size
    while True:
        widths = {}
        for col in st.columns:
            label_w = Renderer.width(st.labels[col], st.bold, size)
            if col == "value_unit":
                cell = max(Renderer.width(r.value, st.bold, size) + INLINE_GAP
                           + Renderer.width(r.unit, st.font, size) for r in rows)
            else:
                font = st.bold if col in ("value", "flag") else st.font
                cell = max(Renderer.width(t, font, size) for r in rows for t in _cell_texts(r, col))
            widths[col] = max(label_w, cell)
        if st.leaders:
            widths["test"] += 40
        gap = (avail - sum(widths.values())) / (len(st.columns) - 1)
        if gap >= 10 or size <= 6:
            break
        size -= 0.5
    gap = max(10.0, min(gap, st.max_gap))
    xs, x = {}, st.ml
    for col in st.columns:
        xs[col] = x
        x += widths[col] + gap
    return Table(st.columns, xs, widths, size, size * st.row_gap, st.ml - 4, x - gap + 4, gap)


def _anchor(tb: Table, col: str, align: str) -> float:
    if align == "right":
        return tb.x[col] + tb.w[col]
    if align == "center":
        return tb.x[col] + tb.w[col] / 2
    return tb.x[col]


def _align(st: Style, col: str) -> str:
    return st.value_align if col in ("value", "flag") else "left"


def _baseline(y_top: float, h: float, size: float) -> float:
    return y_top - h / 2 - size * 0.33


# ---------------------------------------------------------------- blocks

def row_block(st: Style, tb: Table, row: TestRow, index: int) -> Block:
    def draw(r: Renderer, y: float):
        h, size = tb.row_h, tb.size
        if st.table in ("banded", "banded_bar") and index % 2 == 1:
            r.rect(tb.x0, y - h, tb.x1 - tb.x0, h, fill=LIGHT)
        if st.table == "grid":
            r.rect(tb.x0, y - h, tb.x1 - tb.x0, h, stroke=colors.black, width=0.4)
            for col in tb.columns[1:]:
                r.line(tb.x[col] - tb.gap / 2, y, tb.x[col] - tb.gap / 2, y - h, 0.4)
        if st.table == "hrules" and st.row_rules:
            r.line(tb.x0, y - h, tb.x1, y - h, 0.3, GREY)
        base = _baseline(y, h, size)
        test_end = value_start = None
        for col in tb.columns:
            align = _align(st, col)
            x = _anchor(tb, col, align)
            if col == "test":
                test_end = r.text(x, base, row.display, st.font, size, "TEST", row.row_id)
            elif col == "value":
                font = st.bold if row.abnormal and st.bold_abnormal else st.font
                value_start = x if align == "left" else None
                r.text(x, base, row.value, font, size, "VALUE", row.row_id, align)
            elif col == "value_unit":
                font = st.bold if row.abnormal and st.bold_abnormal else st.font
                end = r.text(x, base, row.value, font, size, "VALUE", row.row_id)
                r.text(end + INLINE_GAP, base, row.unit, st.font, size, "UNIT", row.row_id)
            elif col == "unit":
                r.text(x, base, row.unit, st.font, size, "UNIT", row.row_id)
            elif col == "range":
                r.text(x, base, row.range, st.font, size, "RANGE", row.row_id)
            elif col == "flag" and row.flag:
                r.text(x, base, row.flag, st.bold, size, "FLAG", row.row_id, align)
            elif col == "method":
                r.text(x, base, row.method, st.font, size, "O", row.row_id)
        if st.leaders and test_end is not None and value_start is not None:
            dot_w = Renderer.width(".", st.font, size)
            n = int((value_start - LEADER_GAP - (test_end + LEADER_GAP)) / dot_w)
            if n >= 3:
                r.text(test_end + LEADER_GAP, base, "." * n, st.font, size, "O", row.row_id)
    return Block(tb.row_h, draw)


def method_line_block(st: Style, tb: Table, row: TestRow) -> Block:
    size = tb.size - 1
    h = size * 1.35

    def draw(r: Renderer, y: float):
        r.text(tb.x["test"] + 8, _baseline(y, h, size), f"Method: {row.method}", st.italic, size)
    return Block(h, draw)


def col_header_block(st: Style, tb: Table) -> Block:
    h = tb.row_h * 1.1

    def draw(r: Renderer, y: float):
        color = colors.black
        if st.table == "banded_bar":
            r.rect(tb.x0, y - h, tb.x1 - tb.x0, h, fill=DARK)
            color = colors.white
        elif st.table == "grid":
            r.rect(tb.x0, y - h, tb.x1 - tb.x0, h, fill=LIGHT, stroke=colors.black, width=0.4)
            for col in tb.columns[1:]:
                r.line(tb.x[col] - tb.gap / 2, y, tb.x[col] - tb.gap / 2, y - h, 0.4)
        else:
            r.line(tb.x0, y, tb.x1, y, 0.6)
            r.line(tb.x0, y - h, tb.x1, y - h, 0.6)
        base = _baseline(y, h, tb.size)
        for col in tb.columns:
            align = _align(st, col)
            r.text(_anchor(tb, col, align), base, st.labels[col], st.bold, tb.size, align=align, color=color)
    return Block(h, draw, keep_with_next=True)


def section_block(st: Style, tb: Table, header: str, break_before: bool) -> Block:
    size = tb.size + 1.5
    extra = size * 1.3 if st.section == "caps_left" else 0
    h = size * 2.0 + extra

    def draw(r: Renderer, y: float):
        base = y - size * 1.35
        width = tb.x1 - tb.x0
        if st.section == "centered_bold":
            r.text((tb.x0 + tb.x1) / 2, base, header, st.bold, size, align="center")
        elif st.section == "left_underline":
            end = r.text(st.ml, base, header, st.bold, size)
            r.line(st.ml, base - 2, end, base - 2, 0.7)
        elif st.section == "boxed":
            r.rect(tb.x0, base - size * 0.45, width, size * 1.5, stroke=colors.black, width=0.6)
            r.text((tb.x0 + tb.x1) / 2, base, header, st.bold, size, align="center")
        elif st.section == "shaded_bar":
            r.rect(tb.x0, base - size * 0.45, width, size * 1.5, fill=LIGHT)
            r.text(st.ml, base, header, st.bold, size)
        else:  # caps_left with a text underline
            r.text(st.ml, base, header, st.bold, size)
            r.text(st.ml, base - size * 1.3, "=" * len(header), st.font, size)
    return Block(h, draw, keep_with_next=True, break_before=break_before)


def text_lines_block(st: Style, lines: list[str], size: float, font: str, align="left",
                     indent: float = 0.0) -> Block:
    width = PAGE_W - st.ml - st.mr - indent
    wrapped = [w for line in lines for w in simpleSplit(line, font, size, width)]
    lh = size * 1.4
    h = lh * len(wrapped) + size * 0.6

    def draw(r: Renderer, y: float):
        for i, line in enumerate(wrapped):
            base = y - lh * (i + 1) + size * 0.3
            if align == "center":
                r.text(PAGE_W / 2, base, line, font, size, align="center")
            else:
                r.text(st.ml + indent, base, line, font, size)
    return Block(h, draw)


def spacer(h: float) -> Block:
    return Block(h, lambda r, y: None)


def patient_block(st: Style, rep: Report) -> Block:
    p = rep.people
    size = st.size
    sex_text = {"male": ["M", "Male"], "female": ["F", "Female"]}[p["sex"]][st.date_style % 2]
    when = lambda t: ident.fmt_datetime(st.date_style, t)  # noqa: E731
    left = [("Patient Name", p["patient_name"]), ("Age / Sex", f"{p['age']} Yrs / {sex_text}"),
            ("Referred By", p["referrer"])]
    right = [("Patient ID", p["patient_id"]), ("Collected On", when(p["collected"])),
             ("Reported On", when(p["reported"]))]
    if st.patient == "table_lines":
        left.append(("Sample Type", p["sample_type"]))
        right.append(("Sample ID", p["sample_id"]))
    lh = size * 1.55
    sep = " : " if st.date_style == 1 else ": "

    if st.patient == "inline_rows":
        lines = ["    ".join(f"{k}{sep}{val}" for k, val in left),
                 "    ".join(f"{k}{sep}{val}" for k, val in right)]
        return replace(text_lines_block(st, lines, size, st.font), height=lh * 2 + size * 1.5)

    n = max(len(left), len(right))
    pad = size * 0.8 if st.patient == "boxed" else 0
    h = lh * n + 2 * pad + size

    def draw(r: Renderer, y: float):
        x_left, x_right = st.ml + pad, PAGE_W / 2 + 10
        label_w = Renderer.width("Patient Name  ", st.bold, size) + 6
        if st.patient == "boxed":
            r.rect(st.ml - 4, y - lh * n - 2 * pad, PAGE_W - st.ml - st.mr + 8, lh * n + 2 * pad,
                   stroke=colors.black, width=0.6)
        for i in range(n):
            base = y - pad - lh * (i + 1) + size * 0.45
            for (col_x, pairs) in ((x_left, left), (x_right, right)):
                if i < len(pairs):
                    k, val = pairs[i]
                    r.text(col_x, base, k, st.bold, size)
                    r.text(col_x + label_w, base, f": {val}", st.font, size)
            if st.patient == "table_lines":
                r.line(st.ml - 4, base - size * 0.5, PAGE_W - st.mr + 4, base - size * 0.5, 0.3, GREY)
    return Block(h, draw)


def signature_block(st: Style, rep: Report) -> Block:
    p = rep.people
    size = st.size
    h = size * 7

    def draw(r: Renderer, y: float):
        x = PAGE_W - st.mr
        lines = [(p["pathologist"], st.bold), (p["pathologist_degree"], st.font),
                 (p["pathologist_role"], st.font)]
        for i, (line, font) in enumerate(lines):
            r.text(x, y - size * (3.2 + 1.35 * i), line, font, size, align="right")
    return Block(h, draw)


def end_marker_block(st: Style) -> Block:
    size = st.size
    text = "*** End of Report ***" if st.date_style != 2 else "-- End of Report --"
    return Block(size * 2.6, lambda r, y: r.text(PAGE_W / 2, y - size * 1.6, text, st.bold, size, align="center"))


# ---------------------------------------------------------------- page header / footer

def draw_header(r: Renderer, st: Style, rep: Report, y: float, first_page: bool) -> float:
    """Draw the lab header at top edge y; return the height used."""
    lab, size = rep.lab, st.size
    style = st.header if first_page or st.continuation == "full" else "short"
    if not first_page and st.continuation == "none":
        return 0.0
    big = size + 6
    addr = rep.people["lab_address"]
    addr_lines = simpleSplit(addr, st.font, size - 0.5, PAGE_W - st.ml - st.mr - 40)[:2]
    lh = size * 1.35

    if style == "short":
        base = y - size * 1.3
        r.text(st.ml, base, lab["name"], st.bold, size + 1)
        r.text(PAGE_W - st.mr, base, f"{rep.people['patient_name']}  |  {rep.people['patient_id']}",
               st.font, size - 0.5, align="right")
        r.line(st.ml, base - size * 0.6, PAGE_W - st.mr, base - size * 0.6, 0.5)
        return size * 2.6

    if style in ("centered_banner", "boxed", "minimal_center"):
        cx = PAGE_W / 2
        yy = y - big
        r.text(cx, yy, lab["name"], st.bold, big, align="center")
        lines = [] if style == "minimal_center" else [lab["tagline"]]
        lines += addr_lines + [f"{lab['phone']}  |  {lab['email']}"]
        for line in lines:
            yy -= lh
            r.text(cx, yy, line, st.font, size - 0.5, align="center")
        used = y - yy + size * 0.9
        if style == "boxed":
            r.rect(st.ml - 6, y - used, PAGE_W - st.ml - st.mr + 12, used + 2, stroke=colors.black, width=0.8)
        else:
            r.line(st.ml, y - used, PAGE_W - st.mr, y - used, 0.8)
        return used + size * 0.8

    if style == "left_logo":
        radius = big * 0.9
        cx, cy = st.ml + radius, y - radius
        if not r.dry:
            r.c.setFillColor(DARK)
            r.c.circle(cx, cy, radius, stroke=0, fill=1)
        r.text(cx, cy - big * 0.3, lab["initials"], st.bold, big * 0.8, align="center", color=colors.white)
        x = st.ml + 2 * radius + 10
        yy = y - big * 0.9
        r.text(x, yy, lab["name"], st.bold, big)
        for line in addr_lines:
            yy -= lh
            r.text(x, yy, line, st.font, size - 0.5)
        r.text(PAGE_W - st.mr, y - big * 0.9, lab["phone"], st.font, size - 0.5, align="right")
        r.text(PAGE_W - st.mr, y - big * 0.9 - lh, lab["email"], st.font, size - 0.5, align="right")
        used = max(y - yy, 2 * radius) + size
        r.line(st.ml, y - used, PAGE_W - st.mr, y - used, 1.0, DARK)
        return used + size * 0.8

    if style == "two_column":
        yy = y - big
        r.text(st.ml, yy, lab["name"], st.bold, big)
        r.text(PAGE_W - st.mr, yy, lab["tagline"], st.italic, size - 0.5, align="right")
        for i, line in enumerate(addr_lines):
            yy -= lh
            r.text(st.ml, yy, line, st.font, size - 0.5)
            if i == 0:
                r.text(PAGE_W - st.mr, yy, lab["phone"], st.font, size - 0.5, align="right")
        yy -= lh
        r.text(PAGE_W - st.mr, yy, lab["email"], st.font, size - 0.5, align="right")
        used = y - yy + size * 0.8
        r.line(st.ml, y - used, PAGE_W - st.mr, y - used, 0.8)
        return used + size * 0.8

    if style == "right_aligned":
        x = PAGE_W - st.mr
        yy = y - big
        r.text(x, yy, lab["name"], st.bold, big, align="right")
        for line in [lab["tagline"]] + addr_lines + [lab["phone"]]:
            yy -= lh
            r.text(x, yy, line, st.font, size - 0.5, align="right")
        used = y - yy + size * 0.9
        r.line(st.ml, y - used, PAGE_W - st.mr, y - used, 0.6)
        return used + size * 0.8

    # minimal
    yy = y - (size + 3)
    r.text(st.ml, yy, lab["name"], st.bold, size + 3)
    yy -= lh
    r.text(st.ml, yy, (addr_lines[0] if addr_lines else "") + f"   {lab['phone']}", st.font, size - 0.5)
    return y - yy + size * 1.2


def header_height(st: Style, rep: Report, first_page: bool) -> float:
    return draw_header(Renderer(), st, rep, PAGE_H, first_page)


def footer_height(st: Style) -> float:
    return st.size * (3.2 if st.disclaimer else 2.0)


def draw_footer(r: Renderer, st: Style, page: int, pages: int):
    size = st.size - 1
    text = st.page_format.format(i=page, n=pages)
    x = {"left": st.ml, "center": PAGE_W / 2, "right": PAGE_W - st.mr}[st.page_pos]
    r.text(x, st.mb, text, st.font, size, align=st.page_pos)
    if st.disclaimer:
        r.text(PAGE_W / 2, st.mb + size * 1.6, st.disclaimer, st.italic, size - 0.5, align="center")


# ---------------------------------------------------------------- pagination and render

def build_blocks(st: Style, tb: Table, rep: Report) -> list[Block]:
    blocks = [patient_block(st, rep), spacer(st.size * 0.6)]
    if st.show_title:
        blocks.append(text_lines_block(st, [rep.title], st.size + 1.5, st.bold, align="center"))
    if st.col_header == "per_page":
        blocks.append(col_header_block(st, tb))  # page 1: below the patient block, not above it
    for i, sec in enumerate(rep.sections):
        blocks.append(section_block(st, tb, sec.header, st.break_sections and i > 0))
        if st.col_header == "per_section":
            blocks.append(col_header_block(st, tb))
        for j, row in enumerate(sec.rows):
            blocks.append(row_block(st, tb, row, j))
            if st.method_line and "method" not in st.columns:
                blocks.append(method_line_block(st, tb, row))
        if st.notes and sec.notes:
            blocks.append(text_lines_block(st, sec.notes, tb.size - 1, st.italic, indent=4))
        blocks.append(spacer(st.size * 0.8))
    for ending in st.endings:
        blocks.append(signature_block(st, rep) if ending == "signature" else end_marker_block(st))
    return blocks


def paginate(blocks: list[Block], first_avail: float, next_avail: float) -> list[list[Block]]:
    pages: list[list[Block]] = [[]]
    used, avail, i = 0.0, first_avail, 0
    while i < len(blocks):
        j = i
        while blocks[j].keep_with_next and j + 1 < len(blocks):
            j += 1
        group = blocks[i:j + 1]
        gh = sum(b.height for b in group)
        if pages[-1] and (group[0].break_before or used + gh > avail):
            pages.append([])
            used, avail = 0.0, next_avail
        pages[-1].extend(group)
        used += gh
        i = j + 1
    return pages


def render(rep: Report, st: Style, path) -> tuple[list[Fragment], int]:
    """Render the report to `path`; return the recorded fragments and the page count."""
    register_fonts()
    tb = compute_table(st, rep)
    blocks = build_blocks(st, tb, rep)
    col_h = tb.row_h * 1.1 if st.col_header == "per_page" else 0.0
    body = PAGE_H - st.mt - st.mb - footer_height(st) - col_h - 6
    pages = paginate(blocks, body + col_h - header_height(st, rep, True), body - header_height(st, rep, False))

    r = Renderer(path, rep.report_id)
    per_page_header = col_header_block(st, tb)
    for n, page_blocks in enumerate(pages):
        if n:
            r.new_page()
        y = PAGE_H - st.mt
        y -= draw_header(r, st, rep, y, n == 0)
        if col_h and n > 0:
            per_page_header.draw(r, y)
            y -= col_h
        for b in page_blocks:
            b.draw(r, y)
            y -= b.height
        draw_footer(r, st, n + 1, len(pages))
    r.save()
    return r.fragments, len(pages)


def render_capped(rep: Report, st: Style, path) -> tuple[Report, Style, list[Fragment], int]:
    """Render, trimming optional content until the report fits in MAX_PAGES."""
    fragments, pages = render(rep, st, path)
    steps = [
        lambda s, p: (s, replace(p, notes=False)),
        lambda s, p: (s, replace(p, break_sections=False)),
        lambda s, p: (s, replace(p, method_line=False)),
    ]
    for step in steps:
        if pages <= MAX_PAGES:
            break
        rep, st = step(rep, st)
        fragments, pages = render(rep, st, path)
    while pages > MAX_PAGES and len(rep.sections) > 1:
        rep = replace(rep, sections=rep.sections[:-1])
        fragments, pages = render(rep, st, path)
    return rep, st, fragments, pages
