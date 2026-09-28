"""Trends, flags and medication response through the API, on the demo patient seeded by the real
upload + confirm endpoints (with the rule-based stand-in tagger; no model needed)."""

import pytest
from backend.demo import data as demo
from backend.demo.reports import write_pdf
from backend.demo.seed import seed
from backend.main import app
from tests.conftest import signed_in_client, use_fresh_database


def make_client():
    use_fresh_database()
    return signed_in_client()


@pytest.fixture(scope="module")
def pdf_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    for r in demo.REPORTS:
        write_pdf(r, out)
    return out


@pytest.fixture
def seeded(pdf_dir):
    """A fresh database per test: dependency overrides are global to the app, so clients cannot be shared."""
    c = make_client()
    ids = seed(c, pdf_dir)
    yield c, ids
    app.dependency_overrides.clear()


def upload_confirm(c, pid, path):
    with open(path, "rb") as f:
        rid = c.post(f"/patients/{pid}/reports", files={"file": (path.name, f, "application/pdf")}).json()["report"]["id"]
    assert c.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    return rid


def keyed(flags):
    return sorted((f["rule_id"], f["analyte_id"], f["date"], f["direction"], f["change_percent"],
                   (f["expected_effect"] or {}).get("note")) for f in flags)


def test_flags_before_r10(seeded):
    c, ids = seeded
    flags = c.get(f"/patients/{ids['patient_id']}/flags").json()["flags"]
    assert len(flags) == 5 and not any(f["rule_id"] == "KDIGO_RAPID_EGFR" for f in flags)
    assert [f["date"] for f in flags] == sorted((f["date"] for f in flags), reverse=True)      # newest first
    assert all(f["report_ids"] and set(f["report_ids"]) <= set(ids["report_ids"].values()) for f in flags)
    assert not any(f["analyte_id"] in ("potassium", "fasting_glucose", "uacr") for f in flags)
    ramipril = [f for f in flags if f["date"] == "2024-04-01" and f["rule_id"] == "RCV_PREV"]
    assert {(f["analyte_id"], f["change_percent"]) for f in ramipril} == {("creatinine", 16.2)}   # eGFR -16.5% < 20%


def test_trends_before_r10(seeded):
    c, ids = seeded
    t = {a["analyte_id"]: a for a in c.get(f"/patients/{ids['patient_id']}/trends").json()["analytes"]}
    e = t["egfr"]
    assert e["baseline"] == pytest.approx(78.42) and e["rcv_percent"] == 20.0 and e["rcv_status"] == "verified"
    assert (e["slope"]["status"], e["slope"]["span_days"], round(e["slope"]["per_year"], 1)) == ("not enough span", 321, -6.6)
    assert [p["in_window"] for p in e["points"]][4:6] == [[ids["event_ids"]["Ramipril"]], [ids["event_ids"]["Empagliflozin"]]]
    assert all(p["censored"] is False for a in t.values() for p in a["points"])


def test_medication_responses(seeded):
    c, ids = seeded
    got = {}
    for drug, eid in ids["event_ids"].items():
        r = c.get(f"/medications/{eid}/response").json()
        got[drug] = {a["analyte_id"]: a for a in r["analytes"]}
        assert r["event"]["event_id"] == eid and r["note"] is None
    m = got["Metformin"]["hba1c"]
    assert (m["status"], m["change_percent"], m["beyond_rcv"], m["confounders"]) == ("assessed", -15.9, True, [])
    assert m["before"]["value"] == 8.8 and m["cross_lab"] is True
    cr = got["Ramipril"]["creatinine"]
    assert (cr["change_percent"], cr["beyond_rcv"], cr["expected_effect"]["note"]) == (
        15.5, True, "within the ≤30% rise expected after ACEi/ARB start")
    assert cr["cross_lab"] is True
    em = got["Empagliflozin"]["egfr"]
    assert em["beyond_rcv"] is False and [(x["drug"], x["days_from_event"]) for x in em["confounders"]] == [("Ramipril", -63)]


def test_r10_upload_fires_the_kdigo_flag_and_unconfirmed_reports_never_count(pdf_dir):
    c = make_client()
    ids = seed(c, pdf_dir)
    pid = ids["patient_id"]
    before = c.get(f"/patients/{pid}/flags").json()["flags"]
    r10 = pdf_dir / f"selvam_R10_{demo.REPORTS[-1].date.isoformat()}.pdf"
    with open(r10, "rb") as f:
        rid = c.post(f"/patients/{pid}/reports", files={"file": (r10.name, f, "application/pdf")}).json()["report"]["id"]
    assert c.get(f"/patients/{pid}/flags").json()["flags"] == before            # uploaded, not confirmed yet
    assert c.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    after = c.get(f"/patients/{pid}/flags").json()["flags"]
    assert len(after) == 6
    kdigo = [f for f in after if f["rule_id"] == "KDIGO_RAPID_EGFR"]
    assert len(kdigo) == 1 and kdigo[0]["compared"]["slope"]["span_days"] == 503
    assert round(kdigo[0]["compared"]["slope"]["per_year"], 1) == -7.1 and kdigo[0]["level"] == "guideline"
    app.dependency_overrides.clear()


def test_upload_order_does_not_change_the_results(seeded, pdf_dir):
    c, ids = seeded
    expected_flags = keyed(c.get(f"/patients/{ids['patient_id']}/flags").json()["flags"])
    c2 = make_client()
    pid = c2.post("/patients", json=demo.PATIENT).json()["id"]
    for r in reversed(demo.REPORTS[:9]):                                         # oldest report uploaded last
        upload_confirm(c2, pid, pdf_dir / f"selvam_{r.id}_{r.date.isoformat()}.pdf")
    for e in reversed(demo.EVENTS):
        c2.post(f"/patients/{pid}/medications", json=e)
    assert keyed(c2.get(f"/patients/{pid}/flags").json()["flags"]) == expected_flags
    app.dependency_overrides.clear()


def test_deleting_a_medication_recomputes(pdf_dir):
    c = make_client()
    ids = seed(c, pdf_dir)
    pid = ids["patient_id"]
    assert any(f["expected_effect"] and f["expected_effect"]["drug"] == "Ramipril"
               for f in c.get(f"/patients/{pid}/flags").json()["flags"])
    assert c.delete(f"/medications/{ids['event_ids']['Ramipril']}").status_code == 204
    flags = c.get(f"/patients/{pid}/flags").json()["flags"]
    assert not any(f["expected_effect"] and f["expected_effect"]["drug"] == "Ramipril" for f in flags)
    app.dependency_overrides.clear()


def test_not_found(seeded):
    c, _ = seeded
    assert c.get("/patients/999/trends").status_code == 404
    assert c.get("/patients/999/flags").status_code == 404
    assert c.get("/medications/999/response").status_code == 404
