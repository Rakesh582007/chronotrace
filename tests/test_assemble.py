"""Column and row logic on hand-built rows (word positions copied from a real report's layout).

Tags are given explicitly and are often deliberately wrong, to show that the column rules decide
what becomes a result, not the tagger.
"""

import pytest

from backend.extraction.assemble import LAYOUT_HEADER, LAYOUT_NO_HEADER, Line, assemble, clean_range
from backend.extraction.columns import header_columns, keyword_kind

CHAR, SPACE = 4.4, 2.5
HEADER = [(28, "Investigation"), (233, "Observed Value"), (334, "Flag"), (365, "Units"),
          (428, "Biological Reference Interval")]


def words(cells: list[tuple[float, str]], top: float) -> list[dict]:
    out = []
    for x, phrase in cells:
        for part in phrase.split():
            w = len(part) * CHAR
            out.append({"text": part, "x0": x, "x1": x + w, "top": top, "bottom": top + 8})
            x += w + SPACE
    return sorted(out, key=lambda w: w["x0"])


def line(page: int, n: int, top: float, cells, tags=None) -> Line:
    ws = words(cells, top)
    return Line(page, n, ws, tags if tags is not None else ["O"] * len(ws))


def tags_for(cells, top, spec: dict[str, str]) -> list[str]:
    """Tag words by text: {"92": "B-VALUE", ...}; others "O"."""
    return [spec.get(w["text"], "O") for w in words(cells, top)]


def page_with_header(page: int, body: list[Line], header_top=243.6) -> tuple[int, list[Line]]:
    hdr = [line(page, 1, 117, [(28, "SID No. :11111"), (425, "Patient ID : 2222")],
                ["O", "O", "B-VALUE", "O", "O", "O", "B-VALUE"]),
           line(page, 2, 148, [(28, "Age / Sex :52 Y / Male")],
                ["B-TEST", "I-TEST", "I-TEST", "B-VALUE", "B-UNIT", "O", "O"]),
           line(page, 3, header_top, HEADER)]
    return page, hdr + body


def glucose_block(page=1, start=4):
    rows = [
        (295.2, [(46, "GLUCOSE (FASTING)"), (252, "92"), (372, "mg/dl"), (441, "74 - 99 mg/dl : Normal.")],
         {"GLUCOSE": "B-TEST", "(FASTING)": "I-TEST", "92": "B-VALUE", "mg/dl": "B-UNIT", "74": "B-RANGE",
          "-": "I-RANGE", "99": "I-RANGE"}),
        # pdfplumber merges the method line with the second range line; the tagger calls it a result.
        (305.9, [(46, "Method :HEXOKINASE"), (441, "100 - 125 mg/dl: IFG/Fair Control")],
         {"Method": "B-TEST", ":HEXOKINASE": "I-TEST", "100": "B-VALUE", "mg/dl:": "B-UNIT"}),
        (314.1, [(30, "MC-4821"), (46, "Specimen: FLUORIDE PLASMA"), (441, "> 126 mg/dl : DM / Poor Control")],
         {"Specimen:": "B-TEST", "126": "B-VALUE", "mg/dl": "B-UNIT"}),
        (324.9, [(441, "IFG- Impaired Fasting Glucose. Pls do")], {"IFG-": "B-TEST", "Impaired": "I-TEST"}),
        (334.6, [(441, "GTT to confirm Diagnosis.")], {"GTT": "B-TEST"}),
    ]
    return [line(page, start + i, top, cells, tags_for(cells, top, spec)) for i, (top, cells, spec) in enumerate(rows)]


# ---------------------------------------------------------------- columns

def test_real_header_columns():
    cols = header_columns(words(HEADER, 243.6))
    assert [c.kind for c in cols.cells] == ["test", "value", "flag", "unit", "range"]
    assert cols.column_at(252) == "value" and cols.column_at(355) == "flag"
    assert cols.column_at(372) == "unit" and cols.column_at(441) == "range" and cols.column_at(46) == "test"


@pytest.mark.parametrize("labels", [
    ["Test Name", "Result", "Unit", "Reference Range"],
    ["Parameter", "Value", "Status", "Units", "Normal Range"],
    ["TEST", "RESULT", "UNITS", "REF. RANGE"],
    ["Test Description", "Result", "Unit(s)", "Reference Interval"],
    ["Investigation", "Observed Value", "Units", "Biological Ref. Interval"],
    ["Test Name", "Method", "Result", "Unit", "Reference Range"],
])
def test_generator_header_label_sets_are_headers(labels):
    cells = [(40 + 120 * i, label) for i, label in enumerate(labels)]
    cols = header_columns(words(cells, 200))
    assert cols is not None and cols.cells[0].kind == "test" and cols.has("value")


@pytest.mark.parametrize("text", [
    "Test results relate only to the sample as received",
    "Final Test Report Page 1 of 5",
    "Ref By. :Dr. EXAMPLE Reported Date and Time :15/01/2024",
])
def test_prose_is_not_a_header(text):
    assert header_columns(words([(28, text)], 200)) is None


def test_keyword_kind():
    assert keyword_kind("Observed") == "value" and keyword_kind("Ref.") == "range" and keyword_kind("H/L") == "flag"


# ---------------------------------------------------------------- the real glucose layout

def test_glucose_with_method_specimen_and_four_line_range_is_one_result():
    asm = assemble([page_with_header(1, glucose_block())])
    assert asm.layout == LAYOUT_HEADER
    assert len(asm.results) == 1, [r.test_text for r in asm.results]
    r = asm.results[0]
    assert (r.test_text, r.value_text, r.unit_text, r.range_text) == ("GLUCOSE (FASTING)", "92", "mg/dl", "74 - 99 mg/dl")
    assert r.range_lines == ["74 - 99 mg/dl : Normal.", "100 - 125 mg/dl: IFG/Fair Control",
                             "> 126 mg/dl : DM / Poor Control", "IFG- Impaired Fasting Glucose. Pls do",
                             "GTT to confirm Diagnosis."]
    assert r.notes == ["Method :HEXOKINASE", "MC-4821 Specimen: FLUORIDE PLASMA"]
    assert r.continuation_lines == [5, 6, 7, 8]


def test_page_header_rows_are_never_results():
    asm = assemble([page_with_header(1, glucose_block())])
    assert all("Age" not in r.test_text for r in asm.results)
    reasons = {(s.line, s.reason) for s in asm.skipped}
    assert (2, "page header: above the results table") in reasons     # "Age / Sex :52 Y" had a VALUE tag
    assert (1, "page header: above the results table") in reasons


def test_merged_specimen_and_range_row_after_hdl():
    body = [
        line(1, 4, 263.5, [(46, "HDL CHOLESTEROL (DIRECT)"), (252, "52"), (372, "mg/dl"),
                           (441, "NCEP guidelines ATP III classification")],
             ["B-TEST", "I-TEST", "I-TEST", "B-VALUE", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE", "I-RANGE", "I-RANGE"]),
        line(1, 5, 274.2, [(46, "Method :DIRECT MEASURE - POLYMER POLY"), (441, "(Coronary heart disease risk)")]),
        line(1, 6, 282.5, [(30, "MC-4821"), (46, "ANION")]),
        line(1, 7, 292.4, [(46, "Specimen: SERUM"), (441, "Less than 40 mg/dl : High Risk")],
             ["B-TEST", "I-TEST", "B-RANGE", "I-RANGE", "B-VALUE", "B-UNIT", "O", "O", "O"]),
    ]
    asm = assemble([page_with_header(1, body)])
    assert [r.test_text for r in asm.results] == ["HDL CHOLESTEROL (DIRECT)"]
    r = asm.results[0]
    assert r.range_lines[-1] == "Less than 40 mg/dl : High Risk"
    assert "Specimen: SERUM" in r.notes and "MC-4821 ANION" in r.notes


def test_value_must_be_in_the_value_column():
    body = [line(1, 4, 300, [(46, "SOMETHING"), (441, "12.5 mg/dl")], ["B-TEST", "B-VALUE", "B-UNIT"])]
    asm = assemble([page_with_header(1, body)])
    assert asm.results == []
    assert asm.skipped[-1].reason == "the number tagged as a value is not in the value column"


def test_long_test_name_reaching_the_value_bounds():
    cells = [(46, "URINE ALBUMIN/CREATININE RATIO TOTAL"), (252, "286"), (372, "mg/g"), (441, "Less than 30")]
    body = [line(1, 4, 300, cells, ["B-TEST", "I-TEST", "I-TEST", "I-TEST", "B-VALUE", "B-UNIT", "B-RANGE",
                                    "I-RANGE", "I-RANGE"])]
    asm = assemble([page_with_header(1, body)])
    assert [(r.test_text, r.value_text) for r in asm.results] == [("URINE ALBUMIN/CREATININE RATIO TOTAL", "286")]


def test_prose_line_across_columns_is_not_a_result():
    prose = "LDL is calculated by the Friedewald equation when triglycerides are below 400 mg/dl and so on"
    ln = line(1, 5, 310, [(46, prose)])
    ln.tags = ["B-TEST"] + ["O"] * (len(ln.words) - 1)
    ln.tags[prose.split().index("400")] = "B-VALUE"
    first = line(1, 4, 295, [(46, "LDL"), (252, "102"), (372, "mg/dl")], ["B-TEST", "B-VALUE", "B-UNIT"])
    asm = assemble([page_with_header(1, [first, ln])])
    assert [r.test_text for r in asm.results] == ["LDL"]
    assert asm.results[0].continuation_lines == [5]


def test_result_shaped_row_without_a_value_tag_is_skipped_not_attached():
    first = line(1, 4, 295, [(46, "SODIUM"), (252, "138"), (372, "mmol/l")], ["B-TEST", "B-VALUE", "B-UNIT"])
    second = line(1, 5, 306, [(46, "POTASSIUM"), (252, "Haemolysed"), (372, "mmol/l"), (441, "3.5 - 5.1")],
                  ["B-TEST", "O", "B-UNIT", "B-RANGE", "I-RANGE", "I-RANGE"])
    asm = assemble([page_with_header(1, [first, second])])
    assert asm.results[0].continuation_lines == []
    assert "did not tag the value cell 'Haemolysed'" in asm.skipped[-1].reason


def test_section_heading_and_signature_end_continuations():
    # Spacing as on the real report: range lines ~9.7 pt apart, the signature 55 pt below.
    ranges = ["Risk of developing diabetes: 5.7 - 6.4", "Diabetes : More than or Equal", "to 6.5%",
              "Good Control : 6 - 7 %", "Fair Control : 7 - 8 %", "Poor Control : More than 8 %"]
    body = [line(1, 4, 263.5, [(46, "HB A1C"), (252, "5.6"), (372, "%"), (441, "Nondiabetic : Less than 5.6 %")],
                 ["B-TEST", "I-TEST", "B-VALUE", "B-UNIT"] + ["B-RANGE"] + ["I-RANGE"] * 5)]
    body += [line(1, 5 + i, 274.2 + 9.7 * i, [(441, t)]) for i, t in enumerate(ranges)]
    body += [line(1, 11, 381.5, [(419, "Dr Some Pathologist")]),       # the signature, far below
             line(1, 12, 395.8, [(425, "MBBS ,MD Pathology.")])]
    asm = assemble([page_with_header(1, body)])
    assert asm.results[0].continuation_lines == [5, 6, 7, 8, 9, 10]

    heading = body[:3] + [line(1, 7, 296, [(28, "LIPID PROFILE")]), line(1, 8, 306, [(46, "Method :CHOD-POD")])]
    asm = assemble([page_with_header(1, heading)])
    assert asm.results[0].continuation_lines == [5, 6]            # the heading ends the block


def test_repeated_footer_is_ignored_and_body_lines_repeating_are_kept():
    def pg(n):
        return page_with_header(n, [
            line(n, 4, 295, [(46, f"TEST{n}"), (252, "1.0"), (372, "mg/dl")], ["B-TEST", "B-VALUE", "B-UNIT"]),
            line(n, 5, 306, [(46, "Method :CALCULATED")]),
            line(n, 6, 734.7, [(538, "Cond 1234")], ["O", "B-VALUE"]),
        ])
    asm = assemble([pg(1), pg(2)])
    assert [r.notes for r in asm.results] == [["Method :CALCULATED"], ["Method :CALCULATED"]]
    assert {s.reason for s in asm.skipped if s.line == 6} == {"repeated on several pages (page header or footer)"}
    assert all(r.continuation_lines == [5] for r in asm.results)


def test_no_header_falls_back_to_tags():
    rows = [line(1, 1, 100, [(40, "Fasting Blood Sugar"), (220, "124"), (300, "mg/dL")],
                 ["B-TEST", "I-TEST", "I-TEST", "B-VALUE", "B-UNIT"]),
            line(1, 2, 110, [(40, "Method: GOD-POD")], ["O", "O"])]
    asm = assemble([(1, rows)])
    assert asm.layout == LAYOUT_NO_HEADER
    assert [(r.test_text, r.value_text, r.notes) for r in asm.results] == [("Fasting Blood Sugar", "124", ["Method: GOD-POD"])]


def test_every_value_line_is_a_result_a_continuation_or_skipped():
    pages = [page_with_header(1, glucose_block() + [
        line(1, 9, 360, [(46, "SOMETHING"), (441, "12.5 mg/dl")], ["B-TEST", "B-VALUE", "B-UNIT"]),
        line(1, 10, 700, [(200, "Page 1 of 1")], ["O", "B-VALUE", "O", "O"]),
    ])]
    asm = assemble(pages)
    accounted = {(r.page, r.line) for r in asm.results}
    accounted |= {(r.page, n) for r in asm.results for n in r.continuation_lines}
    accounted |= {(s.page, s.line) for s in asm.skipped}
    value_lines = {(ln.page, ln.line) for _, lines in pages for ln in lines if ln.has("VALUE")}
    assert value_lines <= accounted


@pytest.mark.parametrize("text, expected", [
    ("74 - 99 mg/dl : Normal.", "74 - 99 mg/dl"),
    ("100 - 125 mg/dl: IFG/Fair Control", "100 - 125 mg/dl"),
    ("M: 13.0-17.0 F: 12.0-15.0", "M: 13.0-17.0 F: 12.0-15.0"),
    ("Less than 3.5 : Low Risk", "Less than 3.5"),
    ("Nondiabetic : Less than 5.6 %", "Nondiabetic : Less than 5.6 %"),
    ("NCEP guidelines ATP III classification", "NCEP guidelines ATP III classification"),
])
def test_clean_range(text, expected):
    assert clean_range(words([(441, text)], 100)) == expected
