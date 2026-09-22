"""Phase 3: operator auth primitives, login flow, and the gate middleware."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from zengrowth.api import security
from zengrowth.api.main import create_app
from zengrowth.api.operator_sessions import revoke_all_operator_sessions
from zengrowth.api.routers.auth import SESSION_COOKIE
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


def test_session_cookie_rejects_payload_without_sid():
    secret = "s3cret"
    payload = {"iat": 1000, "exp": 1100}
    payload_b64 = security._b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    legacy = f"{payload_b64}.{security._sign(secret, payload_b64)}"
    assert not security.verify_session_cookie(secret, legacy, now=1050)


# --- login flow over a configured app --------------------------------------


@pytest.fixture()
def auth_client(monkeypatch):
    """App with auth configured but require_https off (so login cookies work over
    the test transport). get_settings() is patched and its cache cleared."""
    stored = security.hash_password("operator-pw", iterations=1000)
    monkeypatch.setenv("ZENGROWTH_OPERATOR_PASSWORD_HASH", stored)
    monkeypatch.setenv("ZENGROWTH_SESSION_SECRET", "test-signing-secret")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_login_logout_session_flow(auth_client):
    assert auth_client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401

    ok = auth_client.post("/api/auth/login", json={"password": "operator-pw"})
    assert ok.status_code == 200
    assert auth_client.get("/api/auth/session").status_code == 200

    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/auth/session").status_code == 401


def test_logout_revokes_a_stolen_cookie(auth_client):
    ok = auth_client.post("/api/auth/login", json={"password": "operator-pw"})
    assert ok.status_code == 200
    stolen = ok.cookies.get(SESSION_COOKIE)
    assert stolen

    assert auth_client.post("/api/auth/logout").status_code == 200
    auth_client.cookies.set(SESSION_COOKIE, stolen)
    assert auth_client.get("/api/auth/session").status_code == 401


def test_revoke_all_sessions_kills_a_still_signed_cookie(auth_client):
    ok = auth_client.post("/api/auth/login", json={"password": "operator-pw"})
    stolen = ok.cookies.get(SESSION_COOKIE)
    assert stolen
    assert revoke_all_operator_sessions() >= 1
    auth_client.cookies.set(SESSION_COOKIE, stolen)
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


def test_gate_rejects_revoked_cookie_when_https_required(monkeypatch):
    stored = security.hash_password("operator-pw", iterations=1000)

    def _prod_settings() -> Settings:
        return Settings(
            _env_file=None,
            zengrowth_require_https=True,
            zengrowth_operator_password_hash=stored,
            zengrowth_session_secret="test-signing-secret",
        )

    monkeypatch.setattr("zengrowth.api.middleware.get_settings", _prod_settings)
    monkeypatch.setattr("zengrowth.api.main.get_settings", _prod_settings)
    monkeypatch.setattr("zengrowth.api.routers.auth.get_settings", _prod_settings)
    with TestClient(create_app(), base_url="https://testserver") as client:
        logged_in = client.post("/api/auth/login", json={"password": "operator-pw"})
        assert logged_in.status_code == 200
        stolen = logged_in.cookies.get(SESSION_COOKIE)
        assert stolen
        assert client.get("/api/jobs").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set(SESSION_COOKIE, stolen)
        assert client.get("/api/jobs").status_code == 401


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
    with TestClient(create_app()) as client:
        yield client
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


def test_lockout_is_per_client_behind_the_proxy(throttled_client):
    """SEC-04: one client's failures must not lock out everyone else.

    The API only ever sees the nginx peer address, so keying the throttle on
    request.client.host gave every caller one shared bucket — an attacker could
    spend the operator's budget and lock them out.
    """
    attacker = {"X-Real-IP": "203.0.113.9"}
    for _ in range(3):
        assert (
            throttled_client.post(
                "/api/auth/login", json={"password": "wrong"}, headers=attacker
            ).status_code
            == 401
        )
    assert (
        throttled_client.post(
            "/api/auth/login", json={"password": "operator-pw"}, headers=attacker
        ).status_code
        == 429
    )
    # A different client is unaffected and can still log in.
    operator = {"X-Real-IP": "198.51.100.4"}
    assert (
        throttled_client.post(
            "/api/auth/login", json={"password": "operator-pw"}, headers=operator
        ).status_code
        == 200
    )


def _req(host: str, headers: dict[str, str] | None = None):
    class _Req:
        def __init__(self) -> None:
            self.client = type("C", (), {"host": host})()
            self.headers = headers or {}

    return _Req()


def test_forwarded_client_header_is_only_trusted_from_a_configured_proxy(monkeypatch):
    """A sibling container on the shared Docker network must not be able to forge
    a fresh client IP per attempt and walk past the lockout."""
    from zengrowth.api.routers.auth import _client_key

    get_settings.cache_clear()
    # Default: loopback only. A private Docker peer is keyed on itself.
    assert _client_key(_req("127.0.0.1", {"x-real-ip": "198.51.100.4"})) == "198.51.100.4"
    assert _client_key(_req("172.18.0.5", {"x-real-ip": "198.51.100.4"})) == "172.18.0.5"
    assert _client_key(_req("8.8.8.8", {"x-real-ip": "198.51.100.4"})) == "8.8.8.8"

    # Container-nginx deployments name the Docker subnet explicitly.
    monkeypatch.setenv("LOGIN_TRUSTED_PROXIES", "172.18.0.0/16")
    get_settings.cache_clear()
    assert _client_key(_req("172.18.0.5", {"x-real-ip": "198.51.100.4"})) == "198.51.100.4"
    assert (
        _client_key(_req("172.18.0.5", {"x-forwarded-for": "198.51.100.4, 172.18.0.5"}))
        == "198.51.100.4"
    )
    assert _client_key(_req("172.18.0.5", {})) == "172.18.0.5"
    # A peer outside the configured range still cannot name the client.
    assert _client_key(_req("10.9.9.9", {"x-real-ip": "198.51.100.4"})) == "10.9.9.9"
    get_settings.cache_clear()


def test_proxy_token_identifies_the_edge_without_trusting_the_subnet(monkeypatch):
    """On a shared Docker network, peer addresses cannot distinguish nginx from a
    sibling container, so the edge proves itself with a shared secret instead."""
    from zengrowth.api.routers.auth import _client_key

    monkeypatch.setenv("LOGIN_PROXY_TOKEN", "edge-secret")
    get_settings.cache_clear()

    # nginx: correct token from any peer address -> forwarded client is trusted.
    assert (
        _client_key(_req("172.18.0.7", {"x-zengrowth-proxy-token": "edge-secret", "x-real-ip": "198.51.100.4"}))
        == "198.51.100.4"
    )
    # A sibling container on the same network without the token cannot forge it.
    assert _client_key(_req("172.18.0.9", {"x-real-ip": "203.0.113.7"})) == "172.18.0.9"
    assert (
        _client_key(_req("172.18.0.9", {"x-zengrowth-proxy-token": "wrong", "x-real-ip": "203.0.113.7"}))
        == "172.18.0.9"
    )
    get_settings.cache_clear()


def test_proxy_token_comparison_tolerates_a_junk_header(monkeypatch):
    """The header is attacker-controlled: hmac.compare_digest raises TypeError on
    non-ASCII strings, which would turn junk into a 500 on the login route."""
    from zengrowth.api.routers.auth import _client_key

    monkeypatch.setenv("LOGIN_PROXY_TOKEN", "edge-secret")
    get_settings.cache_clear()
    for junk in ("tökén", "", "x" * 5000):
        assert (
            _client_key(_req("172.18.0.9", {"x-zengrowth-proxy-token": junk, "x-real-ip": "203.0.113.7"}))
            == "172.18.0.9"
        )
    get_settings.cache_clear()
