"""ChronoTrace API. Run from the repo root:  uvicorn backend.main:app --reload

Endpoints are documented with full examples in docs/api.md; tests/test_api_contract.py checks
that every documented response has the same shape as the real one.

Every route except POST /auth/login needs a signed-in doctor (backend/auth.py), and data is scoped
to that doctor: another doctor's patient, report or medication answers 404.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import tempfile
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pdfplumber.utils.exceptions import PdfminerException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import normalise as nm
from . import storage
from . import summaries
from .summaries import facts as summary_facts
from .summaries.llm import LLMConfigError, get_llm
from .auth import current_doctor, ensure_demo_doctor
from .auth import router as auth_router
from .config import check_auth_settings
from .db import check_schema, get_engine, get_session
from .db.models import Doctor, Document, MedicationEvent, Observation, Patient, Report, Summary
from .extraction import ScannedReportError, extract_report
from .extraction.tagger import Tagger, get_tagger
from .normalise.names import name_index
from .trends import catalogue, engine
from .trends import systems as body
from .trends.dictionary import analyte_infos, infos_by_id
from .schemas import (ConfirmIn, Counts, DocumentOut, Flags, MedicationIn, MedicationOut, MedicationResponse, ObservationOut,
                      PatientIn, PatientListItem, PatientOut, ReportDetail, ReportOut, SummaryIn, SummaryOut,
                      Systems, Trends,
                      SkippedOut, Timeline, TimelinePoint, TimelineSeries)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
PAGE_DPI = 110
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


def llm_dep():
    """The summary writer's factory (tests override it with a fake LLM)."""
    return get_llm


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
    return PatientOut(id=p.id, patient_code=p.patient_code, name=p.name, sex=p.sex, birth_year=p.birth_year,
                      conditions=list(p.conditions), has_photo=bool(p.photo_path))


def _next_patient_code(session: Session) -> str:
    codes = session.exec(select(Patient.patient_code)).all()
    n = max((int(c.split("-")[1]) for c in codes if c and c.startswith("CT-")), default=0)
    return f"CT-{n + 1:04d}"


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
    p = Patient(doctor_id=doctor.id, patient_code=_next_patient_code(session), name=body.name.strip(), sex=body.sex,
                birth_year=body.birth_year, conditions=[c.strip() for c in body.conditions if c.strip()])
    session.add(p)
    session.commit()
    session.refresh(p)
    return _patient_out(p)


def _list_item(session: Session, p: Patient) -> PatientListItem:
    points = _confirmed_points(session, p.id)
    _, flags = engine.analyse_patient(list(analyte_infos()), points, _events(session, p.id))
    reports = session.exec(select(Report).where(Report.patient_id == p.id, Report.status == "confirmed")).all()
    counts = body.flag_counts(flags)
    return PatientListItem(
        **_patient_out(p).model_dump(),
        guideline_flags=counts["guideline"], change_flags=counts["change"], expected_flags=counts["expected"],
        latest_report_date=max((r.collected_at for r in reports if r.collected_at), default=None),
        report_count=len(reports), lab_count=len({r.lab for r in reports if r.lab}))


def needs_review_key(i: PatientListItem) -> tuple:
    """Sort key (descending): guideline flags, then change flags, then the latest report; ties by the older id."""
    return i.guideline_flags, i.change_flags, i.latest_report_date or dt.date.min, -i.id


@app.get("/patients", response_model=list[PatientListItem])
def list_patients(sort: Literal["needs_review", "name", "latest_report"] = Query("needs_review"),
                  session: Session = Depends(get_session),
                  doctor: Doctor = Depends(current_doctor)) -> list[PatientListItem]:
    """The doctor's patients with their flag counts. needs_review: guideline flags, then change flags, then the
    latest report first; name: A-Z; latest_report: newest first."""
    items = [_list_item(session, p) for p in session.exec(select(Patient).where(Patient.doctor_id == doctor.id)
                                                          .order_by(Patient.id)).all()]
    if sort == "name":
        items.sort(key=lambda i: (i.name.casefold(), i.id))
    elif sort == "latest_report":
        items.sort(key=lambda i: (i.latest_report_date or dt.date.min, -i.id), reverse=True)
    else:
        items.sort(key=needs_review_key, reverse=True)
    return items


@app.post("/patients/{patient_id}/photo", response_model=PatientOut)
def upload_photo(patient_id: int, file: UploadFile = File(...), session: Session = Depends(get_session),
                 doctor: Doctor = Depends(current_doctor)) -> PatientOut:
    patient = _patient_or_404(session, patient_id, doctor)
    data = file.file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo is larger than 5 MB")
    kind = storage.file_type(data, ("jpg", "png"))
    if kind is None:
        raise HTTPException(415, "the photo must be a JPG or PNG image")
    storage.remove(patient.photo_path)
    patient.photo_path = storage.save(f"photos/patient-{patient.id}.{kind}", data)
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return _patient_out(patient)


@app.get("/patients/{patient_id}/photo", response_class=FileResponse)
def get_photo(patient_id: int, session: Session = Depends(get_session),
              doctor: Doctor = Depends(current_doctor)) -> FileResponse:
    patient = _patient_or_404(session, patient_id, doctor)
    if not patient.photo_path or not storage.absolute(patient.photo_path).exists():
        raise HTTPException(404, "no photo for this patient")
    return FileResponse(storage.absolute(patient.photo_path), media_type=storage.media_type(patient.photo_path))


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

    filename = Path(file.filename or "report.pdf").name
    report = Report(patient_id=patient.id, file_sha256=sha, filename=filename,
                    lab=ex.meta.lab, collected_at=ex.meta.date, date_label=ex.meta.date_label,
                    reported_at=ex.meta.reported_at, layout=ex.layout, pages=ex.pages, skipped=skipped,
                    page_width=ex.page_width, page_height=ex.page_height)
    stored = None
    try:
        session.add(report)
        session.flush()
        for o in observations:
            session.add(Observation(report_id=report.id, **{k: v for k, v in vars(o).items()}))
        doc = Document(patient_id=patient.id, kind="lab_report", filename=filename, sha256=sha, size=len(data),
                       report_id=report.id, document_date=ex.meta.date)
        stored = _store_document(session, doc, data, "pdf")
        session.commit()
    except IntegrityError:     # the same file uploaded twice at once (double click): the first one won
        session.rollback()
        storage.remove(stored)
        _raise_if_duplicate(session, sha, doctor)
        raise
    except Exception:
        session.rollback()
        storage.remove(stored)
        raise
    session.refresh(report)
    return _detail(session, report)


# ---------------------------------------------------------------- documents

def _store_document(session: Session, doc: Document, data: bytes, ext: str) -> str:
    """Add the row, then write the file named after its id (two rows never share a file)."""
    session.add(doc)
    session.flush()
    doc.stored_path = storage.save(f"documents/{doc.id}-{doc.sha256[:12]}.{ext}", data)
    return doc.stored_path


def _document_out(session: Session, d: Document) -> DocumentOut:
    report = session.get(Report, d.report_id) if d.report_id else None
    return DocumentOut(id=d.id, patient_id=d.patient_id, kind=d.kind, filename=d.filename, sha256=d.sha256,
                       size=d.size, uploaded_at=d.uploaded_at, document_date=d.document_date, report_id=d.report_id,
                       report_status=report.status if report else None)


def _document_or_404(session: Session, document_id: int, doctor: Doctor) -> Document:
    d = session.get(Document, document_id)
    p = session.get(Patient, d.patient_id) if d is not None else None
    if d is None or p is None or p.doctor_id != doctor.id:
        raise HTTPException(404, "document not found")
    return d


@app.post("/patients/{patient_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(patient_id: int, kind: Literal["lab_report", "prescription", "doctor_note"] = Form(...),
                    file: UploadFile = File(...), document_date: dt.date | None = Form(None),
                    session: Session = Depends(get_session), doctor: Doctor = Depends(current_doctor)) -> DocumentOut:
    """Store a prescription or a doctor's note (PDF, JPG or PNG, up to 15 MB). It is kept, never parsed."""
    patient = _patient_or_404(session, patient_id, doctor)
    if kind == "lab_report":
        raise HTTPException(422, "upload lab reports with POST /patients/{id}/reports, which reads their values")
    data = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "file is larger than 15 MB")
    ext = storage.file_type(data, ("pdf", "jpg", "png"))
    if ext is None:
        raise HTTPException(415, "only PDF, JPG and PNG files are accepted")
    sha = hashlib.sha256(data).hexdigest()
    mine = select(Document).join(Patient, Patient.id == Document.patient_id).where(
        Patient.doctor_id == doctor.id, Document.sha256 == sha)
    existing = session.exec(mine).first()
    if existing is not None:
        raise HTTPException(409, {"message": "this file was already uploaded", "document_id": existing.id,
                                  "patient_id": existing.patient_id})
    doc = Document(patient_id=patient.id, kind=kind, filename=Path(file.filename or f"document.{ext}").name,
                   sha256=sha, size=len(data), document_date=document_date)
    stored = None
    try:
        stored = _store_document(session, doc, data, ext)
        session.commit()
    except Exception:
        session.rollback()
        storage.remove(stored)
        raise
    session.refresh(doc)
    return _document_out(session, doc)


@app.get("/patients/{patient_id}/documents", response_model=list[DocumentOut])
def list_documents(patient_id: int, session: Session = Depends(get_session),
                   doctor: Doctor = Depends(current_doctor)) -> list[DocumentOut]:
    """Every document of the patient, newest upload first."""
    patient = _patient_or_404(session, patient_id, doctor)
    docs = session.exec(select(Document).where(Document.patient_id == patient.id)
                        .order_by(Document.uploaded_at.desc(), Document.id.desc())).all()
    return [_document_out(session, d) for d in docs]


@app.get("/documents/{document_id}/file", response_class=FileResponse)
def document_file(document_id: int, session: Session = Depends(get_session),
                  doctor: Doctor = Depends(current_doctor)) -> FileResponse:
    d = _document_or_404(session, document_id, doctor)
    path = storage.absolute(d.stored_path)
    if not d.stored_path or not path.exists():
        raise HTTPException(404, "the stored file is missing")
    return FileResponse(path, media_type=storage.media_type(d.stored_path), filename=d.filename,
                        content_disposition_type="inline")


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, session: Session = Depends(get_session),
                    doctor: Doctor = Depends(current_doctor)) -> Response:
    """Delete a document and its file. A lab report goes with its extracted values, unless they were
    confirmed: confirmed values are part of the patient's timeline, so that answers 409."""
    d = _document_or_404(session, document_id, doctor)
    report = session.get(Report, d.report_id) if d.report_id else None
    if report is not None and report.status == "confirmed":
        raise HTTPException(409, {"message": "this lab report has confirmed values in the timeline and cannot be "
                                             "deleted", "report_id": report.id})
    stored = d.stored_path
    pages = [_page_cache(report.id, n) for n in range(1, report.pages + 1)] if report is not None else []
    session.delete(d)
    if report is not None:
        session.flush()
        for o in session.exec(select(Observation).where(Observation.report_id == report.id)).all():
            session.delete(o)
        session.delete(report)
    session.commit()
    for path in [stored, *pages]:
        storage.remove(path)
    return Response(status_code=204)


@app.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, session: Session = Depends(get_session),
               doctor: Doctor = Depends(current_doctor)) -> ReportDetail:
    return _detail(session, _report_or_404(session, report_id, doctor))


def _page_cache(report_id: int, page: int) -> str:
    return f"pages/report-{report_id}-p{page}-{PAGE_DPI}dpi.png"


@app.get("/reports/{report_id}/pages/{page}.png", response_class=FileResponse)
def report_page(report_id: int, page: int, session: Session = Depends(get_session),
                doctor: Doctor = Depends(current_doctor)) -> FileResponse:
    """One page of the report's PDF as a PNG at 110 dpi (rendered once, then served from the cache).
    Pixels = PDF points x 110 / 72, so an observation's bbox maps onto it with that scale."""
    report = _report_or_404(session, report_id, doctor)
    if not 1 <= page <= report.pages:
        raise HTTPException(404, f"page {page} not found (the report has {report.pages})")
    cached = _page_cache(report.id, page)
    if not storage.absolute(cached).exists():
        doc = session.exec(select(Document).where(Document.report_id == report.id)).first()
        if doc is None or not doc.stored_path or not storage.absolute(doc.stored_path).exists():
            raise HTTPException(404, "the report's PDF is not stored (uploaded before documents were kept)")
        with pdfplumber.open(storage.absolute(doc.stored_path)) as pdf:
            image = pdf.pages[page - 1].to_image(resolution=PAGE_DPI).original
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        storage.save(cached, buf.getvalue())
    return FileResponse(storage.absolute(cached), media_type="image/png")


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


@app.get("/patients/{patient_id}/systems", response_model=Systems)
def systems(patient_id: int, session: Session = Depends(get_session),
            doctor: Doctor = Depends(current_doctor)) -> Systems:
    """Every body system with its status, headline value and flag counts (backend/trends/systems.py)."""
    patient = _patient_or_404(session, patient_id, doctor)
    series, out = engine.analyse_patient(list(analyte_infos()), _confirmed_points(session, patient.id),
                                         _events(session, patient.id))
    return Systems(patient_id=patient.id, systems=body.summarise(body.body_systems(), infos_by_id(), series, out))


@app.get("/medications/{medication_id}/response", response_model=MedicationResponse, response_model_by_alias=True)
def medication_response(medication_id: int, session: Session = Depends(get_session),
                        doctor: Doctor = Depends(current_doctor)) -> MedicationResponse:
    m = _medication_or_404(session, medication_id, doctor)
    events = _events(session, m.patient_id)
    event = next(e for e in events if e.id == m.id)
    return MedicationResponse(**engine.response(event, infos_by_id(), _confirmed_points(session, m.patient_id), events))


# ---------------------------------------------------------------- summaries

def _summary_out(s: Summary) -> SummaryOut:
    return SummaryOut(id=s.id, patient_id=s.patient_id, period=s.period, from_=s.from_date, to=s.to_date,
                      created_at=s.created_at, model=s.model, facts_sha256=s.facts_sha256, content=s.content)


def _latest_summary(session: Session, patient_id: int, period: str) -> Summary | None:
    return session.exec(select(Summary).where(Summary.patient_id == patient_id, Summary.period == period)
                        .order_by(Summary.created_at.desc(), Summary.id.desc())).first()


def _summary_failure(status: int, detail: str, last: Summary | None) -> JSONResponse:
    last_saved = jsonable_encoder(_summary_out(last), by_alias=True) if last else None
    return JSONResponse(status_code=status, content={"detail": detail, "last_saved": last_saved})


@app.post("/patients/{patient_id}/summaries", response_model=SummaryOut, status_code=201,
          response_model_by_alias=True, responses={502: {"description": "the LLM failed twice; last_saved"},
                                                   503: {"description": "the LLM is not configured; last_saved"}})
def create_summary(patient_id: int, request: SummaryIn, session: Session = Depends(get_session),
                   doctor: Doctor = Depends(current_doctor), llm_factory=Depends(llm_dep)):
    """Write, check and save a summary of the period. The LLM sees only facts computed by the trend engine
    (backend/summaries/facts.py); an answer that fails a check is retried once, then 502 with the last
    saved summary of the same period (or null). Nothing that fails a check is saved."""
    patient = _patient_or_404(session, patient_id, doctor)
    reports = [summary_facts.ReportRef(r.id, r.collected_at, r.lab) for r in session.exec(
        select(Report).where(Report.patient_id == patient.id, Report.status == "confirmed")).all()]
    try:
        period = summary_facts.resolve_period(request.period, reports, request.from_, request.to)
    except summary_facts.PeriodError as e:
        raise HTTPException(422, str(e)) from None
    facts = summary_facts.build_facts(
        {"code": patient.patient_code, "sex": patient.sex, "birth_year": patient.birth_year,
         "conditions": list(patient.conditions)},
        dt.date.today(), reports, period, _confirmed_points(session, patient.id), _events(session, patient.id),
        infos_by_id(), body.body_systems())
    last = _latest_summary(session, patient.id, period.kind)
    try:
        llm = llm_factory()
    except LLMConfigError as e:
        return _summary_failure(503, str(e), last)
    try:
        written = summaries.write_summary(llm, facts)
    except summaries.SummaryFailed as e:
        return _summary_failure(502, f"the summary could not be written after 2 attempts: {e}", last)
    s = Summary(patient_id=patient.id, period=period.kind, from_date=period.start, to_date=period.end,
                model=llm.model, facts_sha256=facts.sha256, content=summaries.to_content(written, facts))
    session.add(s)
    session.commit()
    session.refresh(s)
    return _summary_out(s)


@app.get("/patients/{patient_id}/summaries/latest", response_model=SummaryOut, response_model_by_alias=True)
def latest_summary(patient_id: int, period: Literal["since_last_visit", "range", "all"] = Query(...),
                   session: Session = Depends(get_session), doctor: Doctor = Depends(current_doctor)) -> SummaryOut:
    patient = _patient_or_404(session, patient_id, doctor)
    s = _latest_summary(session, patient.id, period)
    if s is None:
        raise HTTPException(404, "no saved summary for this period")
    return _summary_out(s)


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

