"""Unit tests for CV alignment helpers."""

from datetime import date

from zengrowth.config import Settings
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials.cv_alignment import (
    compose_summary_from_claims,
    cv_grounding_profile,
    detect_alignment_gaps,
    rank_evidence_for_job,
    split_summary_sentences,
)
from zengrowth.materials.evidence import ParsedEvidence
from zengrowth.models import Job, JobSource


def _job(**kwargs) -> Job:
    base = Job(
        company="Novartis",
        title="Director Agentic AI",
        location="London",
        posting_date=date(2026, 5, 20),
        description="Agentic AI for drug development using LangGraph.",
        source=JobSource.manual,
        dedup_hash=dedup_hash("Novartis", "Director Agentic AI", date(2026, 5, 20)),
        job_summary={
            "requirements": ["LangGraph", "AutoGen", "healthcare AI"],
            "company_domain": "pharma",
        },
        fit_score=88.0,
    )
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_split_summary_sentences():
    parts = split_summary_sentences("First sentence. Second sentence! Third?")
    assert len(parts) == 3


def test_rank_evidence_prefers_jd_overlap():
    job = _job()
    evidence = [
        ParsedEvidence(
            id="low",
            category="x",
            claim_text="Unrelated finance reporting.",
            verified=True,
            tags=[],
        ),
        ParsedEvidence(
            id="high",
            category="y",
            claim_text="Built LangGraph multi-agent platforms for enterprise AI.",
            verified=True,
            tags=["agentic"],
        ),
    ]
    ranked = rank_evidence_for_job(evidence, job)
    assert ranked[0]["id"] == "high"
    assert "langgraph" in ranked[0]["jd_match"]


def test_detect_alignment_gaps_flags_missing_entities():
    job = _job()
    evidence = [
        ParsedEvidence(
            id="e1",
            category="x",
            claim_text="Built LangGraph agent systems.",
            verified=True,
            tags=[],
        )
    ]
    gaps = detect_alignment_gaps(evidence, job, cv_grounding_profile(job, Settings(anthropic_api_key="test")))
    terms = {g["term"] for g in gaps}
    assert "autogen" in terms


def test_compose_summary_stitches_verified_claims():
    evidence = [
        ParsedEvidence(
            id="e1",
            category="x",
            claim_text="Delivered agentic AI platforms",
            verified=True,
            tags=[],
        )
    ]
    ranked = [{"id": "e1", "score": 2}]
    text = compose_summary_from_claims(ranked, evidence, max_words=10)
    assert "agentic" in text.lower()
