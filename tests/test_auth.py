"""Demo login, signed tokens and per-doctor data scoping."""

import re
import time

import pytest
from fastapi.testclient import TestClient

from backend import auth, config
from backend.main import app
from tests.conftest import FIXTURES, TEST_ENV


def upload(client, pid, name="demo_t2d_ckd_1.pdf"):
    with open(FIXTURES / name, "rb") as f:
        return client.post(f"/patients/{pid}/reports", files={"file": (name, f, "application/pdf")})


# ---------------------------------------------------------------- passwords and tokens

def test_password_hash_is_pbkdf2_with_a_random_salt():
    a, b = auth.hash_password("secret-1"), auth.hash_password("secret-1")
    assert a != b and a.startswith("pbkdf2_sha256$200000$")
    assert auth.verify_password("secret-1", a) and not auth.verify_password("secret-2", a)
    assert not auth.verify_password("secret-1", "garbage")


def test_token_round_trip_expiry_and_tampering():
    secret = b"s" * 40
    token = auth.make_token(7, secret, now=1_000_000)
    assert auth.token_doctor_id(token, secret, now=1_000_000 + 3600) == 7
    assert auth.token_doctor_id(token, secret, now=1_000_000 + 12 * 3600 + 1) is None      # expired after 12 h
    assert auth.token_doctor_id(token, b"x" * 40, now=1_000_000) is None                    # other secret
    doctor, expiry, sig = token.split(".")
    assert auth.token_doctor_id(f"8.{expiry}.{sig}", secret, now=1_000_000) is None        # changed payload
    assert auth.token_doctor_id("not-a-token", secret) is None


# ---------------------------------------------------------------- login

def test_login_and_me(client):
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["name"] == "Dr A"


def test_wrong_username_or_password_get_the_same_401(client):
    bad_pw = client.post("/auth/login", json={"username": "dr.a", "password": "nope"})
    bad_user = client.post("/auth/login", json={"username": "nobody", "password": "pw-a-12345"})
    assert bad_pw.status_code == bad_user.status_code == 401
    assert bad_pw.json() == bad_user.json() == {"detail": "Username or password is incorrect"}


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer abc.def.ghi", "Basic dXNlcjpwYXNz"])
def test_missing_or_invalid_token_is_401(client, header):
    c = TestClient(app)
    headers = {} if header is None else {"Authorization": header}
    assert c.get("/patients", headers=headers).status_code == 401


def test_expired_token_is_401(client):
    doctor_id = client.get("/auth/me").json()["id"]
    old = auth.make_token(doctor_id, now=time.time() - 13 * 3600)
    assert TestClient(app).get("/patients", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_every_route_except_login_requires_a_token(client):
    anonymous = TestClient(app)
    paths = app.openapi()["paths"]
    checked = 0
    for path, methods in paths.items():
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in methods:
            if (method, path) == ("post", "/auth/login"):
                continue
            r = anonymous.request(method.upper(), url)
            assert r.status_code == 401, (method, path, r.status_code)
            checked += 1
    assert checked == sum(len(m) for m in paths.values()) - 1          # every route but the login itself


# ---------------------------------------------------------------- scoping

def test_a_second_doctor_sees_none_of_the_first_doctors_data(client, other_doctor):
    pid = client.post("/patients", json={"name": "A's patient", "sex": "male", "birth_year": 1966}).json()["id"]
    rid = upload(client, pid).json()["report"]["id"]
    assert client.post(f"/reports/{rid}/confirm", json={}).status_code == 200
    mid = client.post(f"/patients/{pid}/medications", json={"drug": "Ramipril", "change": "start",
                                                           "date": "2024-01-10"}).json()["id"]
    b = other_doctor
    assert b.get("/patients").json() == []
    for url in [f"/patients/{pid}/timeline", f"/patients/{pid}/trends", f"/patients/{pid}/flags",
                f"/patients/{pid}/medications", f"/reports/{rid}", f"/medications/{mid}/response"]:
        assert b.get(url).status_code == 404, url
    assert b.post(f"/reports/{rid}/confirm", json={}).status_code == 404
    assert b.post(f"/patients/{pid}/medications", json={"drug": "X", "change": "start",
                                                        "date": "2024-01-10"}).status_code == 404
    assert b.delete(f"/medications/{mid}").status_code == 404
    assert upload(b, pid, "demo_t2d_ckd_2.pdf").status_code == 404
    # The same file uploaded by B for B's own patient: a duplicate, but A's ids are not revealed.
    bpid = b.post("/patients", json={"name": "B's patient", "sex": "female", "birth_year": 1970}).json()["id"]
    dup = upload(b, bpid)
    assert dup.status_code == 409 and dup.json()["detail"]["report_id"] is None
    # A still sees everything.
    assert [p["id"] for p in client.get("/patients").json()] == [pid]
    assert client.get(f"/medications/{mid}/response").status_code == 200


# ---------------------------------------------------------------- startup and CORS

@pytest.mark.parametrize("key", list(TEST_ENV))
def test_app_refuses_to_start_without_a_login_setting(monkeypatch, key):
    monkeypatch.setenv(key, "")
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(config.ConfigError, match=key):
        with TestClient(app):
            pass


def test_short_secret_is_refused(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "too-short")
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    with pytest.raises(config.ConfigError, match="at least 32"):
        config.check_auth_settings()


def test_startup_seeds_the_demo_doctor(client):
    with TestClient(app) as c:                       # runs the startup: seeds the doctor from the settings
        r = c.post("/auth/login", json={"username": TEST_ENV["DEMO_DOCTOR_USER"],
                                        "password": TEST_ENV["DEMO_DOCTOR_PASSWORD"]})
    assert r.status_code == 200 and r.json()["doctor"]["name"] == TEST_ENV["DEMO_DOCTOR_NAME"]


def test_cors_allows_only_the_frontend(client):
    ok = client.options("/patients", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/patients", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers
