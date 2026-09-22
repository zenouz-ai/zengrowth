"""Rejection reflection (INT-07) and multi-round journey summary (INT-09)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..models import (
    GeneratedMaterial,
    InterviewRoundType,
    Job,
    MaterialAudience,
    OutcomeResult,
)
from ..observability.tracing import pipeline_run
from .debrief import _write_internal_material
from .markdown_format import strip_llm_envelope, wrap_obsidian_pack
from .material_policy import material_allows_web, missing_sections
from .packs import PackClient, _build_pack_client, _profile_context, _strip_code_fence
from .service import list_interviews, load_cross_job_learnings

REJECTION_REFLECTION_SECTIONS: list[str] = [
    "Process Summary",
    "Feedback Received",
    "What Went Well",
    "Gaps Versus The Bar",
    "Skills And Knowledge To Deepen",
    "Evidence To Add To Library",
    "Posture For The Next Similar Role",
]

JOURNEY_SUMMARY_SECTIONS: list[str] = [
    "Organisation And Role",
    "Timeline Of Rounds",
    "Conversations And Themes",
    "Materials Used",
    "Outcome And Feedback",
    "What Worked",
    "What Needs To Improve",
    "Key Takeaways",
    "Reusable Learnings",
]

PROPER_ROUND_TYPES = frozenset(
    {
        InterviewRoundType.recruiter_screen,
        InterviewRoundType.hiring_manager,
        InterviewRoundType.leadership_panel,
        InterviewRoundType.technical,
        InterviewRoundType.team,
        InterviewRoundType.final_round,
    }
)

TERMINAL_OUTCOMES = frozenset(
    {
        OutcomeResult.rejected,
        OutcomeResult.withdrawn,
        OutcomeResult.offer,
        OutcomeResult.accepted,
        OutcomeResult.declined,
    }
)

_REFLECTION_SYSTEM = """You help a senior candidate reflect after a job process ends without an accept.
Write a private, honest rejection reflection in Markdown.

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
- Do NOT invent feedback, rounds, or outcomes that are not in outcome_notes, debriefs, or rounds.
- Skills And Knowledge To Deepen may use web search to name current tools, frameworks, and
  widely accepted practices related to skills the candidate actually practiced or was exposed to
  in this process. Prefer primary/vendor docs over blogs. Do not invent that they used a tool
  they did not encounter in the provided materials.
- Evidence To Add To Library should propose Library-ready bullets the candidate can verify later.
- Avoid em dashes. Be direct and kind.
"""

_JOURNEY_SYSTEM = """You write a private end-of-process journey summary for a senior candidate
after a multi-round interview process. Capture organisation, timeline, themes, materials,
outcome, and reusable learning.

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
- Ground timeline, conversations, materials used, and outcome only in the provided rounds,
  debriefs, packs, and outcome notes. Never invent process facts from the web.
- Reusable Learnings and What Needs To Improve may use web search to refresh current tools,
  frameworks, and widely accepted practices that relate to skills practiced on this journey.
  Prefer primary/vendor docs; cite when you rely on web facts.
- Reusable Learnings should separate process lessons from substantive skills practiced.
- Avoid em dashes. Be concise and candid.
"""


def count_proper_interviews(session: Session, job_id: int) -> int:
    rounds = list_interviews(session, job_id)
    return sum(1 for r in rounds if r.round_type in PROPER_ROUND_TYPES)


def journey_summary_eligible(session: Session, job: Job) -> bool:
    if job.outcome_result not in TERMINAL_OUTCOMES:
        return False
    return count_proper_interviews(session, job.id or 0) >= 3


def _read_internal_snippets(
    session: Session, job_id: int, *, limit: int = 20
) -> list[dict[str, Any]]:
    from ..materials.files import read_text_content

    rows = list(
        session.exec(
            select(GeneratedMaterial)
            .where(
                GeneratedMaterial.job_id == job_id,
                GeneratedMaterial.audience == MaterialAudience.internal,
            )
            .order_by(GeneratedMaterial.created_at.desc())
            .limit(limit)
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        body = read_text_content(row) or ""
        out.append(
            {
                "id": row.id,
                "material_type": row.material_type,
                "title": row.title,
                "interview_id": row.interview_id,
                "status": row.status,
                "body": strip_llm_envelope(body)[:6000],
            }
        )
    return out


def _rounds_payload(session: Session, job_id: int) -> list[dict[str, Any]]:
    rounds = list_interviews(session, job_id)
    return [
        {
            "id": r.id,
            "round_type": r.round_type.value,
            "title": r.title,
            "format": r.format.value,
            "status": r.status.value,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "participants": r.participants,
            "notes": r.notes,
            "has_transcript": bool(r.transcript),
        }
        for r in rounds
    ]


def generate_rejection_reflection(
    session: Session,
    job: Job,
    *,
    feedback_notes: str | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    settings = settings or get_settings()
    notes = (feedback_notes if feedback_notes is not None else job.outcome_notes) or ""
    with pipeline_run(
        session,
        pipeline_type="rejection_reflection",
        entity_type="job",
        entity_id=job.id,
        detail={"type": "rejection_reflection"},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        payload = {
            "required_sections": REJECTION_REFLECTION_SECTIONS,
            "job": _job_context(job),
            "candidate_profile": _profile_context(settings),
            "outcome": {
                "stage": job.outcome_stage.value if job.outcome_stage else None,
                "result": job.outcome_result.value if job.outcome_result else None,
                "rejection_stage": job.rejection_stage.value if job.rejection_stage else None,
                "outcome_notes": notes,
            },
            "rounds": _rounds_payload(session, job.id or 0),
            "internal_materials": _read_internal_snippets(session, job.id or 0),
            "learnings_from_past_interview_processes": load_cross_job_learnings(
                session, exclude_job_id=job.id
            ),
            "today": datetime.now(UTC).date().isoformat(),
        }
        markdown, citations, web_used = client.generate_document(
            _REFLECTION_SYSTEM,
            "Write the rejection reflection.\n\n" + json.dumps(payload, indent=2, default=str),
            settings.material_model(),
            settings.interview_pack_max_tokens,
            operation_name="generate_rejection_reflection",
            allow_web=material_allows_web("rejection_reflection"),
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("rejection reflection returned an empty document")
        missing = missing_sections(markdown, REJECTION_REFLECTION_SECTIONS)
        title = f"Rejection reflection — {job.company}"
        document = wrap_obsidian_pack(
            markdown,
            title=title,
            job=job,
            pack_type="rejection_reflection",
            web_search_used=web_used,
            citations=citations,
        )
        return _write_internal_material(
            session,
            job,
            material_type="rejection_reflection",
            title=title,
            document=document,
            audit_detail={
                "missing_sections": missing,
                "has_feedback_notes": bool(notes.strip()),
                "web_search_used": web_used,
                "citation_count": len(citations),
            },
        )


def generate_journey_summary(
    session: Session,
    job: Job,
    *,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    if not journey_summary_eligible(session, job):
        raise ValueError(
            "journey summary requires a terminal outcome and at least 3 proper interview rounds"
        )
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="journey_summary",
        entity_type="job",
        entity_id=job.id,
        detail={"type": "journey_summary"},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        payload = {
            "required_sections": JOURNEY_SUMMARY_SECTIONS,
            "job": _job_context(job),
            "candidate_profile": _profile_context(settings),
            "outcome": {
                "stage": job.outcome_stage.value if job.outcome_stage else None,
                "result": job.outcome_result.value if job.outcome_result else None,
                "rejection_stage": job.rejection_stage.value if job.rejection_stage else None,
                "outcome_notes": job.outcome_notes,
                "applied_at": job.applied_at.isoformat() if job.applied_at else None,
                "first_response_at": job.first_response_at.isoformat()
                if job.first_response_at
                else None,
            },
            "rounds": _rounds_payload(session, job.id or 0),
            "proper_round_count": count_proper_interviews(session, job.id or 0),
            "internal_materials": _read_internal_snippets(session, job.id or 0, limit=40),
            "learnings_from_past_interview_processes": load_cross_job_learnings(
                session, exclude_job_id=job.id
            ),
            "today": datetime.now(UTC).date().isoformat(),
        }
        markdown, citations, web_used = client.generate_document(
            _JOURNEY_SYSTEM,
            "Write the journey summary.\n\n" + json.dumps(payload, indent=2, default=str),
            settings.material_model(),
            settings.interview_pack_max_tokens,
            operation_name="generate_journey_summary",
            allow_web=material_allows_web("journey_summary"),
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("journey summary returned an empty document")
        missing = missing_sections(markdown, JOURNEY_SUMMARY_SECTIONS)
        title = f"Journey summary — {job.company}"
        document = wrap_obsidian_pack(
            markdown,
            title=title,
            job=job,
            pack_type="journey_summary",
            web_search_used=web_used,
            citations=citations,
        )
        return _write_internal_material(
            session,
            job,
            material_type="journey_summary",
            title=title,
            document=document,
            audit_detail={
                "missing_sections": missing,
                "proper_round_count": payload["proper_round_count"],
                "web_search_used": web_used,
                "citation_count": len(citations),
            },
        )
