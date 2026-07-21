"""Phase 3: operator auth primitives, login flow, and the gate middleware."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zengrowth.api import security
from zengrowth.api.main import create_app
from zengrowth.config import Settings, get_settings

# --- primitives -------------------------------------------------------------


def test_password_hash_round_trip():
    stored = security.hash_password("hunter2", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert security.verify_password("hunter2", stored)
    assert not security.verify_password("wrong", stored)


def test_session_cookie_round_trip_and_expiry():
    secret = "s3cret"
    cookie = security.make_session_cookie(secret, ttl_seconds=100, issued_at=1000)
    assert security.verify_session_cookie(secret, cookie, now=1050)
    assert not security.verify_session_cookie(secret, cookie, now=2000)  # expired
    assert not security.verify_session_cookie("other-secret", cookie, now=1050)  # bad sig
    assert not security.verify_session_cookie(secret, "garbage", now=1050)


# --- login flow over a configured app --------------------------------------


@pytest.fixture()
def auth_client(monkeypatch):
    """App with auth configured but require_https off (so login cookies work over
    the test transport). get_settings() is patched and its cache cleared."""
    stored = security.hash_password("operator-pw", iterations=1000)
    monkeypatch.setenv("ZENGROWTH_OPERATOR_PASSWORD_HASH", stored)
    monkeypatch.setenv("ZENGROWTH_SESSION_SECRET", "test-signing-secret")
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_login_logout_session_flow(auth_client):
    assert auth_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401

    ok = auth_client.post("/api/auth/login", json={"password": "operator-pw"})
    assert ok.status_code == 200
    assert auth_client.get("/api/auth/session").status_code == 200

    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/auth/session").status_code == 401


# --- gate bites in forced production mode ----------------------------------


def test_gate_blocks_without_session_when_https_required(monkeypatch):
    stored = security.hash_password("operator-pw", iterations=1000)

    def _prod_settings() -> Settings:
        return Settings(
            _env_file=None,
            zengrowth_require_https=True,
            zengrowth_operator_password_hash=stored,
            zengrowth_session_secret="test-signing-secret",
        )

    monkeypatch.setattr("zengrowth.api.middleware.get_settings", _prod_settings)
    # The fail-closed lifespan also reads get_settings; provide configured creds.
    monkeypatch.setattr("zengrowth.api.main.get_settings", _prod_settings)
    client = TestClient(create_app())

    # No session cookie, https required -> the localhost bypass is disabled -> 401.
    assert client.get("/api/jobs").status_code == 401
    # Allowlisted routes still reachable.
    assert client.get("/health").status_code == 200


# --- login brute-force backoff (SEC-04) ------------------------------------


@pytest.fixture()
def throttled_client(monkeypatch):
    """Auth app with a low lockout threshold so the backoff is testable fast."""
    stored = security.hash_password("operator-pw", iterations=1000)
    monkeypatch.setenv("ZENGROWTH_OPERATOR_PASSWORD_HASH", stored)
    monkeypatch.setenv("ZENGROWTH_SESSION_SECRET", "test-signing-secret")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "300")
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_login_locks_out_after_repeated_failures(throttled_client):
    for _ in range(3):
        assert throttled_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    # Threshold crossed: further attempts are throttled — even the correct one.
    locked = throttled_client.post("/api/auth/login", json={"password": "operator-pw"})
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


def test_successful_login_resets_the_failure_counter(throttled_client):
    # Two failures (below the threshold of 3) then a success clears the count.
    for _ in range(2):
        assert throttled_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert throttled_client.post("/api/auth/login", json={"password": "operator-pw"}).status_code == 200
    # Counter reset: two fresh failures still don't lock.
    for _ in range(2):
        assert throttled_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert throttled_client.get("/api/auth/session").status_code == 200


def test_login_returns_503_when_auth_unconfigured():
    # Default dev settings: no operator hash/secret configured.
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert client.post("/api/auth/login", json={"password": "x"}).status_code == 503


def test_fail_closed_startup_refuses_to_boot_without_operator(monkeypatch):
    def _prod_unconfigured() -> Settings:
        return Settings(_env_file=None, zengrowth_require_https=True)

    monkeypatch.setattr("zengrowth.api.main.get_settings", _prod_unconfigured)
    # Entering the TestClient context triggers the lifespan startup, which must raise.
    with pytest.raises(RuntimeError, match="ZENGROWTH_OPERATOR_PASSWORD_HASH"), TestClient(
        create_app()
    ):
        pass


# --- dev/loopback session bypass (SPA must not wall a fresh local clone) -----


def test_session_dev_bypass_when_operator_unconfigured(monkeypatch):
    """In dev (require_https off) with no operator configured, /auth/session
    reports authenticated from loopback so the SPA renders without a login wall."""

    def _dev_unconfigured() -> Settings:
        return Settings(_env_file=None, zengrowth_require_https=False)

    monkeypatch.setattr("zengrowth.api.routers.auth.get_settings", _dev_unconfigured)
    client = TestClient(create_app())
    assert client.get("/api/auth/session").status_code == 200


def test_session_requires_cookie_once_operator_configured(monkeypatch):
    """Once an operator hash + secret are set, the loopback bypass no longer
    applies to /auth/session: it reflects the (absent) signed cookie."""
    stored = security.hash_password("operator-pw", iterations=1000)

    def _dev_configured() -> Settings:
        return Settings(
            _env_file=None,
            zengrowth_require_https=False,
            zengrowth_operator_password_hash=stored,
            zengrowth_session_secret="test-signing-secret",
        )

    monkeypatch.setattr("zengrowth.api.routers.auth.get_settings", _dev_configured)
    client = TestClient(create_app())
    assert client.get("/api/auth/session").status_code == 401
