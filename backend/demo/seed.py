"""Seed the demo patients through the real API.  Usage:  python -m backend.demo.seed [--reset]

Signs in as the demo doctor (.env) and creates four synthetic patients through POST /patients, uploading
and confirming their reports through POST /patients/{id}/reports and /reports/{id}/confirm (the real
extraction model and normalisation):

  CT-0001 K. Selvam  R1-R9 confirmed, three medication starts, a prescription PDF for each start;
                     R10 stays a PDF in backend/demo/generated/ (git-ignored) for the live upload.
  CT-0002 M. Rani    4 reports from 2 labs, 2 change flags (TSH, free T4).
  CT-0003 J. Arul    1 report.
  CT-0004 S. Priya   3 reports from 1 lab, no flags.

--reset drops and recreates every table of the demo database and empties the uploads folder (documents,
photos, rendered pages). The database is the API's (CHRONOTRACE_DB, default backend/chronotrace.db).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import data as demo
from .patients import OTHERS, OtherPatient, rows_a, rows_b
from .reports import SELVAM, draw_a, draw_b, write_pdf, write_prescription

OUT_DIR = Path(__file__).resolve().parent / "generated"
HOW = {"BD": "1 tablet twice a day, after food", "OD": "1 tablet once a day, in the morning"}


def _check(r, expected: int, what: str):
    if r.status_code != expected:
        raise RuntimeError(f"{what} failed: {r.status_code} {r.text}")
    return r.json()


def _upload_confirm(client, pid: int, path: Path, what: str) -> int:
    with open(path, "rb") as f:
        up = _check(client.post(f"/patients/{pid}/reports", files={"file": (path.name, f, "application/pdf")}),
                    201, f"upload of {what}")
    rid = up["report"]["id"]
    _check(client.post(f"/reports/{rid}/confirm", json={}), 200, f"confirming {what}")
    return rid


def seed(client, out_dir: Path = OUT_DIR, upto: str = "R9") -> dict:
    """K. Selvam through the API with `client` (a signed-in TestClient or anything with .post/.get)."""
    ids = [r.id for r in demo.REPORTS]
    last = ids.index(upto)
    pid = _check(client.post("/patients", json=demo.PATIENT), 201, "creating K. Selvam")["id"]
    report_ids = {}
    live = None
    for i, rep in enumerate(demo.REPORTS):
        path = write_pdf(rep, out_dir)
        if i > last:
            live = live or path
            continue
        report_ids[rep.id] = _upload_confirm(client, pid, path, rep.id)
    event_ids, document_ids = {}, {}
    for e in demo.EVENTS:
        event_ids[e["drug"]] = _check(client.post(f"/patients/{pid}/medications", json=e), 201,
                                      f"adding {e['drug']}")["id"]
        date = demo._d(e["date"])
        dose, freq = e["dose_text"].rsplit(" ", 1)
        rx = write_prescription(out_dir / f"selvam_rx_{e['drug'].lower()}_{e['date']}.pdf", SELVAM, date,
                                f"Tab. {e['drug']}", dose, f"{HOW[freq]} ({freq})")
        with open(rx, "rb") as f:
            document_ids[e["drug"]] = _check(client.post(
                f"/patients/{pid}/documents", data={"kind": "prescription", "document_date": e["date"]},
                files={"file": (rx.name, f, "application/pdf")}), 201, f"prescription for {e['drug']}")["id"]
    return {"patient_id": pid, "report_ids": report_ids, "event_ids": event_ids, "document_ids": document_ids,
            "live_report": live}


def seed_other(client, p: OtherPatient, out_dir: Path = OUT_DIR) -> dict:
    pid = _check(client.post("/patients", json=p.record), 201, f"creating {p.record['name']}")["id"]
    report_ids = {}
    for v in p.visits:
        path = out_dir / f"{p.slug}_{v.id}_{v.date.isoformat()}.pdf"
        out_dir.mkdir(parents=True, exist_ok=True)
        if v.lab == "A":
            draw_a(path, p.header, v.date, rows_a(p, v))
        else:
            draw_b(path, p.header, v.date, rows_b(p, v))
        report_ids[v.id] = _upload_confirm(client, pid, path, f"{p.record['name']} {v.id}")
    return {"patient_id": pid, "report_ids": report_ids}


def seed_demo(client, out_dir: Path = OUT_DIR) -> dict:
    """All four demo patients, in the order that gives CT-0001 .. CT-0004."""
    out = {"selvam": seed(client, out_dir)}
    for p in OTHERS:
        out[p.slug] = seed_other(client, p, out_dir)
    return out


def clear_uploads() -> None:
    from .. import storage

    for sub in ("documents", "photos", "pages"):
        shutil.rmtree(storage.root() / sub, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed the four demo patients through the API.")
    ap.add_argument("--reset", action="store_true",
                    help="drop and recreate the demo database and empty the uploads folder first")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="where to write the PDFs (default: git-ignored)")
    args = ap.parse_args(argv)

    from fastapi.testclient import TestClient

    from ..config import setting
    from ..db import SchemaError, check_schema, get_engine, reset_schema
    from ..main import app

    engine = get_engine()
    if args.reset:
        reset_schema(engine)
        clear_uploads()
        print("demo database and uploads reset")
    else:
        try:
            check_schema(engine)
        except SchemaError as e:
            print(e)
            return 1

    with TestClient(app) as client:                  # runs the app's startup: settings check, demo doctor
        login = client.post("/auth/login", json={"username": setting("DEMO_DOCTOR_USER"),
                                                 "password": setting("DEMO_DOCTOR_PASSWORD")})
        token = _check(login, 200, "signing in as the demo doctor")["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        if client.get("/patients").json():
            print("the demo doctor already has patients; run with --reset to recreate the demo data")
            return 1
        out = seed_demo(client, args.out)
        docs = {p["id"]: len(client.get(f"/patients/{p['id']}/documents").json())
                for p in client.get("/patients").json()}
        print(f"{'code':<8} {'patient':<11} {'guideline':>9} {'change':>6} {'expected':>8} {'reports':>7} "
              f"{'labs':>4} {'documents':>9}")
        for p in sorted(client.get("/patients").json(), key=lambda p: p["patient_code"]):
            print(f"{p['patient_code']:<8} {p['name']:<11} {p['guideline_flags']:>9} {p['change_flags']:>6} "
                  f"{p['expected_flags']:>8} {p['report_count']:>7} {p['lab_count']:>4} {docs[p['id']]:>9}")
        print(f"live upload for the demo: {out['selvam']['live_report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
