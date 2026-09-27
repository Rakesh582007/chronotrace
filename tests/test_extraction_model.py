"""Extraction with the real NER model on the committed fixture PDFs (skipped without the model)."""

import datetime as dt

import pytest

from backend import normalise as nm
from backend.extraction import SCANNED_MESSAGE, ScannedReportError, extract_report, read_lines
from backend.extraction.assemble import LAYOUT_NO_HEADER
from tests.conftest import FIXTURES, ner_tagger_or_skip


@pytest.fixture(scope="module")
def tagger():
    return ner_tagger_or_skip()


def run(name, tagger, patient=nm.Patient("male", 1972)):
    ex = extract_report(FIXTURES / name, tagger)
    observations, not_results = nm.normalise(ex.results, patient, ex.meta.date)
    return ex, observations, not_results


def test_real_layout_fixture(tagger):
    ex, obs, not_results = run("real_layout.pdf", tagger)
    tracked = {(o.analyte_id, o.canonical_value) for o in obs if o.analyte_id}
    assert tracked == {("fasting_glucose", 92.0), ("creatinine", 0.74), ("urea", 26.0), ("total_cholesterol", 176.0),
                       ("hdl", 52.0), ("triglycerides", 104.0), ("ldl", 102.0), ("hba1c", 5.6)}
    assert all(o.status == nm.EXTRACTED for o in obs if o.analyte_id)
    untracked = {o.test_text for o in obs if o.status == nm.NOT_TRACKED}
    assert untracked == {"CALCIUM -SERUM", "URIC ACID - SERUM", "A.S.O. TITRE", "C.R.P.", "VLDL CHOLESTEROL",
                         "TOTAL CHO / HDL RATIO"}
    assert len(ex.results) == 14 and ex.skipped == [] and not_results == []     # no fake tests
    assert (ex.meta.date, ex.meta.date_label, ex.meta.lab) == (dt.date(2024, 1, 15), "Collected", "ASTERLANE DIAGNOSTICS")


def test_glucose_block_is_one_result_with_its_range_and_notes(tagger):
    ex, _, _ = run("real_layout.pdf", tagger)
    g = ex.results[0]
    assert (g.test_text, g.value_text, g.unit_text, g.range_text) == ("GLUCOSE (FASTING)", "92", "mg/dl", "74 - 99 mg/dl")
    assert g.notes == ["Method :HEXOKINASE", "MC-4821 Specimen: FLUORIDE PLASMA"]
    assert g.range_lines[1:] == ["100 - 125 mg/dl: IFG/Fair Control", "> 126 mg/dl : DM / Poor Control",
                                 "IFG- Impaired Fasting Glucose. Pls do", "GTT to confirm Diagnosis."]
    hdl = next(r for r in ex.results if r.test_text.startswith("HDL"))
    assert "Less than 40 mg/dl : High Risk" in hdl.range_lines and "Specimen: SERUM" in hdl.notes


def test_edge_cases_fixture(tagger):
    ex, obs, _ = run("edge_cases.pdf", tagger, nm.Patient("male", 1967))
    assert (ex.meta.date, ex.meta.date_label) == (dt.date(2024, 1, 16), "Reported")
    by = {o.test_text: o for o in obs}
    assert by["TSH (ULTRASENSITIVE)"].canonical_value == 3.2 and by["TSH (ULTRASENSITIVE)"].canonical_unit == "mIU/L"
    assert by["SERUM SODIUM"].status == nm.NEEDS_REVIEW and by["SERUM SODIUM"].canonical_value is None
    assert by["eGFR (CKD-EPI 2021)"].canonical_value != 49 and "recomputed" in by["eGFR (CKD-EPI 2021)"].status_reason
    # Text and censored values: whatever the model makes of them, each row is accounted for, with a reason.
    for text in ("TRIGLYCERIDES >1000", "SERUM POTASSIUM Haemolysed", "URINE ALBUMIN/CREATININE RATIO <0.5",
                 "HBsAg Non Reactive", "URINE SUGAR Nil", "HIV I & II ANTIBODY Negative"):
        in_obs = any(o.row_text.startswith(text) for o in obs)
        in_skipped = [s for s in ex.skipped if s.text.startswith(text)]
        assert in_obs or (in_skipped and in_skipped[0].reason), text


def test_no_header_fixture_uses_the_tags(tagger):
    ex, obs, _ = run("no_header.pdf", tagger)
    assert ex.layout == LAYOUT_NO_HEADER
    assert {o.analyte_id for o in obs} == {"fasting_glucose", "hba1c", "creatinine", "potassium"}


def test_scanned_pdf_is_rejected():
    with pytest.raises(ScannedReportError, match=SCANNED_MESSAGE):
        extract_report(FIXTURES / "scanned.pdf", tagger=None)


@pytest.mark.parametrize("name", ["real_layout.pdf", "edge_cases.pdf", "no_header.pdf", "demo_t2d_ckd_1.pdf"])
def test_every_value_line_is_accounted_for(tagger, name):
    ex = extract_report(FIXTURES / name, tagger)
    pages, _ = read_lines(FIXTURES / name)
    lines = [ln for _, ls in pages for ln in ls]
    for ln, tags in zip(lines, tagger.tag([[w["text"] for w in ln.words] for ln in lines])):
        ln.tags = tags
    accounted = {(r.page, r.line) for r in ex.results}
    accounted |= {(r.page, n) for r in ex.results for n in r.continuation_lines}
    accounted |= {(s.page, s.line) for s in ex.skipped}
    missing = [(ln.page, ln.line, ln.text) for ln in lines if ln.has("VALUE") and (ln.page, ln.line) not in accounted]
    assert missing == []
