"""Seed the demo patient through the real API.  Usage:  python -m backend.demo.seed [--reset]

Creates K. Selvam, renders R1-R10 as PDFs, uploads and confirms R1-R9 through POST /patients/{id}/reports
and /reports/{id}/confirm (the real extraction model and normalisation), adds the three medication starts,
and leaves R10 as a PDF in backend/demo/generated/ (git-ignored) for the live upload in the demo.
The database is the API's (CHRONOTRACE_DB, default backend/chronotrace.db, git-ignored).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import data as demo
from .reports import write_pdf

OUT_DIR = Path(__file__).resolve().parent / "generated"


def seed(client, out_dir: Path = OUT_DIR, upto: str = "R9") -> dict:
    """Seed through the API with `client` (a TestClient or anything with .post/.get). Returns the ids."""
    ids = [r.id for r in demo.REPORTS]
    last = ids.index(upto)
    r = client.post("/patients", json=demo.PATIENT)
    if r.status_code != 201:
        raise RuntimeError(f"could not create the patient: {r.status_code} {r.text}")
    pid = r.json()["id"]
    report_ids = {}
    live = None
    for i, rep in enumerate(demo.REPORTS):
        path = write_pdf(rep, out_dir)
        if i > last:
            live = live or path
            continue
        with open(path, "rb") as f:
            up = client.post(f"/patients/{pid}/reports", files={"file": (path.name, f, "application/pdf")})
        if up.status_code != 201:
            raise RuntimeError(f"upload of {rep.id} failed: {up.status_code} {up.text}")
        rid = up.json()["report"]["id"]
        conf = client.post(f"/reports/{rid}/confirm", json={})
        if conf.status_code != 200:
            raise RuntimeError(f"confirming {rep.id} failed: {conf.status_code} {conf.text}")
        report_ids[rep.id] = rid
    event_ids = {}
    for e in demo.EVENTS:
        r = client.post(f"/patients/{pid}/medications", json=e)
        if r.status_code != 201:
            raise RuntimeError(f"adding {e['drug']} failed: {r.status_code} {r.text}")
        event_ids[e["drug"]] = r.json()["id"]
    return {"patient_id": pid, "report_ids": report_ids, "event_ids": event_ids, "live_report": live}


def _remove_existing(name: str) -> int:
    """Delete earlier demo patients with this name, with their reports, observations and medications."""
    from sqlmodel import Session, select

    from ..db import get_engine
    from ..db.models import MedicationEvent, Observation, Patient, Report

    removed = 0
    with Session(get_engine()) as s:
        for p in s.exec(select(Patient).where(Patient.name == name)).all():
            for rep in s.exec(select(Report).where(Report.patient_id == p.id)).all():
                for o in s.exec(select(Observation).where(Observation.report_id == rep.id)).all():
                    s.delete(o)
                s.delete(rep)
            for m in s.exec(select(MedicationEvent).where(MedicationEvent.patient_id == p.id)).all():
                s.delete(m)
            s.delete(p)
            removed += 1
        s.commit()
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed the demo patient through the API.")
    ap.add_argument("--reset", action="store_true", help="first delete an earlier demo patient of the same name")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="where to write the PDFs (default: git-ignored)")
    args = ap.parse_args(argv)

    from fastapi.testclient import TestClient

    from ..main import app

    client = TestClient(app)
    existing = [p for p in client.get("/patients").json() if p["name"] == demo.PATIENT["name"]]
    if existing and not args.reset:
        print(f"{demo.PATIENT['name']} already exists (patient {existing[0]['id']}); run with --reset to recreate.")
        return 1
    if args.reset:
        print(f"removed {_remove_existing(demo.PATIENT['name'])} earlier demo patient(s)")
    out = seed(client, args.out)
    flags = client.get(f"/patients/{out['patient_id']}/flags").json()["flags"]
    print(f"patient {out['patient_id']}: reports {', '.join(f'{k}={v}' for k, v in out['report_ids'].items())}")
    print(f"medications: {', '.join(f'{k}={v}' for k, v in out['event_ids'].items())}")
    print(f"flags now: {len(flags)} ({sum(f['rule_id'] == 'KDIGO_RAPID_EGFR' for f in flags)} KDIGO)")
    print(f"live upload for the demo: {out['live_report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
