import json
import random

import pytest

import check_dataset
from generator import dictionary as d
from generator import generate_reports as gen
from generator import identity, layouts
from generator import values as v
from generator.brands import find_brands
from generator.labeler import TAGS, bio_ok, entity_text, group_rows

N_SMALL = 30


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    out = tmp_path_factory.mktemp("gen")
    manifest = gen.generate(N_SMALL, seed=7, out_dir=out, workers=1, quiet=True)
    rows = [json.loads(line) for line in open(out / "labels.jsonl", encoding="utf-8")]
    return out, manifest, rows


# ---------------------------------------------------------------- end-to-end dataset

def test_every_word_is_aligned(small):
    _, manifest, _ = small
    a = manifest["alignment"]
    assert a["words"] > 0
    assert a.get("unmatched_words", 0) == 0
    assert a.get("fragment_mismatches", 0) == 0
    assert a.get("mixed_rows", 0) == 0


def test_rows_have_required_fields(small):
    _, _, rows = small
    required = {"report_id", "layout_family", "page", "tokens", "tags", "analyte_id", "canonical_value"}
    for r in rows:
        assert required <= r.keys()
        assert len(r["tokens"]) == len(r["tags"])
        assert set(r["tags"]) <= set(TAGS)
        assert bio_ok(r["tags"])


def test_test_rows_are_consistent(small):
    _, _, rows = small
    analytes = d.analytes()
    test_rows = [r for r in rows if r["analyte_id"]]
    assert test_rows
    for r in test_rows:
        t = r["truth"]
        assert entity_text(r["tokens"], r["tags"], "TEST") == t["test"]
        assert entity_text(r["tokens"], r["tags"], "VALUE") == t["value"]
        assert entity_text(r["tokens"], r["tags"], "UNIT") == t["unit"]
        assert entity_text(r["tokens"], r["tags"], "RANGE") == t["range"]
        got = d.to_canonical(analytes[r["analyte_id"]], v.parse_number(t["value"]), t["unit_key"], t["basis"])
        assert got == pytest.approx(r["canonical_value"], rel=1e-6)


def test_ignore_lines_are_all_o(small):
    _, _, rows = small
    other = [r for r in rows if r["analyte_id"] is None]
    assert other, "reports should contain patient/doctor/method/page lines"
    assert all(set(r["tags"]) == {"O"} for r in other)
    text = " ".join(" ".join(r["tokens"]) for r in other)
    for expected in ("Patient", "Dr.", "Page"):
        assert expected in text


def test_splits(small):
    _, manifest, rows = small
    held = set(manifest["test_families"])
    assert len(held) == 2
    for r in rows:
        assert (r["split"] == "test") == (r["layout_family"] in held)
    assert set(manifest["reports_per_split"]) == {"train", "val", "test"}


def test_check_dataset_passes_except_coverage(small):
    out, _, _ = small
    results, _ = check_dataset.run_checks(out, min_rows=1, workers=1)
    failed = {name for name, ok, _ in results if not ok}
    # 30 reports are too few to use every synonym and unit; the full run checks those.
    assert failed <= {"every synonym used", "every unit used", "every range format used"}


def test_generation_is_reproducible(tmp_path):
    a = gen.generate(6, seed=3, out_dir=tmp_path / "a", workers=1, quiet=True)
    b = gen.generate(6, seed=3, out_dir=tmp_path / "b", workers=1, quiet=True)
    assert a == b
    assert (tmp_path / "a" / "labels.jsonl").read_bytes() == (tmp_path / "b" / "labels.jsonl").read_bytes()
    assert (tmp_path / "a" / "pdfs" / "r00000.pdf").read_bytes() == (tmp_path / "b" / "pdfs" / "r00000.pdf").read_bytes()
    gen.generate(6, seed=4, out_dir=tmp_path / "c", workers=1, quiet=True)
    assert (tmp_path / "a" / "labels.jsonl").read_bytes() != (tmp_path / "c" / "labels.jsonl").read_bytes()


def test_split_assignment_is_seeded():
    fams = gen.choose_test_families(42)
    assert gen.assign_splits(200, 42, fams) == gen.assign_splits(200, 42, fams)
    s = gen.assign_splits(1000, 42, fams)
    assert sum(x == "test" for x in s.values()) == 200          # 2 of 10 families, round-robin
    assert sum(x == "val" for x in s.values()) == 80            # 10% of the remaining 800


# ---------------------------------------------------------------- values and formatting

@pytest.mark.parametrize("aid", list(d.PANELS["RENAL FUNCTION"]) + ["hba1c", "platelets", "free_t4"])
def test_unit_conversion_round_trip(aid):
    a = d.analytes()[aid]
    for conv in a["conversions"]:
        for basis in ("primary", "alternate") if d.basis_synonyms(a) else ("primary",):
            printed = d.from_canonical(a, 1.234, conv["unit"], basis)
            assert d.to_canonical(a, printed, conv["unit"], basis) == pytest.approx(1.234)


def test_bun_value_is_converted_to_urea():
    urea = d.analytes()["urea"]
    assert d.from_canonical(urea, 30.0, "mg/dL", "alternate") == pytest.approx(14.0, abs=0.01)
    assert d.from_canonical(urea, 30.0, "mmol/L", "alternate") == pytest.approx(d.from_canonical(urea, 30.0, "mmol/L"))


def test_indian_grouping():
    assert v.indian_grouping(250000) == "2,50,000"
    assert v.indian_grouping(7800) == "7,800"
    assert v.indian_grouping(950) == "950"
    assert v.parse_number("2,50,000") == 250000


@pytest.mark.parametrize("aid, unit, two, high, p_sex, sex, expected, fmt", [
    ("creatinine", "mg/dL", "dash", "lt", 1.0, "male", "M: 0.7-1.3 F: 0.6-1.1", "sex"),
    ("creatinine", "mg/dL", "dash_spaced", "lt", 0.0, "male", "0.7 - 1.3", "dash_spaced"),
    ("creatinine", "mg/dL", "paren", "lt", 0.0, "female", "(0.6-1.1)", "paren"),
    ("creatinine", "mg/dL", "paren", "lt", 1.0, "female", "M: 0.7-1.3 F: 0.6-1.1", "sex"),
    ("total_cholesterol", "mg/dL", "dash", "lt", 0.0, "male", "< 200", "lt"),
    ("alt", "U/L", "dash", "upto", 0.0, "female", "Up to 33", "upto"),
    ("hdl", "mg/dL", "dash", "lt", 0.0, "male", "> 40", "gt"),
    ("platelets", "lakh/cumm", "dash", "lt", 0.0, "male", "1.5-4.1", "dash"),
])
def test_range_formats(aid, unit, two, high, p_sex, sex, expected, fmt):
    a = d.analytes()[aid]
    assert v.format_range(random.Random(0), a, unit, "primary", sex, two, high, p_sex) == (expected, fmt)


def test_about_70_percent_of_values_are_in_range():
    rng = random.Random(0)
    for aid in ("creatinine", "hdl", "tsh", "platelets"):
        a = d.analytes()[aid]
        flags = [v.flag_for(a, v.sample_canonical(rng, a, "male"), "male") for _ in range(4000)]
        assert 0.25 <= sum(bool(f) for f in flags) / len(flags) <= 0.35, aid


# ---------------------------------------------------------------- identities and brands

def test_invented_lab_names_are_not_real_brands():
    rng = random.Random(0)
    names = {identity.lab(rng)["name"] for _ in range(500)}
    assert not [n for n in names if find_brands(n)]


def test_brand_scan_catches_brands_but_not_person_names():
    assert find_brands("Report from SRL Diagnostics")
    assert find_brands("Dr Lal PathLabs Ltd")
    assert find_brands("thyrocare")
    assert not find_brands("Referred By: Dr. Mohan Lal")
    assert not find_brands("Patient: Anand Kumar, Max Weight")


def test_ten_layout_families():
    assert len(layouts.FAMILIES) == 10
    assert len(set(layouts.FAMILY_NAMES)) == 10
    fonts = {f for fam in layouts.FAMILIES for f in fam.fonts}
    assert fonts == set(layouts.FONT_PRESETS)


# ---------------------------------------------------------------- row grouping

def test_group_rows_orders_words():
    words = [
        {"text": "mg/dL", "x0": 300, "x1": 330, "top": 100.8},
        {"text": "Creatinine", "x0": 50, "x1": 100, "top": 100.0},
        {"text": "1.2", "x0": 200, "x1": 212, "top": 101.5},
        {"text": "Page", "x0": 50, "x1": 70, "top": 800.0},
    ]
    rows = group_rows(words)
    assert [[w["text"] for w in r] for r in rows] == [["Creatinine", "1.2", "mg/dL"], ["Page"]]
