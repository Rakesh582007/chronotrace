"""The four demo patients, seeded through the real API (with the rule-based stand-in tagger), and the seed
command's --reset on an outdated database (step 7)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from backend import db
from backend.demo import data as demo
from backend.demo import seed as seed_module
from backend.main import app, tagger_dep
from tests.conftest import RuleTagger, signed_in_client, use_fresh_database


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
        "CT-0002": ("M. Rani", 0, 2, 0, 4, 2, "2026-01-14"),
        "CT-0003": ("J. Arul", 0, 0, 0, 1, 1, "2025-08-05"),
        "CT-0004": ("S. Priya", 0, 0, 0, 3, 1, "2025-11-20"),
    }
    assert [p["patient_code"] for p in c.get("/patients").json()] == ["CT-0001", "CT-0002", "CT-0004", "CT-0003"]


def test_rani_has_one_flag_per_thyroid_value(demo_ward):
    c, out = demo_ward
    flags = c.get(f"/patients/{out['rani']['patient_id']}/flags").json()["flags"]
    assert sorted((f["rule_id"], f["analyte_id"], f["date"], f["change_percent"]) for f in flags) == [
        ("RCV_BASELINE", "free_t4", "2026-01-14", -22.4), ("RCV_PREV", "tsh", "2025-07-15", 73.1)]
    thyroid = next(s for s in c.get(f"/patients/{out['rani']['patient_id']}/systems").json()["systems"]
                   if s["id"] == "thyroid")
    assert thyroid["status"] == "changed" and thyroid["headline"]["latest"]["value"] == 3.4


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
    assert lines["CT-0002"][1:] == ["M.", "Rani", "0", "2", "0", "4", "2", "4"]          # her 4 lab reports
    assert lines["CT-0001"][3:] == ["0", "3", "2", "9", "3", "12"]           # 9 lab reports + 3 prescriptions
    assert not (old_database / "uploads" / "pages" / "report-1-p1-110dpi.png").exists()
    assert seed_module.main(["--out", str(out_dir)]) == 1                     # already seeded
    assert "--reset" in capsys.readouterr().out
