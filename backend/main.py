"""ChronoTrace API (steps 4-5). Run from the repo root:  uvicorn backend.main:app --reload

Endpoints are documented with full examples in docs/api.md; tests/test_api_contract.py checks
that every documented response has the same shape as the real one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import normalise as nm
from .db import get_session
from .db.models import Observation, Patient, Report
from .extraction import ScannedReportError, extract_report
from .extraction.tagger import Tagger, get_tagger
from .normalise.names import name_index
from .schemas import (ConfirmIn, Counts, ObservationOut, PatientIn, PatientOut, ReportDetail, ReportOut,
                      SkippedOut, Timeline, TimelinePoint, TimelineSeries)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ENTERED_BY_DOCTOR = "Entered by doctor"
UNREADABLE_PDF = "could not read this PDF: it is damaged or password-protected"

app = FastAPI(title="ChronoTrace API", version="0.4.0",
              description="Lab-report extraction, normalisation and timelines (see docs/api.md).")
app.add_middleware(CORSMiddleware,
                   allow_origins=os.environ.get("CHRONOTRACE_CORS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def tagger_dep() -> Tagger:
    return get_tagger()


# ---------------------------------------------------------------- helpers

def _patient_or_404(session: Session, patient_id: int) -> Patient:
    p = session.get(Patient, patient_id)
    if p is None:
        raise HTTPException(404, "patient not found")
    return p


def _report_or_404(session: Session, report_id: int) -> Report:
    r = session.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "report not found")
    return r


def _patient_out(p: Patient) -> PatientOut:
    return PatientOut(id=p.id, name=p.name, sex=p.sex, birth_year=p.birth_year, conditions=list(p.conditions))


def _analyte_name(analyte_id: str | None) -> str | None:
    a = name_index().analytes.get(analyte_id) if analyte_id else None
    return a["canonical_name"] if a else None


def _observation_out(o: Observation) -> ObservationOut:
    return ObservationOut(analyte_name=_analyte_name(o.analyte_id), **o.model_dump(exclude={"basis"}))


def _detail(session: Session, report: Report) -> ReportDetail:
    obs = session.exec(select(Observation).where(Observation.report_id == report.id)
                       .order_by(Observation.page, Observation.line)).all()
    c = Counter(o.status for o in obs)
    return ReportDetail(
        report=ReportOut(**report.model_dump(exclude={"skipped"})),
        counts=Counts(extracted=c[nm.EXTRACTED], needs_review=c[nm.NEEDS_REVIEW], not_tracked=c[nm.NOT_TRACKED],
                      confirmed=c[nm.CONFIRMED], rejected=c[nm.REJECTED], skipped=len(report.skipped)),
        observations=[_observation_out(o) for o in obs],
        skipped=[SkippedOut(**s) for s in report.skipped],
    )


def _to_norm(o: Observation) -> nm.Observation:
    return nm.Observation(
        test_text=o.test_text, value_text=o.value_text, unit_text=o.unit_text, range_text=o.range_text,
        flag_text=o.flag_text, row_text=o.row_text, page=o.page, line=o.line, range_lines=list(o.range_lines),
        notes=list(o.notes), analyte_id=o.analyte_id, match=o.match, basis=o.basis, comparator=o.comparator,
        value_number=o.value_number, canonical_value=o.canonical_value, canonical_unit=o.canonical_unit,
        status=o.status, status_reason=o.status_reason)


_NORM_FIELDS = ("analyte_id", "match", "basis", "comparator", "value_number", "canonical_value", "canonical_unit",
                "status", "status_reason")


def _copy_back(src: nm.Observation, dst: Observation) -> None:
    for f in _NORM_FIELDS:
        setattr(dst, f, getattr(src, f))


# ---------------------------------------------------------------- patients

@app.post("/patients", response_model=PatientOut, status_code=201)
def create_patient(body: PatientIn, session: Session = Depends(get_session)) -> PatientOut:
    p = Patient(name=body.name.strip(), sex=body.sex, birth_year=body.birth_year,
                conditions=[c.strip() for c in body.conditions if c.strip()])
    session.add(p)
    session.commit()
    session.refresh(p)
    return _patient_out(p)


@app.get("/patients", response_model=list[PatientOut])
def list_patients(session: Session = Depends(get_session)) -> list[PatientOut]:
    return [_patient_out(p) for p in session.exec(select(Patient).order_by(Patient.id)).all()]


# ---------------------------------------------------------------- reports

def _raise_if_duplicate(session: Session, sha: str) -> None:
    existing = session.exec(select(Report).where(Report.file_sha256 == sha)).first()
    if existing is not None:
        raise HTTPException(409, {"message": "this report was already uploaded", "report_id": existing.id,
                                  "patient_id": existing.patient_id})


@app.post("/patients/{patient_id}/reports", response_model=ReportDetail, status_code=201)
def upload_report(patient_id: int, file: UploadFile = File(...), session: Session = Depends(get_session),
                  tagger: Tagger = Depends(tagger_dep)) -> ReportDetail:
    patient = _patient_or_404(session, patient_id)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file is larger than 20 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "only PDF files are supported")
    sha = hashlib.sha256(data).hexdigest()
    _raise_if_duplicate(session, sha)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.pdf"
        path.write_bytes(data)
        try:
            ex = extract_report(path, tagger)
        except ScannedReportError as e:
            raise HTTPException(422, str(e)) from None
        except PdfminerException:
            raise HTTPException(422, UNREADABLE_PDF) from None

    observations, not_results = nm.normalise(ex.results, nm.Patient(patient.sex, patient.birth_year), ex.meta.date)
    skipped = [{"page": s.page, "line": s.line, "text": s.text, "reason": s.reason} for s in ex.skipped]
    skipped += [{"page": p, "line": ln, "text": t, "reason": r} for p, ln, t, r in not_results]
    skipped.sort(key=lambda s: (s["page"], s["line"]))

    report = Report(patient_id=patient.id, file_sha256=sha, filename=Path(file.filename or "report.pdf").name,
                    lab=ex.meta.lab, collected_at=ex.meta.date, date_label=ex.meta.date_label,
                    reported_at=ex.meta.reported_at, layout=ex.layout, pages=ex.pages, skipped=skipped)
    try:
        session.add(report)
        session.flush()
        for o in observations:
            session.add(Observation(report_id=report.id, **{k: v for k, v in vars(o).items()}))
        session.commit()
    except IntegrityError:     # the same file uploaded twice at once (double click): the first one won
        session.rollback()
        _raise_if_duplicate(session, sha)
        raise
    session.refresh(report)
    return _detail(session, report)


@app.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, session: Session = Depends(get_session)) -> ReportDetail:
    return _detail(session, _report_or_404(session, report_id))


@app.post("/reports/{report_id}/confirm", response_model=ReportDetail)
def confirm_report(report_id: int, body: ConfirmIn, session: Session = Depends(get_session)) -> ReportDetail:
    report = _report_or_404(session, report_id)
    patient = session.get(Patient, report.patient_id)
    obs = {o.id: o for o in session.exec(select(Observation).where(Observation.report_id == report.id)).all()}
    index = name_index()

    unknown = [e.id for e in body.observations if e.id not in obs]
    if unknown:
        raise HTTPException(422, {"message": "observations do not belong to this report", "ids": unknown})
    bad_analytes = [e.analyte_id for e in [*body.observations, *body.add]
                    if e.analyte_id is not None and e.analyte_id not in index.analytes]
    if bad_analytes:
        raise HTTPException(422, {"message": "unknown analyte_id", "analyte_ids": bad_analytes})
    d = body.collected_at
    if d is not None and not (patient.birth_year <= d.year and d <= dt.date.today()):
        raise HTTPException(422, {"message": "collected_at must be between the patient's birth year and today"})
    taken = {(o.page, o.line) for o in obs.values() if o.status != nm.REJECTED}
    bad_adds = []
    for a in body.add:
        if a.page > report.pages or (a.page, a.line) in taken:
            bad_adds.append({"page": a.page, "line": a.line})
        taken.add((a.page, a.line))
    if bad_adds:
        raise HTTPException(422, {"message": "add must point to a line of this report that is not already an observation",
                                  "lines": bad_adds})

    try:
        if body.collected_at is not None and body.collected_at != report.collected_at:
            report.collected_at, report.date_label = body.collected_at, ENTERED_BY_DOCTOR
        if body.lab is not None:
            report.lab = body.lab.strip() or None

        for edit in body.observations:
            o = obs[edit.id]
            o.edited = True
            if edit.reject:
                o.status, o.status_reason = nm.REJECTED, "rejected by the doctor"
                o.canonical_value = None
                continue
            if edit.value_text is not None:
                o.value_text = edit.value_text.strip()
            if edit.unit_text is not None:
                o.unit_text = edit.unit_text.strip()
            n = _to_norm(o)
            unmapped_by_doctor = o.match == "doctor" and o.analyte_id is None and "analyte_id" not in edit.model_fields_set
            if ("analyte_id" in edit.model_fields_set and edit.analyte_id is None) or unmapped_by_doctor:
                # Marked not tracked by the doctor (now or earlier): an edited value does not re-map it.
                n.analyte_id, n.match, n.canonical_value, n.canonical_unit = None, "doctor", None, None
                n.status, n.status_reason = nm.NOT_TRACKED, "marked not tracked by the doctor"
                pv = nm.parse_value(o.value_text)
                n.comparator, n.value_number = pv.comparator, pv.number
            else:
                choice = edit.analyte_id if "analyte_id" in edit.model_fields_set else (
                    o.analyte_id if o.match == "doctor" else None)
                nm.normalise_value(n, index, analyte_id=choice)
            _copy_back(n, o)

        skipped = list(report.skipped)
        for add in body.add:
            src = next((s for s in skipped if s["page"] == add.page and s["line"] == add.line), None)
            n = nm.normalise_value(nm.Observation(
                test_text=add.test_text.strip(), value_text=add.value_text.strip(), unit_text=add.unit_text.strip(),
                range_text=add.range_text.strip(), flag_text="", row_text=src["text"] if src else "",
                page=add.page, line=add.line), index, analyte_id=add.analyte_id)
            new = Observation(report_id=report.id, edited=True, **vars(n))
            session.add(new)
            session.flush()
            obs[new.id] = new
            if src is not None:
                skipped.remove(src)
        report.skipped = skipped

        active = [o for o in obs.values() if o.status != nm.REJECTED]
        norms = [_to_norm(o) for o in active]
        nm.recompute_egfr(norms, nm.Patient(patient.sex, patient.birth_year), report.collected_at)
        for n, o in zip(norms, active):
            _copy_back(n, o)

        if report.collected_at is None:
            raise HTTPException(422, {"message": "enter the report date (collected_at) before confirming"})
        pending = [o for o in active if o.status == nm.NEEDS_REVIEW]
        if pending:
            raise HTTPException(422, {
                "message": "fix or reject these observations before confirming",
                "observations": [{"id": o.id, "test_text": o.test_text, "reason": o.status_reason} for o in pending]})
    except HTTPException:
        session.rollback()
        raise

    for o in active:
        if o.status == nm.EXTRACTED:
            o.status = nm.CONFIRMED
    report.status = "confirmed"
    report.confirmed_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    session.add(report)
    for o in obs.values():
        session.add(o)
    session.commit()
    session.refresh(report)
    return _detail(session, report)


# ---------------------------------------------------------------- timeline

@app.get("/patients/{patient_id}/timeline", response_model=Timeline)
def timeline(patient_id: int, session: Session = Depends(get_session)) -> Timeline:
    patient = _patient_or_404(session, patient_id)
    rows = session.exec(
        select(Observation, Report).join(Report, Observation.report_id == Report.id)
        .where(Report.patient_id == patient.id, Report.status == "confirmed",
               Observation.status == nm.CONFIRMED, Observation.canonical_value.is_not(None),
               Observation.analyte_id.is_not(None))
    ).all()
    by_analyte: dict[str, list[TimelinePoint]] = {}
    for o, r in rows:
        by_analyte.setdefault(o.analyte_id, []).append(TimelinePoint(
            observation_id=o.id, report_id=r.id, date=r.collected_at, value=o.canonical_value,
            comparator=o.comparator, value_text=o.value_text, unit_text=o.unit_text, lab=r.lab,
            page=o.page, line=o.line))
    index = name_index()
    series = []
    for aid, a in index.analytes.items():          # dictionary order
        if aid in by_analyte:
            pts = sorted(by_analyte[aid], key=lambda p: (p.date, p.report_id, p.page, p.line))
            series.append(TimelineSeries(analyte_id=aid, name=a["canonical_name"], canonical_unit=a["canonical_unit"],
                                         loinc=a["loinc"], points=pts))
    return Timeline(patient=_patient_out(patient), analytes=series)
