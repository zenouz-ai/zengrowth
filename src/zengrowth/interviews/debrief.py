"""Post-interview debriefs and email drafts (INT-03).

A debrief turns a pasted transcript / meeting notes into a structured learning
artifact; the next round's prep pack consumes it (INT-04). Email drafts are
approval-by-design: ZenGrowth never sends anything — the operator copies the
text out.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import (
    ActorType,
    GeneratedMaterial,
    Interview,
    InterviewStatus,
    Job,
    MaterialAudience,
)
from ..observability.tracing import pipeline_run
from .markdown_format import slugify, wrap_obsidian_debrief
from .material_policy import (
    DEBRIEF_SECTIONS,
    DEBRIEF_SYSTEM_PROMPT,
    load_prior_debriefs,
    missing_sections,
    quality_warnings,
)
from .packs import PackClient, _build_pack_client

# Shared by every email-shaped internal material (INT-03 drafts, OFF-01
# offer responses): the operator copies the text out; the app never sends.
NEVER_SENT_BANNER = (
    "> **Draft email — nothing is sent by ZenGrowth.** Review, edit, and "
    "send it yourself from your own mailbox.\n\n"
)

_EMAIL_SYSTEM = """You draft professional emails for a senior job candidate.
Write in the candidate's voice: warm, direct, concise, senior. Do not invent facts,
availability, or commitments beyond what the instructions and context state. Avoid em dashes.

Return ONLY the email draft in Markdown with exactly two sections:
## Subject
(one line)
## Body
(the email body, ready to paste, ending with an appropriate sign-off using the candidate's name)"""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def _write_internal_material(
    session: Session,
    job: Job,
    *,
    material_type: str,
    title: str,
    document: str,
    interview_id: int | None = None,
    audit_detail: dict[str, Any],
    evidence_ids: list[str] | None = None,
) -> GeneratedMaterial:
    """Persist an internal markdown material; shared by debriefs, email drafts,
    and the offer-stage generators (OFF-01/OFF-03)."""
    from ..materials.generator import MATERIALS_ROOT, _next_version

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    out_dir = MATERIALS_ROOT / str(job.id) / f"{stamp}-{material_type.replace('_', '-')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{slugify(title)}.md"
    md_path.write_text(document, encoding="utf-8")
    version = _next_version(session, job.id or 0, material_type)
    material = GeneratedMaterial(
        job_id=job.id or 0,
        interview_id=interview_id,
        material_type=material_type,
        audience=MaterialAudience.internal,
        title=title,
        markdown_path=str(md_path),
        evidence_ids=evidence_ids or [],
        version=version,
        status="created_markdown",
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.agent,
        action=f"generate_{material_type}",
        entity_type="job",
        entity_id=job.id,
        detail={"material_id": material.id, "version": version, **audit_detail},
    )
    return material


def generate_debrief(
    session: Session,
    job: Job,
    interview: Interview,
    *,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Turn a round's transcript/notes into a structured debrief material."""
    source_text = (interview.transcript or "").strip() or (interview.notes or "").strip()
    if not source_text:
        raise ValueError(
            "no transcript or notes on this round yet: paste the transcript "
            "(or your meeting notes) before generating a debrief"
        )
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="interview_debrief",
        entity_type="job",
        entity_id=job.id,
        detail={"interview_id": interview.id},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        payload = {
            "required_sections": DEBRIEF_SECTIONS,
            "job": _job_context(job),
            "interview": {
                "round_type": interview.round_type.value,
                "title": interview.title,
                "occurred_at": interview.occurred_at.isoformat() if interview.occurred_at else None,
                "participants": interview.participants,
            },
            "transcript_or_notes": source_text,
            "earlier_round_learnings": load_prior_debriefs(session, job.id or 0) or None,
        }
        markdown, citations, web_used = client.generate_document(
            DEBRIEF_SYSTEM_PROMPT,
            (
                "Write the debrief for this interview round.\n"
                "Use `##` headings exactly matching required_sections, in order.\n"
                "Include up to 3 ### Gap N blocks with 'answer to learn' scripts.\n\n"
                f"{json.dumps(payload, indent=2, default=str)}"
            ),
            settings.scoring_model,
            settings.interview_pack_max_tokens,
            operation_name="generate_debrief",
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("debrief generation returned an empty document")
        missing = missing_sections(markdown, DEBRIEF_SECTIONS)
        warnings = quality_warnings(markdown, material_kind="debrief")
        round_label = interview.title or interview.round_type.value.replace("_", " ")
        debrief_title = f"Debrief — {round_label}"
        document = wrap_obsidian_debrief(
            markdown,
            title=debrief_title,
            job=job,
            web_search_used=web_used,
            citations=citations,
        )
        material = _write_internal_material(
            session,
            job,
            material_type="debrief",
            title=debrief_title,
            document=document,
            interview_id=interview.id,
            audit_detail={
                "interview_id": interview.id,
                "web_search_used": web_used,
                "citation_count": len(citations),
                "source_chars": len(source_text),
                "missing_sections": missing,
                "quality_warnings": warnings,
            },
        )
        # A debrief implies the round happened.
        if interview.status == InterviewStatus.scheduled:
            interview.status = InterviewStatus.completed
            interview.updated_at = datetime.now(UTC)
            session.add(interview)
            session.commit()
        return material


def generate_email_draft(
    session: Session,
    job: Job,
    *,
    instructions: str | None = None,
    inbound_email: str | None = None,
    interview: Interview | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Draft a reply/follow-up email as an internal material (never sent)."""
    if not (instructions or "").strip() and not (inbound_email or "").strip():
        raise ValueError(
            "nothing to draft from: paste the email you received and/or say "
            "what the email should do"
        )
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="email_draft",
        entity_type="job",
        entity_id=job.id,
        detail={"interview_id": interview.id if interview else None},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        payload = {
            "candidate_name": settings.user_full_name,
            "job": _job_context(job),
            "interview": (
                {
                    "round_type": interview.round_type.value,
                    "title": interview.title,
                    "scheduled_at": interview.scheduled_at.isoformat()
                    if interview.scheduled_at
                    else None,
                }
                if interview
                else None
            ),
            "inbound_email": (inbound_email or "").strip() or None,
            "instructions": (instructions or "").strip()
            or "Write an appropriate, professional reply.",
        }
        markdown, _citations, _web = client.generate_document(
            _EMAIL_SYSTEM,
            f"Draft the email.\n\n{json.dumps(payload, indent=2, default=str)}",
            settings.scoring_model,
            2000,
            operation_name="generate_email_draft",
            allow_web=False,
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("email draft generation returned an empty document")
        banner = NEVER_SENT_BANNER
        purpose = (instructions or "").strip() or "Reply draft"
        title = f"Email draft — {purpose[:60]}"
        return _write_internal_material(
            session,
            job,
            material_type="email_draft",
            title=title,
            document=banner + markdown,
            interview_id=interview.id if interview else None,
            audit_detail={
                "interview_id": interview.id if interview else None,
                "has_inbound_email": bool((inbound_email or "").strip()),
            },
        )
