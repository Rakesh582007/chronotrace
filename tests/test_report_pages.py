"""Report page preview (PNG at 110 dpi) and each observation's box on the page (step 7)."""

import io

import pdfplumber
import pytest
from PIL import Image

from backend import main, storage
from tests.conftest import FIXTURES

SCALE = 110 / 72


def upload(c, name="demo_t2d_ckd_1.pdf"):
    pid = c.post("/patients", json={"name": "Pages", "sex": "male", "birth_year": 1966}).json()["id"]
    with open(FIXTURES / name, "rb") as f:
        r = c.post(f"/patients/{pid}/reports", files={"file": (name, f, "application/pdf")})
    assert r.status_code == 201, r.text
    return pid, r.json()


@pytest.mark.parametrize("name", ["demo_t2d_ckd_1.pdf", "real_layout.pdf", "edge_cases.pdf"])
def test_each_bbox_holds_its_row_on_the_page(client, name):
    _, d = upload(client, name)
    rep = d["report"]
    with pdfplumber.open(FIXTURES / name) as pdf:
        assert (rep["page_width"], rep["page_height"]) == (round(pdf.pages[0].width, 1), round(pdf.pages[0].height, 1))
        assert d["observations"]
        for o in d["observations"]:
            x0, top, x1, bottom = o["bbox"]
            assert 0 <= x0 < x1 <= rep["page_width"] and 0 <= top < bottom <= rep["page_height"], o
            page = pdf.pages[o["page"] - 1]
            inside = page.within_bbox((x0 - 0.5, top - 0.5, x1 + 0.5, bottom + 0.5)).extract_text()
            assert o["test_text"].split()[0] in inside and o["value_text"] in inside, (o["test_text"], inside)


def test_page_png_is_110_dpi_and_cached(client, monkeypatch):
    _, d = upload(client)
    rep = d["report"]
    r = client.get(f"/reports/{rep['id']}/pages/1.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (round(rep["page_width"] * SCALE), round(rep["page_height"] * SCALE))
    assert (storage.root() / "pages").exists()

    def no_render(*a, **k):
        raise AssertionError("rendered again instead of using the cache")
    monkeypatch.setattr(main.pdfplumber, "open", no_render)
    assert client.get(f"/reports/{rep['id']}/pages/1.png").content == r.content


def test_page_numbers_and_scoping(client, other_doctor):
    _, d = upload(client)
    rid, pages = d["report"]["id"], d["report"]["pages"]
    assert client.get(f"/reports/{rid}/pages/0.png").status_code == 404
    assert client.get(f"/reports/{rid}/pages/{pages + 1}.png").status_code == 404
    assert client.get(f"/reports/{rid}/pages/one.png").status_code == 422
    assert other_doctor.get(f"/reports/{rid}/pages/1.png").status_code == 404


def test_missing_pdf_is_404(client):
    pid, d = upload(client)
    (doc,) = client.get(f"/patients/{pid}/documents").json()
    storage.remove(f"documents/{doc['id']}-{doc['sha256'][:12]}.pdf")
    r = client.get(f"/reports/{d['report']['id']}/pages/1.png")
    assert r.status_code == 404 and "not stored" in r.json()["detail"]


def test_deleting_the_report_removes_its_cached_pages(client):
    pid, d = upload(client)
    assert client.get(f"/reports/{d['report']['id']}/pages/1.png").status_code == 200
    (doc,) = client.get(f"/patients/{pid}/documents").json()
    assert client.delete(f"/documents/{doc['id']}").status_code == 204
    assert list((storage.root() / "pages").glob("*")) == []


def test_a_row_added_by_the_doctor_has_no_bbox(client):
    _, d = upload(client, "real_layout.pdf")
    rid = d["report"]["id"]
    line = d["skipped"][0]
    r = client.post(f"/reports/{rid}/confirm", json={"add": [
        {"page": line["page"], "line": line["line"], "test_text": "SERUM POTASSIUM", "value_text": "4.9",
         "unit_text": "mmol/l"}]})
    assert r.status_code == 200, r.text
    added = next(o for o in r.json()["observations"] if o["test_text"] == "SERUM POTASSIUM" and o["edited"])
    assert added["bbox"] is None
