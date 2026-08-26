"""Tests for in-app API-key setup + first-run status (PS-P1)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth import secrets_store
from zengrowth.api.main import app
from zengrowth.api.routers import settings as settings_router
from zengrowth.config import Settings
from zengrowth.db import get_session


def _fresh_settings(tmp_path) -> Settings:
    # Point the keyring + db url at a tmp dir so the test never touches data/.
    return Settings(
        anthropic_api_key=None,
        tavily_api_key=None,
        openai_api_key=None,
        database_url=f"sqlite:///{tmp_path}/zen.db",
    )


def test_secret_roundtrip_and_tamper(tmp_path, monkeypatch):
    settings = _fresh_settings(tmp_path)
    token = secrets_store.encrypt("sk-secret-value", settings=settings)
    assert token != "sk-secret-value"
    assert secrets_store.decrypt(token, settings=settings) == "sk-secret-value"
    # A tampered ciphertext fails the MAC and decrypts to None.
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert secrets_store.decrypt(tampered, settings=settings) is None


def test_status_and_key_lifecycle(tmp_path, session: Session, monkeypatch):
    settings = _fresh_settings(tmp_path)
    monkeypatch.setattr(settings_router, "get_settings", lambda: settings)
    # Don't hit the network when validating the key.
    monkeypatch.setattr(settings_router, "_validate_anthropic_key", lambda key, model: None)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        status = client.get("/api/settings/status").json()
        assert status["anthropic_configured"] is False
        assert status["anthropic_source"] is None
        assert status["setup_complete"] is False

        resp = client.put("/api/settings/keys", json={"provider": "anthropic", "key": "sk-test-123456"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["anthropic_configured"] is True
        assert body["anthropic_source"] == "stored"
        # The running Settings singleton picked up the key (no restart).
        assert settings.anthropic_api_key == "sk-test-123456"

        # Reload via a new request: the stored secret persists.
        assert client.get("/api/settings/status").json()["anthropic_configured"] is True

        # Delete removes the stored key (no env var in the test environment).
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        after = client.delete("/api/settings/keys/anthropic").json()
        assert after["anthropic_configured"] is False
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_put_rejects_invalid_key(tmp_path, session: Session, monkeypatch):
    settings = _fresh_settings(tmp_path)
    monkeypatch.setattr(settings_router, "get_settings", lambda: settings)

    def reject(key, model):
        raise ValueError("The API key was rejected by Anthropic.")

    monkeypatch.setattr(settings_router, "_validate_anthropic_key", reject)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        resp = client.put("/api/settings/keys", json={"provider": "anthropic", "key": "sk-bad-000000"})
        assert resp.status_code == 400
        assert "rejected" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_unknown_provider_rejected(tmp_path, session: Session, monkeypatch):
    settings = _fresh_settings(tmp_path)
    monkeypatch.setattr(settings_router, "get_settings", lambda: settings)

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        resp = client.put("/api/settings/keys", json={"provider": "wat", "key": "sk-test-123456"})
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_session, None)
