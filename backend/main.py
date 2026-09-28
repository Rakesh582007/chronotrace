"""ChronoTrace API. Run from the repo root:  uvicorn backend.main:app --reload

Endpoints are documented with full examples in docs/api.md; tests/test_api_contract.py checks
that every documented response has the same shape as the real one.

Every route except POST /auth/login needs a signed-in doctor (backend/auth.py), and data is scoped
to that doctor: another doctor's patient, report or medication answers 404.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import tempfile
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import normalise as nm
from .auth import current_doctor, ensure_demo_doctor
from .auth import router as auth_router
from .config import check_auth_settings
from .db import check_schema, get_engine, get_session
from .db.models import Doctor, MedicationEvent, Observation, Patient, Report
from .extraction import ScannedReportError, extract_report
from .extraction.tagger import Tagger, get_tagger
from .normalise.names import name_index
from .trends import catalogue, engine
from .trends.dictionary import analyte_infos, infos_by_id
from .schemas import (ConfirmIn, Counts, Flags, MedicationIn, MedicationOut, MedicationResponse, ObservationOut,
                      PatientIn, PatientOut, ReportDetail, ReportOut, Trends,
                      SkippedOut, Timeline, TimelinePoint, TimelineSeries)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ENTERED_BY_DOCTOR = "Entered by doctor"
UNREADABLE_PDF = "could not read this PDF: it is damaged or password-protected"

FRONTEND_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Refuse to start without the login settings or on an outdated database; seed the demo doctor."""
    check_auth_settings()
    engine = get_engine()
    check_schema(engine)
    with Session(engine) as session:
        ensure_demo_doctor(session)
    yield


app = FastAPI(title="ChronoTrace API", version="0.7.0", lifespan=lifespan,
              description="Lab-report extraction, normalisation, trends and summaries (see docs/api.md).")
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)


def tagger_dep() -> Tagger:
    return get_tagger()


# ---------------------------------------------------------------- helpers

def _patient_or_404(session: Session, patient_id: int, doctor: Doctor) -> Patient:
    """The doctor's own patient; another doctor's patient is "not found", like a missing one."""
    p = session.get(Patient, patient_id)
    if p is None or p.doctor_id != doctor.id:
        raise HTTPException(404, "patient not found")
    return p


def _report_or_404(session: Session, report_id: int, doctor: Doctor) -> Report:
    r = session.get(Report, report_id)
    p = session.get(Patient, r.patient_id) if r is not None else None
    if r is None or p is None or p.doctor_id != doctor.id:
        raise HTTPException(404, "report not found")
    return r


def _medication_or_404(session: Session, medication_id: int, doctor: Doctor) -> MedicationEvent:
    m = session.get(MedicationEvent, medication_id)
    p = session.get(Patient, m.patient_id) if m is not None else None
    if m is None or p is None or p.doctor_id != doctor.id:
        raise HTTPException(404, "medication event not found")
    return m


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
def create_patient(body: PatientIn, session: Session = Depends(get_session),
                   doctor: Doctor = Depends(current_doctor)) -> PatientOut:
    p = Patient(doctor_id=doctor.id, name=body.name.strip(), sex=body.sex, birth_year=body.birth_year,
                conditions=[c.strip() for c in body.conditions if c.strip()])
    session.add(p)
    session.commit()
    session.refresh(p)
    return _patient_out(p)


@app.get("/patients", response_model=list[PatientOut])
def list_patients(session: Session = Depends(get_session), doctor: Doctor = Depends(current_doctor)) -> list[PatientOut]:
    return [_patient_out(p) for p in session.exec(select(Patient).where(Patient.doctor_id == doctor.id)
                                                  .order_by(Patient.id)).all()]


# ---------------------------------------------------------------- reports

def _raise_if_duplicate(session: Session, sha: str, doctor: Doctor) -> None:
    """409 for a file uploaded before. Its ids are given only when it is this doctor's own report."""
    existing = session.exec(select(Report).where(Report.file_sha256 == sha)).first()
    if existing is not None:
        owner = session.get(Patient, existing.patient_id)
        mine = owner is not None and owner.doctor_id == doctor.id
        raise HTTPException(409, {"message": "this report was already uploaded",
                                  "report_id": existing.id if mine else None,
                                  "patient_id": existing.patient_id if mine else None})


@app.post("/patients/{patient_id}/reports", response_model=ReportDetail, status_code=201)
def upload_report(patient_id: int, file: UploadFile = File(...), session: Session = Depends(get_session),
                  tagger: Tagger = Depends(tagger_dep), doctor: Doctor = Depends(current_doctor)) -> ReportDetail:
    patient = _patient_or_404(session, patient_id, doctor)
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file is larger than 20 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "only PDF files are supported")
    sha = hashlib.sha256(data).hexdigest()
    _raise_if_duplicate(session, sha, doctor)

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
        _raise_if_duplicate(session, sha, doctor)
        raise
    session.refresh(report)
    return _detail(session, report)


@app.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, session: Session = Depends(get_session),
               doctor: Doctor = Depends(current_doctor)) -> ReportDetail:
    return _detail(session, _report_or_404(session, report_id, doctor))


@app.post("/reports/{report_id}/confirm", response_model=ReportDetail)
def confirm_report(report_id: int, body: ConfirmIn, session: Session = Depends(get_session),
                   doctor: Doctor = Depends(current_doctor)) -> ReportDetail:
    report = _report_or_404(session, report_id, doctor)
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
def timeline(patient_id: int, session: Session = Depends(get_session),
             doctor: Doctor = Depends(current_doctor)) -> Timeline:
    patient = _patient_or_404(session, patient_id, doctor)
    by_analyte = _confirmed_points(session, patient.id)
    index = name_index()
    series = []
    for aid, a in index.analytes.items():          # dictionary order
        if aid in by_analyte:
            pts = [TimelinePoint(**vars(p)) for p in by_analyte[aid]]
            series.append(TimelineSeries(analyte_id=aid, name=a["canonical_name"], canonical_unit=a["canonical_unit"],
                                         loinc=a["loinc"], points=pts))
    return Timeline(patient=_patient_out(patient), analytes=series)


def _confirmed_points(session: Session, patient_id: int) -> dict[str, list[engine.Point]]:
    """Confirmed values of confirmed reports, per analyte, sorted by collected date. The timeline, trends,
    flags and medication responses all read the patient's data through this one query."""
    rows = session.exec(
        select(Observation, Report).join(Report, Observation.report_id == Report.id)
        .where(Report.patient_id == patient_id, Report.status == "confirmed",
               Observation.status == nm.CONFIRMED, Observation.canonical_value.is_not(None),
               Observation.analyte_id.is_not(None))
    ).all()
    out: dict[str, list[engine.Point]] = {}
    for o, r in rows:
        out.setdefault(o.analyte_id, []).append(engine.Point(
            observation_id=o.id, report_id=r.id, date=r.collected_at, value=o.canonical_value,
            comparator=o.comparator, value_text=o.value_text, unit_text=o.unit_text, lab=r.lab,
            page=o.page, line=o.line))
    for pts in out.values():
        pts.sort(key=lambda p: (p.date, p.report_id, p.page, p.line))
    return out


def _events(session: Session, patient_id: int) -> list[engine.Event]:
    out = []
    for m in _medications(session, patient_id):
        class_id, generic = catalogue.resolve(m.drug)
        out.append(engine.Event(m.id, m.drug, m.change, m.date, class_id, generic, m.dose_text))
    return out


@app.get("/patients/{patient_id}/trends", response_model=Trends, response_model_by_alias=True)
def trends(patient_id: int, session: Session = Depends(get_session),
           doctor: Doctor = Depends(current_doctor)) -> Trends:
    patient = _patient_or_404(session, patient_id, doctor)
    series, _ = engine.analyse_patient(list(analyte_infos()), _confirmed_points(session, patient.id),
                                       _events(session, patient.id))
    return Trends(patient=_patient_out(patient), analytes=series)


@app.get("/patients/{patient_id}/flags", response_model=Flags, response_model_by_alias=True)
def flags(patient_id: int, session: Session = Depends(get_session),
          doctor: Doctor = Depends(current_doctor)) -> Flags:
    patient = _patient_or_404(session, patient_id, doctor)
    _, out = engine.analyse_patient(list(analyte_infos()), _confirmed_points(session, patient.id),
                                    _events(session, patient.id))
    return Flags(patient_id=patient.id, flags=out)


@app.get("/medications/{medication_id}/response", response_model=MedicationResponse, response_model_by_alias=True)
def medication_response(medication_id: int, session: Session = Depends(get_session),
                        doctor: Doctor = Depends(current_doctor)) -> MedicationResponse:
    m = _medication_or_404(session, medication_id, doctor)
    events = _events(session, m.patient_id)
    event = next(e for e in events if e.id == m.id)
    return MedicationResponse(**engine.response(event, infos_by_id(), _confirmed_points(session, m.patient_id), events))


# ---------------------------------------------------------------- medications

def _medication_out(m: MedicationEvent) -> MedicationOut:
    class_id, generic = catalogue.resolve(m.drug)
    c = catalogue.drug_class(class_id)
    return MedicationOut(id=m.id, patient_id=m.patient_id, drug=m.drug, generic=generic, drug_class=class_id,
                         drug_class_name=c.name if c else None, change=m.change, dose_text=m.dose_text, date=m.date)


@app.post("/patients/{patient_id}/medications", response_model=MedicationOut, status_code=201)
def add_medication(patient_id: int, body: MedicationIn, session: Session = Depends(get_session),
                   doctor: Doctor = Depends(current_doctor)) -> MedicationOut:
    patient = _patient_or_404(session, patient_id, doctor)
    if not (patient.birth_year <= body.date.year and body.date <= dt.date.today()):
        raise HTTPException(422, {"message": "date must be between the patient's birth year and today"})
    m = MedicationEvent(patient_id=patient.id, drug=body.drug.strip(), change=body.change,
                        dose_text=body.dose_text.strip(), date=body.date)
    session.add(m)
    session.commit()
    session.refresh(m)
    return _medication_out(m)


def _medications(session: Session, patient_id: int) -> list[MedicationEvent]:
    return list(session.exec(select(MedicationEvent).where(MedicationEvent.patient_id == patient_id)
                             .order_by(MedicationEvent.date, MedicationEvent.id)).all())


@app.get("/patients/{patient_id}/medications", response_model=list[MedicationOut])
def list_medications(patient_id: int, session: Session = Depends(get_session),
                     doctor: Doctor = Depends(current_doctor)) -> list[MedicationOut]:
    _patient_or_404(session, patient_id, doctor)
    return [_medication_out(m) for m in _medications(session, patient_id)]


@app.delete("/medications/{medication_id}", status_code=204)
def delete_medication(medication_id: int, session: Session = Depends(get_session),
                      doctor: Doctor = Depends(current_doctor)) -> Response:
    m = _medication_or_404(session, medication_id, doctor)
    session.delete(m)
    session.commit()
    return Response(status_code=204)

