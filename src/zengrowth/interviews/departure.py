"""Departure pack — leave the current role well (OFF-05).

Accepting an offer starts a second workflow: resigning from the current
employer. The departure pack turns the accepted offer's dates plus a short
operator-supplied context into one internal document: notice arithmetic, a
ready-to-send resignation letter, the manager-conversation script, a
counter-offer stance decided in advance, the handover plan, achievements
captured while they are fresh (paste-ready for the evidence bank), exit
interview guardrails, and the practical leaving checklist. Nothing is ever
sent by ZenGrowth; the operator copies the letter out.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlmodel import Session

from ..config import Settings, get_settings
from ..models import GeneratedMaterial, Job
from ..observability.tracing import pipeline_run
from .debrief import _write_internal_material
from .markdown_format import strip_llm_envelope, wrap_offer_document
from .material_policy import line_count, missing_sections
from .offers import (
    PackClient,
    _accepted_or_latest_offer,
    _build_pack_client,
    _offer_context,
    _strip_code_fence,
)

# Structure follows UK resignation practice (Acas / GOV.UK): manager hears
# first and in person; the letter is unambiguous with notice and last day;
# criticism waits for the exit interview; the handover protects the reference.
DEPARTURE_SECTIONS: list[str] = [
    "Key Dates And Notice",
    "Resignation Letter",
    "Manager Conversation Script",
    "Counter-Offer Stance",
    "Handover Plan",
    "Achievements And Reflections",
    "Exit Interview Notes",
    "Leaving Checklist",
    "Information To Keep And Return",
]

DEPARTURE_LINE_BUDGET: tuple[int, int] = (120, 350)

DEPARTURE_SYSTEM_PROMPT = """You are a senior career coach helping a candidate resign professionally and hand over well.
Write a focused, practical departure pack in Markdown.

Priority order for facts (highest first):
1. The operator-supplied current-role context and the accepted offer's dates
2. The candidate's profile and new role details
3. Web search only for statutory/contractual norms (notice rules, accrued holiday, references)
   in the current role's jurisdiction

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
  Do NOT include YAML frontmatter or a top-level `#` title.
- Key Dates And Notice: work the arithmetic — notice period vs the new role's start date,
  proposed resignation day, resulting last working day, accrued holiday options; flag any
  clash between notice and start date explicitly.
- Resignation Letter: ready to send. Unambiguous resignation statement, the notice being
  given and the exact proposed last working day, brief thanks, an offer to support the
  handover, the candidate's name. No reasons, no grievances, no new-employer name.
- Manager Conversation Script: the manager hears first, in person or on a call, before the
  letter lands; a short positive opening, the decision stated as final, key lines to hold,
  and calm responses to likely reactions.
- Counter-Offer Stance: a stance decided in advance, grounded in why the candidate chose the
  new role; script a polite, firm decline unless the operator's notes say otherwise.
- Handover Plan: responsibilities, in-flight work, systems and access, key contacts, and the
  documentation to write, ordered so the most critical transfers happen first.
- Achievements And Reflections: capture measurable achievements and lessons from this role
  while they are fresh — written as evidence-bank-ready bullets (metric + action + result)
  the candidate can paste into their Library, plus honest reflections on what to do
  differently next time.
- Exit Interview Notes: what is worth saying constructively, what to leave unsaid, and why
  the reference matters more than catharsis.
- Leaving Checklist: practical admin as a checkbox list — expenses, equipment return,
  pension/benefits, payslips and P45-equivalents, personal files and contacts, handover
  sign-off, references secured, non-solicitation/confidentiality obligations reviewed.
- Information To Keep And Return: what the candidate may keep (personal records, own
  contacts, personal development notes) versus what belongs to the employer; when in doubt,
  say leave it.
- Target 150-300 lines. Be concise, specific, and calm; never invent contract terms — flag
  anything unknown as "check your contract".
- Avoid em dashes; no wrapping code fence around the whole document."""


def _departure_context(
    *,
    current_company: str | None,
    current_role: str | None,
    manager_name: str | None,
    notice_period: str | None,
    last_day_target: date | None,
    responsibilities: str | None,
    achievements: str | None,
    notes: str | None,
) -> dict[str, Any]:
    return {
        "current_company": (current_company or "").strip() or None,
        "current_role": (current_role or "").strip() or None,
        "manager_name": (manager_name or "").strip() or None,
        "contractual_notice_period": (notice_period or "").strip() or None,
        "preferred_last_day": last_day_target.isoformat() if last_day_target else None,
        "key_responsibilities": (responsibilities or "").strip()[:6000] or None,
        "achievements_notes": (achievements or "").strip()[:6000] or None,
        "operator_notes": (notes or "").strip()[:3000] or None,
    }


def generate_departure_pack(
    session: Session,
    job: Job,
    *,
    current_company: str | None = None,
    current_role: str | None = None,
    manager_name: str | None = None,
    notice_period: str | None = None,
    last_day_target: date | None = None,
    responsibilities: str | None = None,
    achievements: str | None = None,
    notes: str | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Generate the leave-well pack (OFF-05) for the accepted offer's job."""
    settings = settings or get_settings()
    offer = _accepted_or_latest_offer(session, job.id or 0)
    with pipeline_run(
        session,
        pipeline_type="departure_pack",
        entity_type="job",
        entity_id=job.id,
        detail={"offer_id": offer.id if offer else None},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        payload = {
            "required_sections": DEPARTURE_SECTIONS,
            "candidate_name": settings.user_full_name,
            "current_employment": _departure_context(
                current_company=current_company,
                current_role=current_role,
                manager_name=manager_name,
                notice_period=notice_period,
                last_day_target=last_day_target,
                responsibilities=responsibilities,
                achievements=achievements,
                notes=notes,
            ),
            "new_role": {
                "company": job.company,
                "title": job.title,
                "location": job.location,
                "accepted_offer": _offer_context(offer) if offer else None,
            },
            "today": datetime.now(UTC).date().isoformat(),
        }
        markdown, citations, web_used = client.generate_document(
            DEPARTURE_SYSTEM_PROMPT,
            (
                "Prepare the departure pack for leaving the current role described below.\n"
                "Use `##` headings exactly matching required_sections, in order.\n"
                "Work the notice arithmetic against the accepted offer's start date.\n\n"
                f"{json.dumps(payload, indent=2, default=str)}"
            ),
            settings.scoring_model,
            settings.interview_pack_max_tokens,
            operation_name="generate_departure_pack",
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("departure pack generation returned an empty document")
        missing = missing_sections(markdown, DEPARTURE_SECTIONS)
        warnings: list[str] = []
        lines = line_count(strip_llm_envelope(markdown))
        if lines > DEPARTURE_LINE_BUDGET[1]:
            warnings.append(
                f"departure pack exceeds line budget ({lines} > {DEPARTURE_LINE_BUDGET[1]})"
            )
        label = (current_company or "").strip() or "current role"
        title = f"Departure pack — leaving {label}"
        document = wrap_offer_document(
            markdown,
            title=title,
            job=job,
            material_type="departure_pack",
            web_search_used=web_used,
            citations=citations,
        )
        return _write_internal_material(
            session,
            job,
            material_type="departure_pack",
            title=title,
            document=document,
            audit_detail={
                "offer_id": offer.id if offer else None,
                "web_search_used": web_used,
                "citation_count": len(citations),
                "missing_sections": missing,
                "quality_warnings": warnings,
                "has_achievements": bool((achievements or "").strip()),
            },
        )
