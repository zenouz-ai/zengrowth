"""Web-search allowlist for interview materials."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.journey import (
    JOURNEY_SUMMARY_SECTIONS,
    REJECTION_REFLECTION_SECTIONS,
    generate_journey_summary,
    generate_rejection_reflection,
)
from zengrowth.interviews.material_policy import PACK_TYPES, material_allows_web
from zengrowth.interviews.packs import generate_pack
from zengrowth.materials import generator
from zengrowth.models import Interview, InterviewRoundType, Job, OutcomeResult


def test_material_allows_web_policy() -> None:
    assert material_allows_web("company_briefing") is True
    assert material_allows_web("culture_comparison") is True
    assert material_allows_web("rejection_reflection") is True
    assert material_allows_web("journey_summary") is True
    assert material_allows_web("debrief") is True
    assert material_allows_web("offer_evaluation") is True
    assert material_allows_web("onboarding_pack") is True
    assert material_allows_web("departure_pack") is True

    assert material_allows_web("session_prep") is False
    assert material_allows_web("email_draft") is False
    assert material_allows_web("offer_response") is False
    assert material_allows_web("answer") is False


def test_all_pack_types_except_session_prep_allow_web() -> None:
    for pack_type in PACK_TYPES:
        expected = pack_type != "session_prep"
        assert material_allows_web(pack_type) is expected, pack_type


class _RecordingClient:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown
        self.allow_web_flags: list[bool] = []
        self.system_prompts: list[str] = []

    def generate_document(  # noqa: ANN001
        self, system, user, model, max_tokens, *, operation_name, allow_web=True
    ):
        self.allow_web_flags.append(allow_web)
        self.system_prompts.append(system)
        return self.markdown, [{"url": "https://example.com/docs", "title": "Docs"}], allow_web


def _reflection_markdown() -> str:
    parts = [f"## {section}\nContent.\n" for section in REJECTION_REFLECTION_SECTIONS]
    return "\n".join(parts)


def _journey_markdown() -> str:
    parts = [f"## {section}\nContent.\n" for section in JOURNEY_SUMMARY_SECTIONS]
    return "\n".join(parts)


def _job(session: Session) -> Job:
    job = Job(
        company="Intact",
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash("Intact", "Director of AI", None),
        outcome_result=OutcomeResult.rejected,
        outcome_notes="Strong technical depth; deepen Azure + Databricks narrative.",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_rejection_reflection_allows_web(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    client = _RecordingClient(_reflection_markdown())
    material = generate_rejection_reflection(session, job, client=client)
    assert client.allow_web_flags == [True]
    assert "web search" in client.system_prompts[0].lower()
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "https://example.com/docs" in document


def test_journey_summary_allows_web(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    for round_type in (
        InterviewRoundType.recruiter_screen,
        InterviewRoundType.technical,
        InterviewRoundType.leadership_panel,
    ):
        session.add(
            Interview(
                job_id=job.id or 0,
                round_type=round_type,
                title=round_type.value,
            )
        )
    session.commit()
    client = _RecordingClient(_journey_markdown())
    material = generate_journey_summary(session, job, client=client)
    assert client.allow_web_flags == [True]
    assert "never invent process facts from the web" in client.system_prompts[0].lower()
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "https://example.com/docs" in document


def test_session_prep_disables_web(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session)
    # Minimal session_prep body with required headings.
    from zengrowth.interviews.material_policy import SESSION_PREP_SECTIONS

    body = "\n".join(f"## {s}\nBody.\n" for s in SESSION_PREP_SECTIONS)
    client = _RecordingClient(body)
    generate_pack(session, job, pack_type="session_prep", client=client)
    assert client.allow_web_flags == [False]
