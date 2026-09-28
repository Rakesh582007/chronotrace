"""API tests on an in-memory database, with the rule-based stand-in tagger (tests/conftest.py)."""

import pytest

from tests.conftest import FIXTURES

DEMO = {"name": "Ravi Kumar", "sex": "male", "birth_year": 1966, "conditions": ["type 2 diabetes", "CKD stage 3"]}


def new_patient(client, **over):
    r = client.post("/patients", json={**DEMO, **over})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, patient_id, name):
    with open(FIXTURES / name, "rb") as f:
        return client.post(f"/patients/{patient_id}/reports", files={"file": (name, f, "application/pdf")})


def by_test(detail):
    return {o["test_text"]: o for o in detail["observations"]}


# ---------------------------------------------------------------- patients

def test_create_and_list_patients(client):
    p = new_patient(client)
    assert p == {"id": p["id"], **DEMO}
    assert client.get("/patients").json() == [p]


@pytest.mark.parametrize("body", [
    {**DEMO, "sex": "other"}, {**DEMO, "birth_year": 1800}, {**DEMO, "birth_year": 3000}, {**DEMO, "name": ""},
    {"name": "X", "sex": "male"},
])
def test_patient_validation(client, body):
    assert client.post("/patients", json=body).status_code == 422


# ---------------------------------------------------------------- upload

def test_upload_extracts_unconfirmed_observations(client):
    p = new_patient(client)
    r = upload(client, p["id"], "demo_t2d_ckd_1.pdf")
    assert r.status_code == 201, r.text
    d = r.json()
    rep = d["report"]
    assert (rep["status"], rep["layout"], rep["collected_at"], rep["date_label"], rep["lab"]) == (
        "extracted", "header", "2024-01-08", "Collected", "ASTERLANE DIAGNOSTICS")
    obs = by_test(d)
    assert obs["HB A1C"]["analyte_id"] == "hba1c" and obs["HB A1C"]["canonical_value"] == 8.4
    assert obs["HB A1C"]["status"] == "extracted" and obs["HB A1C"]["page"] == 1 and obs["HB A1C"]["line"] == 12
    assert obs["VITAMIN B12"]["status"] == "not_tracked" and obs["VITAMIN B12"]["analyte_id"] is None
    egfr = obs["eGFR (CKD-EPI 2021)"]
    assert egfr["value_text"] == "49" and egfr["canonical_value"] != 49 and "recomputed" in egfr["status_reason"]
    assert not any("Method" in o["test_text"] for o in d["observations"])     # rule tagger's fake test rejected
    assert d["counts"]["extracted"] == 8 and d["counts"]["not_tracked"] == 1     # vitamin B12
    # The rule tagger tags numbers in the patient block: skipped as page header, never results.
    # "Negative" / "Nil" are not values to it (nor to the model): skipped with the reason.
    reasons = {s["text"].split()[0] + " " + s["text"].split()[1]: s["reason"] for s in d["skipped"]}
    assert "did not tag the value cell 'Negative'" in reasons["URINE KETONES"]
    assert "did not tag the value cell 'Nil'" in reasons["URINE GLUCOSE"]
    assert {s["reason"] for s in d["skipped"] if not s["text"].startswith("URINE")} == {
        "page header: above the results table"}
    assert client.get(f"/reports/{rep['id']}").json() == d


def test_duplicate_upload_is_rejected(client):
    p = new_patient(client)
    first = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    r = upload(client, new_patient(client, name="Other")["id"], "demo_t2d_ckd_1.pdf")
    assert r.status_code == 409
    assert r.json()["detail"]["report_id"] == first["report"]["id"]


def test_upload_errors(client):
    p = new_patient(client)
    r = client.post(f"/patients/{p['id']}/reports", files={"file": ("x.txt", b"not a pdf", "text/plain")})
    assert r.status_code == 415
    r = upload(client, p["id"], "scanned.pdf")
    assert r.status_code == 422 and r.json()["detail"] == "scanned reports are not supported yet"
    assert upload(client, 999, "demo_t2d_ckd_1.pdf").status_code == 404
    assert client.get("/reports/999").status_code == 404


def test_edge_cases_through_the_api(client):
    p = new_patient(client, birth_year=1967)
    d = upload(client, p["id"], "edge_cases.pdf").json()
    assert (d["report"]["collected_at"], d["report"]["date_label"]) == ("2024-01-16", "Reported")
    obs = by_test(d)
    assert obs["TSH (ULTRASENSITIVE)"]["canonical_value"] == 3.2
    assert obs["SERUM SODIUM"]["status"] == "needs_review"
    looks = [s["text"] for s in d["skipped"] if s["reason"].startswith("looks like a result row")]
    for text in ("TRIGLYCERIDES >1000", "SERUM POTASSIUM Haemolysed", "URINE ALBUMIN/CREATININE RATIO <0.5",
                 "HBsAg Non Reactive", "URINE SUGAR Nil", "HIV I & II ANTIBODY Negative"):
        assert any(t.startswith(text) for t in looks), text     # each accounted for, with its reason


def test_doctor_adds_censored_and_text_values_from_skipped_lines(client):
    p = new_patient(client, birth_year=1967)
    d = upload(client, p["id"], "edge_cases.pdf").json()
    rid, obs = d["report"]["id"], by_test(d)
    line = {s["text"].split()[0]: s for s in d["skipped"]}
    add = [{"page": 1, "line": line["TRIGLYCERIDES"]["line"], "test_text": "TRIGLYCERIDES", "value_text": ">1000",
            "unit_text": "mg/dl"},
           {"page": 1, "line": line["HIV"]["line"], "test_text": "HIV I & II ANTIBODY", "value_text": "Negative",
            "range_text": "Negative"},
           {"page": 1, "line": line["SERUM"]["line"], "test_text": "SERUM POTASSIUM", "value_text": "Haemolysed",
            "unit_text": "mmol/l"}]
    r = client.post(f"/reports/{rid}/confirm", json={"add": add, "observations": [
        {"id": obs["SERUM SODIUM"]["id"], "unit_text": "mmol/L"}]})
    assert r.status_code == 422                          # potassium "Haemolysed" is not a number: needs review
    assert [o["test_text"] for o in r.json()["detail"]["observations"]] == ["SERUM POTASSIUM"]
    add[2]["value_text"] = "4.9"
    c = client.post(f"/reports/{rid}/confirm", json={"add": add, "observations": [
        {"id": obs["SERUM SODIUM"]["id"], "unit_text": "mmol/L"}]}).json()
    after = by_test(c)
    assert (after["TRIGLYCERIDES"]["comparator"], after["TRIGLYCERIDES"]["canonical_value"]) == (">", 1000)
    assert after["HIV I & II ANTIBODY"]["status"] == "not_tracked" and after["HIV I & II ANTIBODY"]["value_text"] == "Negative"
    assert after["SERUM POTASSIUM"]["canonical_value"] == 4.9


# ---------------------------------------------------------------- confirm and timeline

def test_confirm_blocks_on_needs_review_then_edit_reject_add(client):
    p = new_patient(client, birth_year=1967)
    d = upload(client, p["id"], "edge_cases.pdf").json()
    rid, obs = d["report"]["id"], by_test(d)

    r = client.post(f"/reports/{rid}/confirm", json={})
    assert r.status_code == 422
    assert {o["test_text"] for o in r.json()["detail"]["observations"]} == {"SERUM SODIUM"}
    assert client.get(f"/reports/{rid}").json()["report"]["status"] == "extracted"     # nothing saved

    potassium = next(s for s in d["skipped"] if "POTASSIUM" in s["text"])
    r = client.post(f"/reports/{rid}/confirm", json={
        "observations": [{"id": obs["SERUM SODIUM"]["id"], "unit_text": "mmol/L"},
                         {"id": obs["TSH (ULTRASENSITIVE)"]["id"], "reject": True}],
        "add": [{"page": potassium["page"], "line": potassium["line"], "test_text": "SERUM POTASSIUM",
                 "value_text": "4.9", "unit_text": "mmol/l"}]})
    assert r.status_code == 200, r.text
    c = r.json()
    after = by_test(c)
    assert c["report"]["status"] == "confirmed"
    assert after["SERUM SODIUM"]["status"] == "confirmed" and after["SERUM SODIUM"]["canonical_value"] == 138
    assert after["SERUM SODIUM"]["edited"] is True
    assert after["TSH (ULTRASENSITIVE)"]["status"] == "rejected"
    assert after["SERUM POTASSIUM"]["canonical_value"] == 4.9 and after["SERUM POTASSIUM"]["status"] == "confirmed"
    assert not any("POTASSIUM" in s["text"] for s in c["skipped"])
    assert any(s["text"].startswith("URINE SUGAR") for s in c["skipped"])       # still listed, not dropped


def test_confirm_requires_a_date_and_recomputes_egfr(client, tmp_path):
    p = new_patient(client, birth_year=1967)
    d = upload(client, p["id"], "edge_cases.pdf").json()
    rid, obs = d["report"]["id"], by_test(d)
    fix = [{"id": obs["SERUM SODIUM"]["id"], "reject": True}]
    before = obs["eGFR (CKD-EPI 2021)"]["canonical_value"]
    r = client.post(f"/reports/{rid}/confirm", json={
        "collected_at": "2024-01-15", "observations": fix + [{"id": obs["SERUM CREATININE"]["id"], "value_text": "1.9"}]})
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["report"]["collected_at"], c["report"]["date_label"]) == ("2024-01-15", "Entered by doctor")
    egfr = by_test(c)["eGFR (CKD-EPI 2021)"]
    assert egfr["status"] == "confirmed" and egfr["canonical_value"] < before


def test_unknown_ids_and_analytes_are_rejected(client):
    p = new_patient(client)
    rid = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()["report"]["id"]
    assert client.post(f"/reports/{rid}/confirm", json={"observations": [{"id": 99999}]}).status_code == 422
    obs_id = client.get(f"/reports/{rid}").json()["observations"][0]["id"]
    r = client.post(f"/reports/{rid}/confirm", json={"observations": [{"id": obs_id, "analyte_id": "ferritin"}]})
    assert r.status_code == 422


def test_doctor_can_map_or_unmap_a_test(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    obs = by_test(d)
    r = client.post(f"/reports/{d['report']['id']}/confirm", json={"observations": [
        {"id": obs["VITAMIN B12"]["id"], "analyte_id": "tsh", "unit_text": "mIU/L"},
        {"id": obs["TSH (ULTRASENSITIVE)"]["id"], "analyte_id": None}]})
    after = by_test(r.json())
    assert after["VITAMIN B12"]["analyte_id"] == "tsh" and after["VITAMIN B12"]["match"] == "doctor"
    assert after["TSH (ULTRASENSITIVE)"]["status"] == "not_tracked" and after["TSH (ULTRASENSITIVE)"]["analyte_id"] is None


def test_timeline_has_confirmed_values_with_their_source(client):
    p = new_patient(client)
    ids = []
    for name in ("demo_t2d_ckd_2.pdf", "demo_t2d_ckd_1.pdf"):          # uploaded out of date order
        d = upload(client, p["id"], name).json()
        ids.append(d["report"]["id"])
    assert client.get(f"/patients/{p['id']}/timeline").json()["analytes"] == []       # nothing confirmed yet
    for rid in ids:
        assert client.post(f"/reports/{rid}/confirm", json={}).status_code == 200

    t = client.get(f"/patients/{p['id']}/timeline").json()
    series = {s["analyte_id"]: s for s in t["analytes"]}
    assert t["patient"]["id"] == p["id"]
    assert [pt["value"] for pt in series["hba1c"]["points"]] == [8.4, 7.6]            # sorted by date
    assert [pt["date"] for pt in series["hba1c"]["points"]] == ["2024-01-08", "2024-04-11"]
    pt = series["creatinine"]["points"][0]
    assert (pt["report_id"], pt["lab"], pt["page"], pt["line"]) == (ids[1], "ASTERLANE DIAGNOSTICS", 1, 14)
    assert series["egfr"]["points"][0]["value_text"] == "49"
    assert series["egfr"]["canonical_unit"] == "mL/min/1.73m²"
    assert "vitamin" not in " ".join(series)
    assert client.get("/patients/999/timeline").status_code == 404


# ---------------------------------------------------------------- review findings (regressions)

def test_doctor_not_tracked_choice_survives_later_edits(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    rid, tsh = d["report"]["id"], by_test(d)["TSH (ULTRASENSITIVE)"]["id"]
    client.post(f"/reports/{rid}/confirm", json={"observations": [{"id": tsh, "analyte_id": None}]})
    c = client.post(f"/reports/{rid}/confirm", json={"observations": [{"id": tsh, "value_text": "2.9"}]}).json()
    t = by_test(c)["TSH (ULTRASENSITIVE)"]
    assert (t["status"], t["analyte_id"], t["match"], t["value_text"]) == ("not_tracked", None, "doctor", "2.9")
    assert "tsh" not in {s["analyte_id"] for s in client.get(f"/patients/{p['id']}/timeline").json()["analytes"]}


@pytest.mark.parametrize("data", [b"%PDF-1.4\nthis is not really a pdf\n",
                                  (FIXTURES / "demo_t2d_ckd_1.pdf").read_bytes()[:1500]])
def test_damaged_pdf_is_a_clear_422(client, data):
    p = new_patient(client)
    r = client.post(f"/patients/{p['id']}/reports", files={"file": ("bad.pdf", data, "application/pdf")})
    assert r.status_code == 422 and "damaged or password-protected" in r.json()["detail"]


def test_password_protected_pdf_is_a_clear_422(client, tmp_path):
    from reportlab.lib import pdfencrypt
    from reportlab.pdfgen import canvas
    path = tmp_path / "locked.pdf"
    c = canvas.Canvas(str(path), encrypt=pdfencrypt.StandardEncryption("secret", canPrint=0))
    c.drawString(100, 700, "HB A1C 7.1 %")
    c.save()
    p = new_patient(client)
    r = client.post(f"/patients/{p['id']}/reports", files={"file": ("locked.pdf", path.read_bytes(), "application/pdf")})
    assert r.status_code == 422 and "password-protected" in r.json()["detail"]


def test_simultaneous_duplicate_upload_is_409_not_500(client, monkeypatch):
    import backend.main as main
    p = new_patient(client)
    upload(client, p["id"], "demo_t2d_ckd_1.pdf")
    real, calls = main._raise_if_duplicate, []

    def first_check_misses(session, sha, doctor):  # as if the other request had not committed yet
        calls.append(sha)
        if len(calls) > 1:
            real(session, sha, doctor)
    monkeypatch.setattr(main, "_raise_if_duplicate", first_check_misses)
    r = upload(client, p["id"], "demo_t2d_ckd_1.pdf")
    assert r.status_code == 409 and len(calls) == 2


def test_add_must_point_to_a_free_line_of_the_report(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    rid, hba1c = d["report"]["id"], by_test(d)["HB A1C"]
    for add in [{"page": 1, "line": hba1c["line"], "test_text": "HB A1C", "value_text": "8.4", "unit_text": "%"},
                {"page": 9, "line": 5, "test_text": "HbA1c", "value_text": "9.9", "unit_text": "%"}]:
        r = client.post(f"/reports/{rid}/confirm", json={"add": [add]})
        assert r.status_code == 422 and r.json()["detail"]["lines"] == [{"page": add["page"], "line": add["line"]}]
    twice = {"page": 1, "line": 22, "test_text": "URINE KETONES", "value_text": "Negative"}
    assert client.post(f"/reports/{rid}/confirm", json={"add": [twice, twice]}).status_code == 422


@pytest.mark.parametrize("date", ["1950-01-01", "2999-01-01"])
def test_confirm_date_must_be_after_birth_and_not_in_the_future(client, date):
    p = new_patient(client)
    rid = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()["report"]["id"]
    r = client.post(f"/reports/{rid}/confirm", json={"collected_at": date})
    assert r.status_code == 422 and "between the patient's birth year and today" in r.json()["detail"]["message"]


def test_recomputed_egfr_has_no_comparator_even_if_printed_censored(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    rid, egfr = d["report"]["id"], by_test(d)["eGFR (CKD-EPI 2021)"]
    c = client.post(f"/reports/{rid}/confirm", json={"observations": [{"id": egfr["id"], "value_text": "<60"}]}).json()
    e = by_test(c)["eGFR (CKD-EPI 2021)"]
    assert (e["value_text"], e["comparator"], e["status"]) == ("<60", None, "confirmed")
    point = next(s for s in client.get(f"/patients/{p['id']}/timeline").json()["analytes"] if s["analyte_id"] == "egfr")
    assert point["points"][0]["comparator"] is None and point["points"][0]["value"] == e["canonical_value"]


def test_zero_creatinine_needs_review_instead_of_crashing(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    creat = by_test(d)["CREATININE - SERUM"]["id"]
    r = client.post(f"/reports/{d['report']['id']}/confirm", json={"observations": [{"id": creat, "value_text": "0"}]})
    assert r.status_code == 422
    assert r.json()["detail"]["observations"][0]["reason"] == "creatinine must be above 0 to compute eGFR"


def test_doctor_mapping_bun_keeps_the_urea_nitrogen_basis(client):
    p = new_patient(client)
    d = upload(client, p["id"], "demo_t2d_ckd_1.pdf").json()
    add = [{"page": 1, "line": 22, "test_text": "UREA NITROGEN (BUN)", "value_text": "14", "unit_text": "mg/dL",
            "analyte_id": "urea"},
           {"page": 1, "line": 23, "test_text": "URINE GLUCOSE", "value_text": "Nil"}]
    c = client.post(f"/reports/{d['report']['id']}/confirm", json={"add": add}).json()
    assert by_test(c)["UREA NITROGEN (BUN)"]["canonical_value"] == pytest.approx(14 * 2.1437)
