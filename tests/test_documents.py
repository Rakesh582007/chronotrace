"""Documents: prescriptions and doctor's notes are stored, never parsed; lab reports keep their PDF (step 7)."""

import pytest
from backend import storage
from tests.conftest import FIXTURES

PDF = (FIXTURES / "demo_t2d_ckd_2.pdf").read_bytes()      # a lab report PDF: as a prescription it must not be parsed
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x02" * 64


def new_patient(c, name="Doc Patient"):
    return c.post("/patients", json={"name": name, "sex": "female", "birth_year": 1970}).json()["id"]


def post_doc(c, pid, data, name="rx.pdf", kind="prescription", **form):
    return c.post(f"/patients/{pid}/documents", data={"kind": kind, **form}, files={"file": (name, data, "x/y")})


def upload_report(c, pid, name="demo_t2d_ckd_1.pdf"):
    with open(FIXTURES / name, "rb") as f:
        return c.post(f"/patients/{pid}/reports", files={"file": (name, f, "application/pdf")})


def stored_files():
    return sorted(p.name for p in (storage.root() / "documents").glob("*")) if (storage.root() / "documents").exists() else []


# ---------------------------------------------------------------- upload

@pytest.mark.parametrize("data,name,media", [(PDF, "rx.pdf", "application/pdf"), (PNG, "rx.png", "image/png"),
                                             (JPG, "rx.jpg", "image/jpeg")], ids=["pdf", "png", "jpg"])
def test_upload_and_download(client, data, name, media):
    pid = new_patient(client)
    r = post_doc(client, pid, data, name)
    assert r.status_code == 201
    d = r.json()
    assert (d["kind"], d["filename"], d["size"], d["report_id"], d["report_status"], d["document_date"]) == (
        "prescription", name, len(data), None, None, None)
    got = client.get(f"/documents/{d['id']}/file")
    assert got.status_code == 200 and got.content == data and got.headers["content-type"].startswith(media)
    assert got.headers["content-disposition"].startswith("inline") and name in got.headers["content-disposition"]


def test_a_stored_pdf_is_never_parsed(client):
    pid = new_patient(client)
    assert post_doc(client, pid, PDF, kind="doctor_note", document_date="2025-02-03").json()["document_date"] == "2025-02-03"
    listed = client.get("/patients").json()[0]
    assert listed["report_count"] == 0
    assert client.get(f"/patients/{pid}/timeline").json()["analytes"] == []


@pytest.mark.parametrize("form,status", [
    ({"kind": "lab_report"}, 422),                    # lab reports go through POST /patients/{id}/reports
    ({"kind": "scan"}, 422),
    ({}, 422),
    ({"kind": "prescription", "document_date": "not a date"}, 422),
], ids=["lab-report", "unknown-kind", "no-kind", "bad-date"])
def test_upload_form_is_checked(client, form, status):
    pid = new_patient(client)
    r = client.post(f"/patients/{pid}/documents", data=form, files={"file": ("rx.pdf", PDF, "application/pdf")})
    assert r.status_code == status
    assert stored_files() == []


@pytest.mark.parametrize("data,status", [
    (b"GIF89a....", 415), (b"plain text", 415), (b"%PDF" + b"\x00" * (15 * 1024 * 1024), 413),
], ids=["gif", "text", "over-15-mb"])
def test_type_and_size(client, data, status):
    pid = new_patient(client)
    assert post_doc(client, pid, data).status_code == status
    assert client.get(f"/patients/{pid}/documents").json() == [] and stored_files() == []


def test_duplicate_is_409_for_the_same_doctor_only(client, other_doctor):
    a1, a2 = new_patient(client), new_patient(client, "Other")
    first = post_doc(client, a1, PNG).json()
    dup = post_doc(client, a2, PNG, name="again.png", kind="doctor_note")
    assert dup.status_code == 409
    assert dup.json()["detail"] == {"message": "this file was already uploaded", "document_id": first["id"],
                                    "patient_id": a1}
    # Another doctor's identical file is not a duplicate of A's, and A's ids are not revealed.
    assert post_doc(other_doctor, new_patient(other_doctor), PNG).status_code == 201


# ---------------------------------------------------------------- lab reports

def test_lab_report_upload_creates_a_document(client):
    pid = new_patient(client)
    rep = upload_report(client, pid).json()["report"]
    (doc,) = client.get(f"/patients/{pid}/documents").json()
    assert (doc["kind"], doc["report_id"], doc["report_status"], doc["sha256"]) == (
        "lab_report", rep["id"], "extracted", rep["file_sha256"])
    assert doc["document_date"] == rep["collected_at"] and doc["filename"] == rep["filename"]
    assert client.get(f"/documents/{doc['id']}/file").content == (FIXTURES / "demo_t2d_ckd_1.pdf").read_bytes()


def test_rejected_report_leaves_no_document(client):
    pid = new_patient(client)
    assert upload_report(client, pid, "scanned.pdf").status_code == 422
    assert client.get(f"/patients/{pid}/documents").json() == [] and stored_files() == []


def test_list_is_newest_first(client):
    pid = new_patient(client)
    post_doc(client, pid, PNG)
    upload_report(client, pid)
    post_doc(client, pid, JPG, "n.jpg", "doctor_note")
    kinds = [d["kind"] for d in client.get(f"/patients/{pid}/documents").json()]
    assert kinds == ["doctor_note", "lab_report", "prescription"]


# ---------------------------------------------------------------- delete

def test_delete_a_prescription_removes_the_file(client):
    pid = new_patient(client)
    d = post_doc(client, pid, PNG).json()
    assert len(stored_files()) == 1
    assert client.delete(f"/documents/{d['id']}").status_code == 204
    assert client.get(f"/documents/{d['id']}/file").status_code == 404
    assert client.get(f"/patients/{pid}/documents").json() == [] and stored_files() == []
    assert post_doc(client, pid, PNG).status_code == 201                  # no longer a duplicate


def test_delete_an_unconfirmed_lab_report_removes_the_report(client):
    pid = new_patient(client)
    rid = upload_report(client, pid).json()["report"]["id"]
    (doc,) = client.get(f"/patients/{pid}/documents").json()
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert client.get(f"/reports/{rid}").status_code == 404 and stored_files() == []
    assert upload_report(client, pid).status_code == 201                  # the same PDF can be uploaded again


def test_a_confirmed_lab_report_cannot_be_deleted(client):
    pid = new_patient(client)
    rid = upload_report(client, pid).json()["report"]["id"]
    assert client.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    (doc,) = client.get(f"/patients/{pid}/documents").json()
    r = client.delete(f"/documents/{doc['id']}")
    assert r.status_code == 409 and r.json()["detail"]["report_id"] == rid
    assert client.get(f"/reports/{rid}").status_code == 200 and len(stored_files()) == 1


def test_another_doctor_gets_404(client, other_doctor):
    pid = new_patient(client)
    d = post_doc(client, pid, PNG).json()
    b = other_doctor
    assert b.get(f"/patients/{pid}/documents").status_code == 404
    assert b.get(f"/documents/{d['id']}/file").status_code == 404
    assert b.delete(f"/documents/{d['id']}").status_code == 404
    assert post_doc(b, pid, JPG).status_code == 404
    assert client.get(f"/documents/{d['id']}/file").status_code == 200
