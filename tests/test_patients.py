"""Patient codes, photos, and the patient list's flag counts and sort orders (step 7)."""

import datetime as dt

import pytest
from backend.demo import data as demo
from backend.demo.reports import write_pdf
from backend.demo.seed import seed
from backend.main import app, needs_review_key
from backend.schemas import PatientListItem
from tests.conftest import FIXTURES, signed_in_client, use_fresh_database

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def new_patient(c, name, sex="female", birth_year=1970):
    return c.post("/patients", json={"name": name, "sex": sex, "birth_year": birth_year}).json()


def upload_confirm(c, pid, path):
    with open(path, "rb") as f:
        rid = c.post(f"/patients/{pid}/reports", files={"file": (path.name, f, "application/pdf")}).json()["report"]["id"]
    assert c.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    return rid


# ---------------------------------------------------------------- codes

def test_codes_are_sequential_and_unique_across_doctors(client, other_doctor):
    a1, a2 = new_patient(client, "One"), new_patient(client, "Two")
    b1 = new_patient(other_doctor, "Three")
    assert [a1["patient_code"], a2["patient_code"], b1["patient_code"]] == ["CT-0001", "CT-0002", "CT-0003"]
    assert [p["patient_code"] for p in client.get("/patients?sort=name").json()] == ["CT-0001", "CT-0002"]


# ---------------------------------------------------------------- photos

def test_photo_is_404_until_one_is_uploaded(client):
    pid = new_patient(client, "Photo")["id"]
    assert client.get(f"/patients/{pid}/photo").status_code == 404
    r = client.post(f"/patients/{pid}/photo", files={"file": ("face.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["has_photo"] is True
    got = client.get(f"/patients/{pid}/photo")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    # A new photo replaces the old one, whatever its type.
    client.post(f"/patients/{pid}/photo", files={"file": ("face.jpg", JPG, "image/jpeg")})
    got = client.get(f"/patients/{pid}/photo")
    assert got.content == JPG and got.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("name,data,status", [
    ("face.png", b"not an image", 415),               # checked by content, not by name
    ("report.pdf", b"%PDF-1.4 ...", 415),
    ("big.png", PNG + b"\x00" * (5 * 1024 * 1024), 413),
], ids=["not-an-image", "pdf", "over-5-mb"])
def test_photo_type_and_size(client, name, data, status):
    pid = new_patient(client, "Photo")["id"]
    assert client.post(f"/patients/{pid}/photo", files={"file": (name, data, "image/png")}).status_code == status
    assert client.get(f"/patients/{pid}/photo").status_code == 404


def test_another_doctors_photo_is_404(client, other_doctor):
    pid = new_patient(client, "Photo")["id"]
    client.post(f"/patients/{pid}/photo", files={"file": ("face.png", PNG, "image/png")})
    assert other_doctor.get(f"/patients/{pid}/photo").status_code == 404
    assert other_doctor.post(f"/patients/{pid}/photo", files={"file": ("x.png", PNG, "image/png")}).status_code == 404


# ---------------------------------------------------------------- list counts and sort

@pytest.fixture(scope="module")
def pdf_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    for r in demo.REPORTS:
        write_pdf(r, out)
    return out


@pytest.fixture
def ward(pdf_dir, tmp_path):
    """The seeded demo patient (R1-R9, 5 flags), a patient with one report, and one with none."""
    use_fresh_database(tmp_path / "uploads")
    c = signed_in_client()
    ids = seed(c, pdf_dir)
    one = new_patient(c, "Anand", sex="male", birth_year=1980)["id"]
    upload_confirm(c, one, FIXTURES / "demo_t2d_ckd_1.pdf")
    none = new_patient(c, "Zara")["id"]
    yield c, ids["patient_id"], one, none
    app.dependency_overrides.clear()


def test_list_counts_match_the_flags_endpoint(ward):
    c, selvam, one, none = ward
    items = {p["id"]: p for p in c.get("/patients").json()}
    flags = c.get(f"/patients/{selvam}/flags").json()["flags"]
    s = items[selvam]
    assert s["guideline_flags"] == sum(f["level"] == "guideline" for f in flags)
    assert s["change_flags"] == sum(f["level"] == "change" and f["expected_effect"] is None for f in flags)
    assert s["expected_flags"] == sum(f["level"] == "change" and f["expected_effect"] is not None for f in flags)
    assert s["guideline_flags"] + s["change_flags"] + s["expected_flags"] == len(flags) == 5
    assert s["expected_flags"] >= 1                          # the creatinine rise after Ramipril
    dates = {p["date"] for a in c.get(f"/patients/{selvam}/timeline").json()["analytes"] for p in a["points"]}
    assert s["report_count"] == 9 and s["lab_count"] == 3
    assert s["latest_report_date"] == max(dates)
    assert (items[one]["report_count"], items[one]["lab_count"]) == (1, 1)
    assert (items[none]["report_count"], items[none]["lab_count"], items[none]["latest_report_date"]) == (0, 0, None)
    assert (items[none]["guideline_flags"], items[none]["change_flags"], items[none]["expected_flags"]) == (0, 0, 0)


def test_sort_orders(ward):
    c, selvam, one, none = ward
    order = lambda sort: [p["id"] for p in c.get(f"/patients?sort={sort}").json()]   # noqa: E731
    assert order("needs_review") == [selvam, one, none] == [p["id"] for p in c.get("/patients").json()]
    assert order("name") == [one, selvam, none]              # Anand, K. Selvam, Zara
    dates = {p["id"]: p["latest_report_date"] for p in c.get("/patients").json()}
    newest_first = sorted([selvam, one], key=lambda i: dates[i], reverse=True) + [none]
    assert order("latest_report") == newest_first
    assert c.get("/patients?sort=flags").status_code == 422


def test_needs_review_ranks_guideline_then_change_then_latest_report():
    def item(i, g, ch, d):
        return PatientListItem(id=i, patient_code=f"CT-{i:04d}", name=str(i), sex="male", birth_year=1970,
                               conditions=[], has_photo=False, guideline_flags=g, change_flags=ch, expected_flags=0,
                               latest_report_date=d, report_count=0, lab_count=0)
    items = [item(1, 0, 5, dt.date(2025, 1, 1)), item(2, 1, 0, None), item(3, 0, 5, dt.date(2025, 6, 1)),
             item(4, 0, 0, dt.date(2026, 1, 1)), item(5, 0, 5, dt.date(2025, 6, 1))]
    assert [i.id for i in sorted(items, key=needs_review_key, reverse=True)] == [2, 3, 5, 1, 4]
