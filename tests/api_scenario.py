"""The documented API scenario: the demo patient (type 2 diabetes + CKD) from upload to timeline.

Used twice, so docs/api.md and the code cannot drift apart:
- tests/test_api_contract.py runs it (with the rule-based test tagger) and checks that every example
  in docs/api.md has the same keys and value types as the real responses;
- `python tests/api_scenario.py` runs it with the real NER model and rewrites the JSON example blocks
  in docs/api.md (the text around them is left alone).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
DOC = ROOT / "docs" / "api.md"
EXAMPLE = re.compile(r"(<!-- example: (\S+) (request|response)(?: (\d{3}))? -->\s*```json\n)(.*?)(\n```)", re.S)

PATIENT = {"name": "Ravi Kumar", "sex": "male", "birth_year": 1966, "conditions": ["type 2 diabetes", "CKD stage 3"]}


def _upload(client, pid, name):
    with open(FIXTURES / name, "rb") as f:
        return client.post(f"/patients/{pid}/reports", files={"file": (name, f, "application/pdf")})


def _skipped_line(detail, prefix):
    return next(s for s in detail["skipped"] if s["text"].startswith(prefix))


def run_scenario(client, patient: dict = PATIENT) -> dict:
    """{example name: {"request"?, "response", "status"}} for every documented example."""
    out = {}

    def keep(name, r, request=None):
        out[name] = {"response": r.json(), "status": r.status_code}
        if request is not None:
            out[name]["request"] = request
        return r.json()

    pid = keep("create-patient", client.post("/patients", json=patient), patient)["id"]
    keep("list-patients", client.get("/patients"))
    d1 = keep("upload-report", _upload(client, pid, "demo_t2d_ckd_1.pdf"))
    rid1 = d1["report"]["id"]
    keep("get-report", client.get(f"/reports/{rid1}"))

    obs = {o["test_text"]: o for o in d1["observations"]}
    ketones = _skipped_line(d1, "URINE KETONES")
    confirm = {"observations": [{"id": obs["VITAMIN B12"]["id"], "reject": True},
                                {"id": obs["POTASSIUM - SERUM"]["id"], "value_text": "5.1", "unit_text": "mmol/L"}],
               "add": [{"page": ketones["page"], "line": ketones["line"], "test_text": "URINE KETONES",
                        "value_text": "Negative", "range_text": "Negative"}]}
    keep("confirm-report", client.post(f"/reports/{rid1}/confirm", json=confirm), confirm)

    d2 = _upload(client, pid, "demo_t2d_ckd_2.pdf").json()
    uacr = _skipped_line(d2, "URINE ALBUMIN/CREATININE RATIO")        # printed ">300": the model sees no value
    client.post(f"/reports/{d2['report']['id']}/confirm", json={"add": [
        {"page": uacr["page"], "line": uacr["line"], "test_text": "URINE ALBUMIN/CREATININE RATIO",
         "value_text": ">300", "unit_text": "mg/g", "range_text": "Less than 30"}]})
    keep("timeline", client.get(f"/patients/{pid}/timeline"))

    keep("upload-duplicate", _upload(client, pid, "demo_t2d_ckd_1.pdf"))
    keep("upload-scanned", _upload(client, pid, "scanned.pdf"))
    keep("upload-unreadable", client.post(f"/patients/{pid}/reports", files={
        "file": ("broken.pdf", b"%PDF-1.4\nthis file was cut off during download", "application/pdf")}))
    keep("upload-not-pdf", client.post(f"/patients/{pid}/reports", files={"file": ("notes.txt", b"hello", "text/plain")}))
    keep("not-found", client.get("/patients/999/timeline"))

    undated = _upload(client, pid, "undated.pdf").json()
    keep("confirm-no-date", client.post(f"/reports/{undated['report']['id']}/confirm", json={}), {})
    p2 = client.post("/patients", json={**patient, "name": "Edge Case", "birth_year": 1967}).json()
    edge = _upload(client, p2["id"], "edge_cases.pdf").json()
    keep("confirm-needs-review", client.post(f"/reports/{edge['report']['id']}/confirm", json={}), {})
    keep("validation-error", client.post("/patients", json={**patient, "sex": "unknown"}))

    # Step 6: the demo patient K. Selvam, seeded through the same upload + confirm endpoints, then R10.
    import tempfile

    from backend.demo import data as demo
    from backend.demo.seed import seed

    ids = seed(client, Path(tempfile.mkdtemp(prefix="chronotrace-demo-")), upto="R10")
    sid = ids["patient_id"]
    statin = {"drug": "Atorvastatin", "change": "start", "dose_text": "10 mg OD", "date": "2024-08-01"}
    keep("add-medication", client.post(f"/patients/{sid}/medications", json=statin), statin)
    keep("list-medications", client.get(f"/patients/{sid}/medications"))
    keep("trends", client.get(f"/patients/{sid}/trends"))
    keep("flags", client.get(f"/patients/{sid}/flags"))
    keep("medication-response", client.get(f"/medications/{ids['event_ids']['Empagliflozin']}/response"))
    bad = {**statin, "date": "2999-01-01"}
    keep("medication-bad-date", client.post(f"/patients/{sid}/medications", json=bad), bad)
    assert demo.PATIENT["name"] == "K. Selvam"
    return out


def documented(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for _, name, kind, status, body, _ in EXAMPLE.findall(text):
        out.setdefault(name, {})[kind] = json.loads(body)
        if status:
            out[name]["status"] = int(status)
    return out


def rewrite_doc(results: dict) -> list[str]:
    """Replace every example block in docs/api.md with the recorded request/response. Returns missing names."""
    missing = []

    def sub(m):
        head, name, kind, status, _body, tail = m.groups()
        if name not in results:
            missing.append(name)
            return m.group(0)
        body = results[name]["request" if kind == "request" else "response"]
        if status:
            head = head.replace(f"{kind} {status}", f"{kind} {results[name]['status']}")
        return head + json.dumps(body, indent=2, ensure_ascii=False) + tail

    DOC.write_text(EXAMPLE.sub(sub, DOC.read_text(encoding="utf-8")), encoding="utf-8")
    return missing


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from backend import db
    from backend.main import app

    engine = db.make_engine("sqlite://")

    def session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[db.get_session] = session        # real model, throwaway database
    results = run_scenario(TestClient(app))
    missing = rewrite_doc(results)
    print(f"rewrote {len(results)} examples in {DOC}" + (f"; not in scenario: {missing}" if missing else ""))
    extra = set(results) - set(documented(DOC.read_text(encoding="utf-8")))
    if extra:
        print(f"recorded but not documented yet (add a marker for each): {sorted(extra)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
