"""Demo doctor login: one seeded doctor, PBKDF2 password hash, stdlib HMAC-signed token.

Not production auth: no rate limiting, no refresh tokens, no password reset (docs/decisions.md).

Token: "<doctor_id>.<expiry unix seconds>.<hex HMAC-SHA256 of "<doctor_id>.<expiry>">", valid 12 hours.
Every API route except POST /auth/login needs "Authorization: Bearer <token>". Data belongs to the
doctor who created the patient; another doctor's patient (or its reports, documents, medications,
summaries) answers 404, not 403, so ids of other doctors' data are not revealed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from . import config
from .db import get_session
from .db.models import Doctor

ITERATIONS = 200_000
TOKEN_SECONDS = 12 * 3600
BAD_LOGIN = "Username or password is incorrect"


# ---------------------------------------------------------------- passwords

def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        assert algo == "pbkdf2_sha256"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, AssertionError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Checked when the username does not exist, so a wrong username costs the same time as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- tokens

def _sign(payload: str, secret: bytes) -> str:
    return hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()


def make_token(doctor_id: int, secret: bytes | None = None, now: float | None = None) -> str:
    expiry = int((now if now is not None else time.time()) + TOKEN_SECONDS)
    payload = f"{doctor_id}.{expiry}"
    return f"{payload}.{_sign(payload, secret or config.auth_secret())}"


def token_doctor_id(token: str, secret: bytes | None = None, now: float | None = None) -> int | None:
    """The doctor id of a valid, unexpired token; None otherwise."""
    try:
        doctor_id, expiry, signature = token.split(".")
        payload = f"{int(doctor_id)}.{int(expiry)}"
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(payload, secret or config.auth_secret()), signature):
        return None
    if int(expiry) <= (now if now is not None else time.time()):
        return None
    return int(doctor_id)


# ---------------------------------------------------------------- dependency and routes

def current_doctor(authorization: str | None = Header(default=None),
                   session: Session = Depends(get_session)) -> Doctor:
    scheme, _, token = (authorization or "").partition(" ")
    doctor_id = token_doctor_id(token.strip()) if scheme.lower() == "bearer" else None
    doctor = session.get(Doctor, doctor_id) if doctor_id is not None else None
    if doctor is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    return doctor


def ensure_demo_doctor(session: Session) -> Doctor:
    """Create the demo doctor from .env, or update its name and password to match .env."""
    config.check_auth_settings()
    username = config.setting("DEMO_DOCTOR_USER")
    doctor = session.exec(select(Doctor).where(Doctor.username == username)).first()
    password = config.setting("DEMO_DOCTOR_PASSWORD")
    if doctor is None:
        doctor = Doctor(name=config.setting("DEMO_DOCTOR_NAME"), username=username, password_hash=hash_password(password))
    else:
        doctor.name = config.setting("DEMO_DOCTOR_NAME")
        if not verify_password(password, doctor.password_hash):
            doctor.password_hash = hash_password(password)
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


class LoginIn(BaseModel):
    username: str
    password: str


class DoctorOut(BaseModel):
    id: int
    name: str


class LoginOut(BaseModel):
    token: str
    doctor: DoctorOut


router = APIRouter()


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> LoginOut:
    doctor = session.exec(select(Doctor).where(Doctor.username == body.username.strip())).first()
    ok = verify_password(body.password, doctor.password_hash if doctor else _DUMMY_HASH)
    if doctor is None or not ok:
        raise HTTPException(401, BAD_LOGIN)
    return LoginOut(token=make_token(doctor.id), doctor=DoctorOut(id=doctor.id, name=doctor.name))


@router.get("/auth/me", response_model=DoctorOut)
def me(doctor: Doctor = Depends(current_doctor)) -> DoctorOut:
    return DoctorOut(id=doctor.id, name=doctor.name)
