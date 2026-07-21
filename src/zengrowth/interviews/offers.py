"""Offer stage — record, evaluate, and respond to a job offer (OFF-01).

The natural end of the post-application journey: once a process reaches an
offer, the operator records its terms, generates a market-benchmarked
evaluation (web research, provenance-labelled), and drafts an acceptance,
counter-offer, or clarification email. Nothing is ever sent by ZenGrowth —
every draft carries the never-sent banner and the operator copies it out.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import (
    ActorType,
    GeneratedMaterial,
    Job,
    JobOffer,
    LifecycleState,
    OfferStatus,
    OutcomeResult,
    OutcomeStage,
)
from ..observability.tracing import pipeline_run
from .debrief import NEVER_SENT_BANNER, _write_internal_material
from .markdown_format import strip_llm_envelope, wrap_offer_document
from .material_policy import line_count, missing_sections
from .packs import PackClient, _build_pack_client, _strip_code_fence

OFFER_RESPONSE_TYPES = ("accept", "counter", "clarify")

# Section schema informed by total-compensation evaluation practice: benchmark
# every component (base, bonus, equity, pension, holiday, benefits) against the
# market and the operator's own expectations before deciding the response.
OFFER_EVALUATION_SECTIONS: list[str] = [
    "Offer Summary",
    "Market Benchmark",
    "Against Your Expectations",
    "Benefits Assessment",
    "Gaps And Red Flags",
    "Negotiation Levers",
    "Recommendation",
    "Next Steps",
]

# Inserted after Offer Summary when the job carries negotiation history
# (prior offers and/or the candidate's sent responses): a revised offer is
# judged against what was asked, not just against the market.
NEGOTIATION_SECTION = "Movement From Last Round"


def evaluation_sections(*, negotiating: bool) -> list[str]:
    sections = list(OFFER_EVALUATION_SECTIONS)
    if negotiating:
        sections.insert(1, NEGOTIATION_SECTION)
    return sections


OFFER_EVALUATION_LINE_BUDGET: tuple[int, int] = (80, 300)

OFFER_EVAL_SYSTEM_PROMPT = """You are a senior compensation adviser evaluating a job offer for a candidate.
Write a focused, honest offer evaluation in Markdown.

Priority order for facts (highest first):
1. The recorded offer terms and pasted offer letter
2. The candidate's stated expectations and the job's posted compensation
3. Web search for current market salary/benefits benchmarks only

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
  Do NOT include YAML frontmatter or a top-level `#` title.
- Offer Summary: restate every component (base, bonus, equity, pension, holiday, benefits,
  start date, deadline) and an estimated total-compensation figure with the arithmetic shown.
- Movement From Last Round (only when required_sections includes it): compare this offer
  component-by-component against the previous offer(s) and each ask in the candidate's sent
  responses in negotiation_history — state what moved, what did not, and whether each ask was
  met, partially met, or ignored; judge whether the movement itself signals room for another
  round or a final position.
- Market Benchmark: compare each component against current market data for this role, seniority,
  and location; name the sources; state clearly when a figure is inferred rather than found.
- Against Your Expectations: compare against the candidate's minimum and target compensation
  and the job's posted range; say plainly whether the offer clears, meets, or misses them.
- Benefits Assessment: judge pension, holiday, healthcare, and other benefits against
  statutory baselines and market norms for the offer's jurisdiction (assume the job's
  location unless the offer says otherwise).
- Gaps And Red Flags: missing terms the candidate should get in writing (bonus mechanics,
  equity vesting, notice period, probation, hybrid policy), plus anything unusual.
- Negotiation Levers: the strongest 2-4 asks in priority order, each with a realistic range
  and a one-line justification grounded in the benchmark.
- Recommendation: one of accept / counter / clarify, with a two-sentence rationale.
- Next Steps: a short numbered checklist ordered against the response deadline.
- Target 100-250 lines. Be concise, specific, and numeric wherever possible.
- Never invent offer terms that were not provided; call them out as missing instead.
- Avoid em dashes; no wrapping code fence around the whole document."""

_OFFER_RESPONSE_SYSTEM = """You draft professional emails for a senior job candidate responding to a job offer.
Write in the candidate's voice: warm, direct, concise, senior. Never invent offer terms,
figures, dates, or commitments beyond what the provided context states. Avoid em dashes.

Response-type rules:
- accept: confirm acceptance clearly, restate the headline terms being accepted, ask for the
  contract / next steps, and thank them with genuine enthusiasm.
- counter: open with gratitude and enthusiasm for the role, then make a specific, justified
  ask grounded in the market evaluation and the candidate's value; frame it as a
  collaborative discussion, not a demand; keep secondary asks (holiday, start date) explicit
  but brief; close positively.
- clarify: list the specific terms that need to be confirmed in writing before a decision,
  politely and without signalling doubt about the role.

Return ONLY the email draft in Markdown with exactly two sections:
## Subject
(one line)
## Body
(the email body, ready to paste, ending with an appropriate sign-off using the candidate's name)"""


def list_offers(session: Session, job_id: int) -> list[JobOffer]:
    rows = list(session.exec(select(JobOffer).where(JobOffer.job_id == job_id)))

    def sort_key(row: JobOffer) -> tuple[Any, ...]:
        return (row.received_at or row.created_at, row.id or 0)

    return sorted(rows, key=sort_key)


def sync_job_outcome_from_offer(session: Session, job: Job, offer: JobOffer) -> bool:
    """Move the job's outcome to match the offer. Stage only ever advances.

    Recording any offer raises ``outcome_stage`` to ``offer`` and the lifecycle
    to the offer band; accepting or declining stamps the terminal
    ``outcome_result``. Returns True when the job row changed.
    """
    changed = False
    if job.outcome_stage != OutcomeStage.offer:
        job.outcome_stage = OutcomeStage.offer
        changed = True
    result_for_status = {
        OfferStatus.accepted: OutcomeResult.accepted,
        OfferStatus.declined: OutcomeResult.declined,
    }.get(offer.status, OutcomeResult.offer)
    terminal = {OutcomeResult.accepted, OutcomeResult.declined}
    # A live offer never downgrades a terminal accepted/declined result; an
    # explicit accept/decline always wins (the operator can correct a decision).
    downgrade = job.outcome_result in terminal and result_for_status not in terminal
    if job.outcome_result != result_for_status and not downgrade:
        job.outcome_result = result_for_status
        changed = True
    if (
        job.lifecycle_state not in {LifecycleState.rejected, LifecycleState.archived}
        and job.lifecycle_state != LifecycleState.offer
    ):
        job.lifecycle_state = LifecycleState.offer
        changed = True
    if changed:
        if job.applied_at is None:
            job.applied_at = datetime.now(UTC)
        job.outcome_updated_at = datetime.now(UTC)
        job.updated_at = datetime.now(UTC)
        session.add(job)
    return changed


def _offer_context(offer: JobOffer) -> dict[str, Any]:
    return {
        "status": offer.status.value,
        "base_salary": offer.base_salary,
        "currency": offer.currency,
        "bonus": offer.bonus,
        "equity": offer.equity,
        "pension": offer.pension,
        "holiday_days": offer.holiday_days,
        "benefits": offer.benefits,
        "other_terms": offer.other_terms,
        "start_date": offer.start_date.isoformat() if offer.start_date else None,
        "received_at": offer.received_at.isoformat() if offer.received_at else None,
        "response_deadline": offer.deadline_at.isoformat() if offer.deadline_at else None,
        "offer_letter_text": (offer.offer_text or "").strip()[:12000] or None,
        "notes": offer.notes,
    }


def _expectations_context(settings: Settings) -> dict[str, Any]:
    return {
        "target_roles": settings.user_target_roles,
        "location": settings.user_location,
        "hybrid_max_office_days": settings.user_hybrid_max_office_days,
        "compensation_min_gbp": settings.user_comp_min_gbp or None,
        "compensation_target_gbp": settings.user_comp_target_gbp or None,
    }


def _advance_offer_status(
    session: Session,
    offer: JobOffer,
    *,
    to: OfferStatus,
    allowed_from: set[OfferStatus],
    reason: str,
) -> None:
    """Generator-driven, forward-only offer status transition (audit-logged)."""
    if offer.status not in allowed_from:
        return
    previous = offer.status
    offer.status = to
    offer.updated_at = datetime.now(UTC)
    session.add(offer)
    session.commit()
    log_action(
        session,
        actor=ActorType.agent,
        action="advance_offer_status",
        entity_type="offer",
        entity_id=offer.id,
        detail={"from": previous.value, "to": to.value, "reason": reason},
    )


def _latest_evaluation_body(session: Session, job_id: int, *, max_chars: int = 6000) -> str | None:
    from ..materials.files import read_text_content

    row = session.exec(
        select(GeneratedMaterial)
        .where(
            GeneratedMaterial.job_id == job_id,
            GeneratedMaterial.material_type == "offer_evaluation",
        )
        .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
    ).first()
    if row is None:
        return None
    raw = read_text_content(row)
    if not raw:
        return None
    body = strip_llm_envelope(raw)
    return body[:max_chars] if body.strip() else None


def _prior_offers_context(
    session: Session, job_id: int, *, exclude_offer_id: int | None
) -> list[dict[str, Any]]:
    """Earlier offers on this job (oldest first, capped) — the negotiation trail."""
    rows = [row for row in list_offers(session, job_id) if row.id != exclude_offer_id]
    return [_offer_context(row) for row in rows[-3:]]


def _sent_responses_context(
    session: Session, job_id: int, *, limit: int = 2, max_chars: int = 3000
) -> list[dict[str, Any]]:
    """The candidate's own responses (generated or imported counters), newest first."""
    from ..materials.files import read_text_content

    rows = list(
        session.exec(
            select(GeneratedMaterial)
            .where(
                GeneratedMaterial.job_id == job_id,
                GeneratedMaterial.material_type == "offer_response",
            )
            .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        body = strip_llm_envelope(read_text_content(row) or "")
        if not body.strip():
            continue
        out.append(
            {
                "title": row.title,
                "status": row.status,
                "date": (row.effective_date or row.created_at).date().isoformat(),
                "content": body[:max_chars],
            }
        )
        if len(out) >= limit:
            break
    return out


def generate_offer_evaluation(
    session: Session,
    job: Job,
    offer: JobOffer,
    *,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Benchmark the offer against the market and the operator's expectations."""
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="offer_evaluation",
        entity_type="job",
        entity_id=job.id,
        detail={"offer_id": offer.id},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        prior_offers = _prior_offers_context(session, job.id or 0, exclude_offer_id=offer.id)
        sent_responses = _sent_responses_context(session, job.id or 0)
        negotiating = bool(prior_offers or sent_responses)
        sections = evaluation_sections(negotiating=negotiating)
        payload = {
            "required_sections": sections,
            "job": _job_context(job),
            "offer": _offer_context(offer),
            "negotiation_history": {
                "prior_offers": prior_offers or None,
                "your_sent_responses": sent_responses or None,
            }
            if negotiating
            else None,
            "candidate_expectations": _expectations_context(settings),
            "today": datetime.now(UTC).date().isoformat(),
        }
        markdown, citations, web_used = client.generate_document(
            OFFER_EVAL_SYSTEM_PROMPT,
            (
                "Evaluate the job offer described below.\n"
                "Use `##` headings exactly matching required_sections, in order.\n"
                "Benchmark every compensation component against current market data.\n\n"
                f"{json.dumps(payload, indent=2, default=str)}"
            ),
            settings.scoring_model,
            settings.interview_pack_max_tokens,
            operation_name="generate_offer_evaluation",
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("offer evaluation returned an empty document")
        missing = missing_sections(markdown, sections)
        warnings: list[str] = []
        lines = line_count(strip_llm_envelope(markdown))
        if lines > OFFER_EVALUATION_LINE_BUDGET[1]:
            warnings.append(
                f"offer evaluation exceeds line budget ({lines} > {OFFER_EVALUATION_LINE_BUDGET[1]})"
            )
        title = f"Offer evaluation — {job.company}"
        document = wrap_offer_document(
            markdown,
            title=title,
            job=job,
            material_type="offer_evaluation",
            web_search_used=web_used,
            citations=citations,
        )
        material = _write_internal_material(
            session,
            job,
            material_type="offer_evaluation",
            title=title,
            document=document,
            audit_detail={
                "offer_id": offer.id,
                "web_search_used": web_used,
                "citation_count": len(citations),
                "prior_offers": len(prior_offers),
                "sent_responses": len(sent_responses),
                "missing_sections": missing,
                "quality_warnings": warnings,
            },
        )
        # Generating an evaluation implies the operator is weighing the offer.
        _advance_offer_status(
            session,
            offer,
            to=OfferStatus.evaluating,
            allowed_from={OfferStatus.received},
            reason="offer evaluation generated",
        )
        return material


# Onboarding pack (OFF-03) — the journey's final artifact. Section schema
# follows first-90-days practice for senior hires: assessment → alignment →
# execution phases, an explicit stakeholder map, trust-building quick wins,
# and everything the interview process taught, carried into day one.
ONBOARDING_SECTIONS: list[str] = [
    "Mission And Mandate",
    "Company And Strategy Snapshot",
    "Stakeholder Map",
    "What You Learned In The Process",
    "First 30 Days — Learn And Listen",
    "Days 31 To 60 — Align And Design",
    "Days 61 To 90 — Deliver",
    "Quick Wins",
    "Risks And Watchouts",
    "Success Metrics And Check-Ins",
    "Open Questions Before Day One",
]

ONBOARDING_LINE_BUDGET: tuple[int, int] = (250, 500)

ONBOARDING_SYSTEM_PROMPT = """You are a senior executive coach preparing a candidate to excel from day one in a role they have just accepted.
Write a focused, practical onboarding pack in Markdown.

Priority order for facts (highest first):
1. What the process itself produced: interview debriefs, prep packs, transcripts context, recorded rounds and participants, offer terms
2. The job description / summary and the candidate's verified evidence bank (cite claim ids inline)
3. Web search for net-new company strategy, results, and leadership facts only

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
  Do NOT include YAML frontmatter or a top-level `#` title.
- Mission And Mandate: what they hired this person to do, in their own words where the process
  revealed them (JD, interviewer statements from debriefs); how success will be judged.
- Company And Strategy Snapshot: current strategy, priorities, stack, and key numbers —
  refresh with web search and mark inferred items.
- Stakeholder Map: every named person from the interview process with role, what they care
  about (from debriefs), and a first-meeting goal; flag likely supporters and sceptics only
  when the process gave evidence for it.
- What You Learned In The Process: organisational intelligence from debriefs, commitments or
  positions the candidate voiced in interviews (they will be remembered), and themes every
  round returned to.
- The 30/60/90 sections: learn-and-listen first (one-on-ones, current-state review, expectation
  alignment with the manager), then align-and-design (priorities, early initiatives), then
  deliver (visible execution, present early results). Make items concrete to THIS role and
  company, not generic onboarding advice.
- Quick Wins: 3-5 candidates filtered for: meaningful impact, deliverable with confidence,
  models the behaviour the candidate wants to be known for, and visibly wouldn't have happened
  without them.
- Risks And Watchouts: inherited risks, political dynamics evidenced in the process, and the
  candidate's own gaps (from debriefs) with a mitigation each.
- Success Metrics And Check-Ins: what to measure, when to review with the manager, and the
  day-90 story the candidate should be able to tell.
- Open Questions Before Day One: what to clarify with the hiring manager or HR before starting.
- Target 250-450 lines. Be concise, specific, and grounded; never invent people, commitments,
  or company facts.
- Avoid em dashes; no wrapping code fence around the whole document."""


def _interview_history(session: Session, job_id: int) -> list[dict[str, Any]]:
    from .service import list_interviews

    rows = list_interviews(session, job_id)
    return [
        {
            "round_type": row.round_type.value,
            "title": row.title,
            "occurred_at": (row.occurred_at or row.scheduled_at).isoformat()
            if (row.occurred_at or row.scheduled_at)
            else None,
            "status": row.status.value,
            "participants": row.participants,
            "notes": row.notes,
        }
        for row in rows
    ]


def _accepted_or_latest_offer(session: Session, job_id: int) -> JobOffer | None:
    rows = list_offers(session, job_id)
    for row in reversed(rows):
        if row.status == OfferStatus.accepted:
            return row
    return rows[-1] if rows else None


def generate_onboarding_pack(
    session: Session,
    job: Job,
    *,
    offer: JobOffer | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Generate the new-role start pack (OFF-03) once an offer is accepted.

    Carries everything the process gathered — debriefs, prep packs, stakeholder
    names, offer terms, verified evidence — into a 30/60/90 plan for day one.
    """
    settings = settings or get_settings()
    offer = offer or _accepted_or_latest_offer(session, job.id or 0)
    with pipeline_run(
        session,
        pipeline_type="onboarding_pack",
        entity_type="job",
        entity_id=job.id,
        detail={"offer_id": offer.id if offer else None},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.cv_alignment import select_relevant_evidence
        from ..materials.generator import (
            _evidence_payload,
            _job_context,
            _load_evidence_with_source,
        )
        from .material_policy import load_prior_debriefs, load_prior_prep_materials
        from .service import load_cross_job_learnings

        pool, _source = _load_evidence_with_source(session, limit=settings.evidence_candidate_pool)
        evidence = select_relevant_evidence(pool, job, limit=settings.evidence_prompt_limit)
        payload = {
            "required_sections": ONBOARDING_SECTIONS,
            "job": _job_context(job),
            "accepted_offer": _offer_context(offer) if offer else None,
            "interview_rounds": _interview_history(session, job.id or 0) or None,
            "round_debriefs": load_prior_debriefs(session, job.id or 0, limit=6) or None,
            "prep_packs": load_prior_prep_materials(session, job.id or 0, limit=6) or None,
            "candidate_evidence_bank": _evidence_payload(evidence),
            "learnings_from_past_processes": load_cross_job_learnings(
                session, exclude_job_id=job.id
            )
            or None,
            "candidate_profile": _expectations_context(settings),
            "today": datetime.now(UTC).date().isoformat(),
        }
        markdown, citations, web_used = client.generate_document(
            ONBOARDING_SYSTEM_PROMPT,
            (
                "Prepare the onboarding pack for the accepted role described below.\n"
                "Use `##` headings exactly matching required_sections, in order.\n"
                "Ground every stakeholder and process fact in the provided materials.\n\n"
                f"{json.dumps(payload, indent=2, default=str)}"
            ),
            settings.scoring_model,
            settings.interview_pack_max_tokens,
            operation_name="generate_onboarding_pack",
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("onboarding pack generation returned an empty document")
        missing = missing_sections(markdown, ONBOARDING_SECTIONS)
        warnings: list[str] = []
        lines = line_count(strip_llm_envelope(markdown))
        if lines > ONBOARDING_LINE_BUDGET[1]:
            warnings.append(
                f"onboarding pack exceeds line budget ({lines} > {ONBOARDING_LINE_BUDGET[1]})"
            )
        title = f"Onboarding pack — {job.company}"
        document = wrap_offer_document(
            markdown,
            title=title,
            job=job,
            material_type="onboarding_pack",
            web_search_used=web_used,
            citations=citations,
        )
        from .packs import _cited_claim_ids

        cited_ids = _cited_claim_ids(markdown, {item.id for item in evidence})
        return _write_internal_material(
            session,
            job,
            material_type="onboarding_pack",
            title=title,
            document=document,
            audit_detail={
                "offer_id": offer.id if offer else None,
                "web_search_used": web_used,
                "citation_count": len(citations),
                "evidence_cited": cited_ids,
                "missing_sections": missing,
                "quality_warnings": warnings,
                "rounds": len(payload["interview_rounds"] or []),
                "debriefs": len(payload["round_debriefs"] or []),
            },
            evidence_ids=cited_ids,
        )


_RESPONSE_TITLES = {
    "accept": "Acceptance draft",
    "counter": "Counter-offer draft",
    "clarify": "Clarification draft",
}


def generate_offer_response(
    session: Session,
    job: Job,
    offer: JobOffer,
    *,
    response_type: str,
    instructions: str | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Draft an acceptance / counter-offer / clarification email (never sent)."""
    if response_type not in OFFER_RESPONSE_TYPES:
        raise ValueError(
            f"unsupported response type: {response_type!r} "
            f"(expected one of {OFFER_RESPONSE_TYPES})"
        )
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="offer_response",
        entity_type="job",
        entity_id=job.id,
        detail={"offer_id": offer.id, "response_type": response_type},
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.generator import _job_context

        payload = {
            "response_type": response_type,
            "candidate_name": settings.user_full_name,
            "job": _job_context(job),
            "offer": _offer_context(offer),
            "candidate_expectations": _expectations_context(settings),
            # Only counter drafts ground their asks in the benchmark; accept and
            # clarify drafts don't need ~6k chars of market data in the prompt.
            "market_evaluation": _latest_evaluation_body(session, job.id or 0)
            if response_type == "counter"
            else None,
            "instructions": (instructions or "").strip() or None,
        }
        markdown, _citations, _web = client.generate_document(
            _OFFER_RESPONSE_SYSTEM,
            f"Draft the {response_type} email for this offer.\n\n"
            f"{json.dumps(payload, indent=2, default=str)}",
            settings.scoring_model,
            2000,
            operation_name="generate_offer_response",
            allow_web=False,
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("offer response draft returned an empty document")
        title = f"{_RESPONSE_TITLES[response_type]} — {job.company}"
        material = _write_internal_material(
            session,
            job,
            material_type="offer_response",
            title=title,
            document=NEVER_SENT_BANNER + markdown,
            audit_detail={
                "offer_id": offer.id,
                "response_type": response_type,
                "has_market_evaluation": payload["market_evaluation"] is not None,
            },
        )
        # Drafting a counter implies a negotiation is underway.
        if response_type == "counter":
            _advance_offer_status(
                session,
                offer,
                to=OfferStatus.negotiating,
                allowed_from={OfferStatus.received, OfferStatus.evaluating},
                reason="counter-offer draft generated",
            )
        return material
