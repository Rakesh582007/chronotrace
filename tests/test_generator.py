import json
import random

import pytest

from faker import Faker

import check_dataset
from generator import clinical
from generator import dictionary as d
from generator import extra_tests as xt
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
    test_rows = [r for r in rows if r["truth"]]
    assert test_rows
    for r in test_rows:
        t = r["truth"]
        assert entity_text(r["tokens"], r["tags"], "TEST") == t["test"]
        assert entity_text(r["tokens"], r["tags"], "VALUE") == t["value"]
        assert entity_text(r["tokens"], r["tags"], "UNIT") == t["unit"]
        assert entity_text(r["tokens"], r["tags"], "RANGE") == t["range"]
        if r["analyte_id"]:
            got = d.to_canonical(analytes[r["analyte_id"]], v.parse_number(t["value"]), t["unit_key"], t["basis"])
            assert got == pytest.approx(r["canonical_value"], rel=1e-6)


def test_non_dictionary_rows_are_tagged_but_unmapped(small):
    _, _, rows = small
    extras = [r for r in rows if r["truth"] and r["truth"]["extra_id"]]
    assert extras
    for r in extras:
        assert r["analyte_id"] is None and r["canonical_value"] is None
        assert "B-TEST" in r["tags"] and "B-VALUE" in r["tags"]
        if xt.EXTRA_TESTS[r["truth"]["extra_id"]].unit == "":
            assert not any(t.endswith("-UNIT") for t in r["tags"])   # ratios print without a unit


def test_flags_appear_after_value_unit_and_range(small):
    _, _, rows = small
    before = {r["tags"][r["tags"].index("B-FLAG") - 1][2:] for r in rows if "B-FLAG" in r["tags"]}
    assert {"VALUE", "UNIT", "RANGE"} <= before
    assert set(layouts.FLAG_POSITIONS) == {"after_value", "after_unit", "after_range", "column"}


def test_ignore_lines_are_all_o(small):
    _, _, rows = small
    other = [r for r in rows if r["truth"] is None]
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
    # 30 reports are too few for coverage and for stable shares; the full run checks those.
    assert failed <= {"every synonym used", "every unit used", "every range format used",
                      "value mix near 65/30/5", "non-dictionary share of CBC and LFT rows in range"}
    assert "clinical consistency" not in failed


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
    ("platelets", "lakh/cumm", "dash", "lt", 0.0, "male", "1.50-4.10", "dash"),
    ("creatinine", "µmol/L", "dash_spaced", "lt", 0.0, "male", "62 - 115", "dash_spaced"),
    ("hba1c", "mmol/mol", "dash", "lt", 0.0, "male", "20-38", "dash"),
    ("fasting_glucose", "mmol/L", "dash", "lt", 0.0, "male", "3.9-5.5", "dash"),
    ("platelets", "/cumm", "dash", "lt", 0.0, "male", "150000-410000", "dash"),
])
def test_range_formats(aid, unit, two, high, p_sex, sex, expected, fmt):
    a = d.analytes()[aid]
    assert v.format_range(random.Random(0), a, unit, "primary", sex, two, high, p_sex) == (expected, fmt)


def test_every_converted_unit_has_a_print_precision():
    for a in d.analytes().values():
        for conv in a["conversions"]:
            dec, step = v.precision(a, conv["unit"])
            assert dec >= 0 and (step is None or step > 0)


def test_counts_per_cumm_are_rounded():
    plt, wbc = d.analytes()["platelets"], d.analytes()["wbc"]
    assert v.format_value(plt, "/cumm", "primary", 296465.0, group=True) == "2,96,000"
    assert v.format_value(plt, "cells/cumm", "primary", 296465.0, group=False) == "296000"
    assert v.format_value(wbc, "/cumm", "primary", 7843.0, group=False) == "7840"


def test_extra_test_names_do_not_clash_with_dictionary():
    assert xt.names_clashing_with_dictionary() == []


def _contents(n):
    fake = Faker("en_IN")
    reports = []
    for i in range(n):
        rng = random.Random(f"mix:{i}")
        fake.seed_instance(rng.getrandbits(32))
        reports.append(layouts.build_content(rng, fake, layouts.FAMILIES[i % 10], f"r{i}"))
    return reports


def test_value_mix_and_non_dictionary_share():
    reports = _contents(800)
    rows = [r for rep in reports for r in rep.rows()]
    dict_rows = [r for r in rows if r.analyte_id]
    share = {c: sum(r.value_class == c for r in dict_rows) / len(dict_rows) for c in clinical.CLASSES}
    assert share["normal"] == pytest.approx(0.65, abs=0.05)
    assert share["abnormal"] == pytest.approx(0.30, abs=0.05)
    assert share["extreme"] == pytest.approx(0.05, abs=0.025)
    for panel, (lo, hi) in check_dataset.EXTRA_SHARE.items():
        in_panel = [r for r in rows if r.panel == panel]
        assert lo <= sum(r.analyte_id is None for r in in_panel) / len(in_panel) <= hi, panel


def test_related_values_are_consistent():
    rng = random.Random(1)
    for i in range(3000):
        profile = list(clinical.PROFILES)[i % len(clinical.PROFILES)]
        s = clinical.patient_state(rng, profile, rng.choice(["male", "female"]))
        assert not (s["hba1c"] < 5.7 and s["fasting_glucose"] > 200)
        assert s["total_cholesterol"] == pytest.approx(s["ldl"] + s["hdl"] + s["triglycerides"] / 5)
        assert s["pcv"] == pytest.approx(s["haemoglobin"] * 100 / s["mchc"])
        if s["tsh"] > 10:
            assert s["free_t4"] < 0.8          # overt hypothyroid: FT4 low


# Each calculated test: the inputs clinical.py computes it from, and an identity that must hold.
FORMULAS = {
    "direct_bilirubin": ({"total_bilirubin"}, lambda s: 0 < s["direct_bilirubin"] < s["total_bilirubin"]),
    "globulin": ({"total_protein", "albumin"},
                 lambda s: s["globulin"] == pytest.approx(s["total_protein"] - s["albumin"])),
    "ag_ratio": ({"albumin", "globulin"}, lambda s: s["ag_ratio"] == pytest.approx(s["albumin"] / s["globulin"])),
    "vldl": ({"triglycerides"}, lambda s: s["vldl"] == pytest.approx(s["triglycerides"] / 5)),
    "non_hdl": ({"total_cholesterol", "hdl"},
                lambda s: s["non_hdl"] == pytest.approx(s["total_cholesterol"] - s["hdl"])),
    "tc_hdl_ratio": ({"total_cholesterol", "hdl"},
                     lambda s: s["tc_hdl_ratio"] == pytest.approx(s["total_cholesterol"] / s["hdl"])),
    "ldl_hdl_ratio": ({"ldl", "hdl"}, lambda s: s["ldl_hdl_ratio"] == pytest.approx(s["ldl"] / s["hdl"])),
    # Exception (see REQUIRES): computed from Hb and MCHC, but printable with Hb alone.
    "pcv": ({"haemoglobin", "mchc"}, lambda s: s["pcv"] == pytest.approx(s["haemoglobin"] * 100 / s["mchc"])),
    "mch": ({"haemoglobin", "rbc"}, lambda s: s["mch"] == pytest.approx(s["haemoglobin"] * 10 / s["rbc"])),
    "mchc": ({"haemoglobin", "pcv"}, lambda s: s["mchc"] == pytest.approx(s["haemoglobin"] * 100 / s["pcv"])),
}


def test_requires_matches_clinical_formulas():
    assert set(FORMULAS) == set(xt.REQUIRES)
    for tid, (inputs, _) in FORMULAS.items():
        want = {"haemoglobin"} if tid == "pcv" else inputs
        assert xt.REQUIRES[tid] == want, tid
    rng = random.Random(5)
    for i in range(2000):
        profile = list(clinical.PROFILES)[i % len(clinical.PROFILES)]
        s = clinical.patient_state(rng, profile, rng.choice(["male", "female"]))
        for tid, (_, holds) in FORMULAS.items():
            assert holds(s), (tid, s)


@pytest.mark.parametrize("ids, kept", [
    (["haemoglobin", "rbc", "pcv", "mch", "mchc"], ["haemoglobin", "rbc", "pcv", "mch", "mchc"]),
    (["rbc", "pcv", "mcv", "mch", "mchc"], ["rbc", "mcv"]),                   # no Hb: PCV, MCH, MCHC go
    (["haemoglobin", "rbc", "mch", "mchc"], ["haemoglobin", "rbc", "mch"]),   # MCHC needs PCV
    (["alt", "total_protein", "globulin", "ag_ratio"], ["alt", "total_protein"]),  # chain: globulin, then A/G
    (["direct_bilirubin", "alp"], ["alp"]),
    (["total_cholesterol", "ldl", "non_hdl", "tc_hdl_ratio", "ldl_hdl_ratio", "vldl"],
     ["total_cholesterol", "ldl"]),
    (["wbc", "neutrophils", "lymphocytes", "eosinophils", "monocytes"], ["wbc"]),   # partial differential
    (["wbc", *xt.DIFFERENTIAL], ["wbc", *xt.DIFFERENTIAL]),
])
def test_prune_orphans(ids, kept):
    assert xt.prune_orphans(ids) == kept


def test_differential_is_whole_and_sums_to_100():
    rng = random.Random(9)
    for i in range(3000):
        profile = list(clinical.PROFILES)[i % len(clinical.PROFILES)]
        s = clinical.patient_state(rng, profile, rng.choice(["male", "female"]))
        diff = [s[t] for t in xt.DIFFERENTIAL]
        assert all(isinstance(x, int) and x >= 0 for x in diff)
        assert sum(diff) == 100
        assert 0 <= s["basophils"] <= 2
        assert s["neutrophils"] == max(diff)


def test_printed_panels_have_inputs_and_complete_differentials():
    for rep in _contents(300):
        by_panel: dict[str, dict] = {}
        for r in rep.rows():
            by_panel.setdefault(r.panel, {})[r.analyte_id or r.extra_id] = r.value
        for panel in by_panel.values():
            for tid in panel:
                assert xt.REQUIRES.get(tid, set()) <= set(panel), tid
            diff = [panel[t] for t in xt.DIFFERENTIAL if t in panel]
            assert not diff or (len(diff) == 5 and sum(v.parse_number(x) for x in diff) == 100)


def test_printed_egfr_matches_printed_creatinine():
    formula = d.analytes()["egfr"]["formula"]
    for rep in _contents(300):
        rows = {r.analyte_id: r for r in rep.rows() if r.analyte_id}
        if "egfr" in rows:
            want = d.va.egfr_ckd_epi_2021(rows["creatinine"].canonical_value, rows["egfr"].age,
                                          rows["egfr"].sex, formula)
            assert abs(rows["egfr"].canonical_value - want) <= 1


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
