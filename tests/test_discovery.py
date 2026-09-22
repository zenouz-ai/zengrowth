"""Discovery API: Tavily search persistence and history."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.ingestion.tavily_search import DiscoveryResult, DiscoveryRun


def test_discovery_search_persists_and_lists(session: Session):
    def override_get_session() -> Iterator[Session]:
        yield session

    run = DiscoveryRun(
        query="Head of AI London",
        scoped_query="Head of AI London job opening apply",
        results=[
            DiscoveryResult(
                title="Director of AI",
                url="https://boards.greenhouse.io/acme/jobs/123",
                snippet="Lead our AI team.",
                score=0.91,
            )
        ],
    )

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        with patch("zengrowth.api.routers.discovery.discover", return_value=run):
            response = client.post(
                "/api/discovery/search",
                json={"query": "Head of AI London", "max_results": 10},
            )
        assert response.status_code == 200
        hits = response.json()
        assert len(hits) == 1
        assert hits[0]["url"].startswith("https://boards.greenhouse.io")

        listed = client.get("/api/discovery/searches?limit=5")
        assert listed.status_code == 200
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["query"] == "Head of AI London"
        assert rows[0]["result_count"] == 1
        assert rows[0]["results"][0]["title"] == "Director of AI"
    finally:
        app.dependency_overrides.clear()
