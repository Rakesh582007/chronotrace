"""The four demo patients, seeded through the real API (with the rule-based stand-in tagger), and the seed
command's --reset on an outdated database (step 7)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from backend import db
from backend.demo import data as demo
from backend.demo import seed as seed_module
from backend.main import app, llm_dep, tagger_dep
from backend.summaries.llm import LLMError
from tests.conftest import RuleTagger, signed_in_client, use_fresh_database
from tests.fake_llm import FakeLLM, use_llm

# A summary that passes the checks against K. Selvam's R1-R9 facts.
R1_R9_SUMMARY = {"key_finding": {"text": "eGFR fell by 25.9% from a baseline of 78.4 to 58.1 mL/min/1.73 m².",
                                 "report_ids": ["R1", "R2", "R3", "R9"]},
                 "sections": [], "medication_rows": [], "data_notes": ["Adherence is not recorded."]}


@pytest.fixture
def demo_ward(tmp_path):
    use_fresh_database(tmp_path / "uploads")
    c = signed_in_client()
    out = seed_module.seed_demo(c, tmp_path / "pdfs")
    yield c, out
    app.dependency_overrides.clear()


def by_code(c):
    return {p["patient_code"]: p for p in c.get("/patients").json()}


def test_four_patients_with_the_designed_counts(demo_ward):
    c, out = demo_ward
    got = {code: (p["name"], p["guideline_flags"], p["change_flags"], p["expected_flags"], p["report_count"],
                  p["lab_count"], p["latest_report_date"]) for code, p in by_code(c).items()}
    assert got == {
        "CT-0001": ("K. Selvam", 0, 3, 2, 9, 3, "2025-09-01"),        # R10 is left for the live upload
        "CT-0002": ("M. Rani", 0, 4, 0, 5, 2, "2025-12-15"),
        "CT-0003": ("J. Arul", 0, 0, 0, 1, 1, "2025-08-05"),
        "CT-0004": ("S. Priya", 0, 0, 0, 3, 1, "2025-11-20"),
    }
    assert [p["patient_code"] for p in c.get("/patients").json()] == ["CT-0002", "CT-0001", "CT-0004", "CT-0003"]


def test_rani_lab_change_explains_her_flags(demo_ward):
    c, out = demo_ward
    pid = out["rani"]["patient_id"]
    flags = c.get(f"/patients/{pid}/flags").json()["flags"]
    assert sorted((f["rule_id"], f["analyte_id"], f["date"]) for f in flags) == [
        ("RCV_PREV", "free_t4", "2025-06-16"), ("RCV_PREV", "free_t4", "2025-12-15"),
        ("RCV_PREV", "tsh", "2025-06-16"), ("RCV_PREV", "tsh", "2025-12-15")]
    for f in flags:
        lc = f["lab_change"]
        assert lc["same_lab_agrees"] is True and {lc["from_lab"], lc["to_lab"]} == {"ASTERLANE DIAGNOSTICS", "Kestrelline Labs"}
    tsh_r4 = next(f for f in flags if f["analyte_id"] == "tsh" and f["date"] == "2025-06-16")
    assert tsh_r4["target_direction"] == "toward" and tsh_r4["target"]["label"] == "0.4–4.0 mIU/L"
    thyroid = next(s for s in c.get(f"/patients/{pid}/systems").json()["systems"] if s["id"] == "thyroid")
    assert thyroid["status"] == "changed" and thyroid["headline"]["latest"]["value"] == 8.1


def test_rani_levothyroxine_expected_fall_not_seen(demo_ward):
    c, out = demo_ward
    pid = out["rani"]["patient_id"]
    [med] = c.get(f"/patients/{pid}/medications").json()
    assert (med["drug"], med["drug_class"], med["date"]) == ("Levothyroxine", "thyroid_hormone", "2024-11-04")
    r = c.get(f"/medications/{med['id']}/response").json()
    tsh = next(a for a in r["analytes"] if a["analyte_id"] == "tsh")
    assert (tsh["status"], tsh["verdict"], tsh["change_percent"]) == ("assessed", "not seen", -6.7)
    assert tsh["before"]["value"] == 9.0 and tsh["after"]["value"] == 8.4
    assert "within its reference change value of 51%" in tsh["verdict_note"]
    docs = c.get(f"/patients/{pid}/documents").json()
    assert [(d["kind"], d["document_date"]) for d in docs if d["kind"] == "prescription"] == [("prescription", "2024-11-04")]


def test_priya_and_arul_have_no_flags(demo_ward):
    c, out = demo_ward
    for slug, systems in [("priya", {"kidney", "electrolytes"}), ("arul", {"kidney", "glucose", "lipids"})]:
        pid = out[slug]["patient_id"]
        assert c.get(f"/patients/{pid}/flags").json()["flags"] == []
        status = {s["id"]: s["status"] for s in c.get(f"/patients/{pid}/systems").json()["systems"]}
        assert {k for k, v in status.items() if v == "stable"} == systems
        assert {k for k, v in status.items() if v != "stable"} == set(status) - systems


def test_selvam_has_a_prescription_per_drug_start(demo_ward):
    c, out = demo_ward
    docs = c.get(f"/patients/{out['selvam']['patient_id']}/documents").json()
    rx = sorted((d["document_date"], d["kind"]) for d in docs if d["kind"] == "prescription")
    assert rx == [(e["date"], "prescription") for e in demo.EVENTS]
    assert sum(d["kind"] == "lab_report" for d in docs) == 9
    first = next(d for d in docs if d["kind"] == "prescription")
    assert c.get(f"/documents/{first['id']}/file").content.startswith(b"%PDF")


# ---------------------------------------------------------------- the command

@pytest.fixture
def old_database(tmp_path, monkeypatch):
    """A demo database created before step 7 (no patient_code, no doctor), used by the seed command."""
    monkeypatch.setenv("CHRONOTRACE_UPLOADS", str(tmp_path / "uploads"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as con:
        con.execute(text("CREATE TABLE patient (id INTEGER PRIMARY KEY, name TEXT, sex TEXT, birth_year INTEGER)"))
    SQLModel.metadata.create_all(engine)             # the other tables; patient keeps its old columns
    db.set_engine(engine)
    app.dependency_overrides.pop(db.get_session, None)
    app.dependency_overrides[tagger_dep] = RuleTagger
    (tmp_path / "uploads" / "pages").mkdir(parents=True)
    (tmp_path / "uploads" / "pages" / "report-1-p1-110dpi.png").write_bytes(b"stale")
    yield tmp_path
    app.dependency_overrides.clear()


def test_the_command_refuses_an_outdated_database_then_resets_it(old_database, capsys):
    out_dir = old_database / "pdfs"
    assert seed_module.main(["--out", str(out_dir)]) == 1
    assert "patient.patient_code" in capsys.readouterr().out
    assert seed_module.main(["--reset", "--out", str(out_dir)]) == 0
    printed = capsys.readouterr().out
    assert "demo database and uploads reset" in printed
    lines = {ln.split()[0]: ln.split() for ln in printed.splitlines() if ln.startswith("CT-")}
    assert lines["CT-0002"][1:] == ["M.", "Rani", "0", "4", "0", "5", "2", "6"]   # 5 lab reports + 1 prescription
    assert lines["CT-0001"][3:] == ["0", "3", "2", "9", "3", "12"]           # 9 lab reports + 3 prescriptions
    assert not (old_database / "uploads" / "pages" / "report-1-p1-110dpi.png").exists()
    assert seed_module.main(["--out", str(out_dir)]) == 1                     # already seeded
    assert "--reset" in capsys.readouterr().out


def test_with_summary_saves_a_whole_history_summary(old_database, capsys):
    fake = use_llm(app, llm_dep, FakeLLM(R1_R9_SUMMARY))
    assert seed_module.main(["--reset", "--with-summary", "--out", str(old_database / "pdfs")]) == 0
    printed = capsys.readouterr().out
    assert "summary saved for CT-0001 (2023-06-12 to 2025-09-01, 9 reports) by fake-llm" in printed
    assert len(fake.prompts) == 1 and '"reports_in_period": 9' in fake.prompts[0]


def test_with_summary_reports_a_failed_summary(old_database, capsys):
    use_llm(app, llm_dep, FakeLLM(LLMError("503 UNAVAILABLE"), LLMError("503 UNAVAILABLE")))
    assert seed_module.main(["--reset", "--with-summary", "--out", str(old_database / "pdfs")]) == 1
    printed = capsys.readouterr().out
    assert "CT-0004" in printed                                      # the patients are seeded anyway
    assert "demo data seeded, but the summary was not saved (502)" in printed
