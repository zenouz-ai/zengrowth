"""Phase 0/1: the app factory builds a working instance and mounts routes under
the /api prefix (with /health left unprefixed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from zengrowth.api.main import app, create_app


def _paths(application) -> set[str]:
    return {route.path for route in application.routes if hasattr(route, "path")}


def test_create_app_returns_an_independent_instance():
    fresh = create_app()
    assert fresh is not app
    client = TestClient(fresh)
    assert client.get("/health").json() == {"status": "ok"}


def test_health_is_unprefixed():
    paths = _paths(app)
    assert "/health" in paths
    assert "/api/health" not in paths


def test_api_prefix_is_mounted():
    paths = _paths(app)
    assert "/api/jobs" in paths
    assert "/api/ingestion/run" in paths
    assert "/api/discovery/search" in paths
    assert "/api/discovery/searches" in paths
    assert "/api/audit" in paths
