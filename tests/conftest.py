"""Shared fixtures: in-memory SQLite session + canned LLM response."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from zengrowth import models  # noqa: F401  populate metadata

    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def fake_score_response() -> dict[str, Any]:
    return {
        "role_relevance": {"score": 80, "reason": "Title matches."},
        "ai_technical_alignment": {"score": 70, "reason": "MLOps mentioned."},
        "leadership_alignment": {"score": 65, "reason": "Manages a small team."},
        "compensation_fit": {"score": 60, "reason": "Slightly below target."},
        "domain_fit": {"score": 75, "reason": "FinTech."},
        "strategic_career_value": {"score": 72, "reason": "Greenfield platform."},
        "hybrid_location_fit": {"score": 85, "reason": "London hybrid 2 days."},
        "application_effort": {"score": 3, "reason": "Standard."},
        "success_probability": {"score": 0.4, "reason": "Credible match."},
        "match_quality": {"score": 74, "reason": "Strong overall."},
        "summary": "Solid match; comp slightly below target.",
        "_usage": {"input_tokens": 1200, "output_tokens": 450},
    }
