"""Interview timeline + internal-artifact filing (INT-01) and the
promote-a-learning path into the evidence review queue (INT-04).

Interviews are dated, backdatable rounds on a job's post-application timeline.
Artifacts (prep packs, debriefs, email drafts) reuse ``GeneratedMaterial`` with
``audience=internal`` so versioning, retention, files, and audit come for free.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from ..audit import log_action
from ..models import (
    ActorType,
    ClaimVerificationState,
    EvidenceClaim,
    GeneratedMaterial,
    Interview,
    InterviewRoundType,
    Job,
    MaterialAudience,
    OutcomeStage,
    SourceDocument,
    SourceDocumentStatus,
    SourceDocumentType,
)

# Internal (operator-facing) material types the interview workflow produces or
# imports. These are never exported as application documents and skip the
# employer-document grounding gates (they carry web citations instead).
INTERNAL_MATERIAL_TYPES = frozenset(
    {
        "company_briefing",
        "interviewer_pack",
        "tech_prep_pack",
        "final_round_pack",
        "culture_comparison",
        "session_prep",
        "debrief",
        "email_draft",
        "interviewer_sim_prompt",
        # Offer stage (OFF-01/OFF-03/OFF-05).
        "offer_evaluation",
        "offer_response",
        "onboarding_pack",
        "departure_pack",
        # Journey close-out (INT-07/INT-09).
        "rejection_reflection",
        "journey_summary",
    }
)

# Coarse funnel stage each round type implies (for outcome/lifecycle sync).
ROUND_TO_STAGE: dict[InterviewRoundType, OutcomeStage] = {
    InterviewRoundType.recruiter_screen: OutcomeStage.recruiter_screen,
    InterviewRoundType.hiring_manager: OutcomeStage.interview,
    InterviewRoundType.leadership_panel: OutcomeStage.interview,
    InterviewRoundType.technical: OutcomeStage.interview,
    InterviewRoundType.team: OutcomeStage.interview,
    InterviewRoundType.final_round: OutcomeStage.final_round,
    InterviewRoundType.other: OutcomeStage.interview,
}

_STAGE_ORDER: dict[OutcomeStage, int] = {
    OutcomeStage.applied: 0,
    OutcomeStage.acknowledged: 1,
    OutcomeStage.recruiter_screen: 2,
    OutcomeStage.interview: 3,
    OutcomeStage.final_round: 4,
    OutcomeStage.offer: 5,
}


def list_interviews(session: Session, job_id: int) -> list[Interview]:
    rows = list(session.exec(select(Interview).where(Interview.job_id == job_id)))

    def sort_key(row: Interview) -> tuple[Any, ...]:
        when = row.occurred_at or row.scheduled_at or row.created_at
        return (when, row.id or 0)

    return sorted(rows, key=sort_key)


def sync_job_outcome_from_round(session: Session, job: Job, round_type: InterviewRoundType) -> bool:
    """Raise the job's coarse outcome stage to match a recorded round.

    Only ever moves the stage forward; never touches ``applied_at`` (a
    backdated timeline sets that explicitly via the outcome endpoint).
    Skips terminal jobs (offer/rejected/archived) so historical replay does
    not rewrite a finished outcome. Returns True when the job row changed.
    """
    from ..models import LifecycleState, OutcomeResult

    if job.lifecycle_state in {
        LifecycleState.offer,
        LifecycleState.rejected,
        LifecycleState.archived,
    }:
        return False
    if job.outcome_result in {OutcomeResult.offer, OutcomeResult.rejected}:
        return False
    stage = ROUND_TO_STAGE[round_type]
    current = job.outcome_stage
    if current is not None and _STAGE_ORDER[current] >= _STAGE_ORDER[stage]:
        return False
    job.outcome_stage = stage
    # Mirror jobs._sync_lifecycle_from_outcome for the interview band.
    if job.lifecycle_state not in {
        LifecycleState.offer,
        LifecycleState.rejected,
        LifecycleState.archived,
    }:
        job.lifecycle_state = LifecycleState.interviewing
    job.outcome_updated_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    session.add(job)
    return True


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "artifact"


LEARNING_CATEGORY = "interview_learning"
PROCESS_SKILL_CATEGORY = "process_skill"
LEARNING_CATEGORIES = frozenset({LEARNING_CATEGORY, PROCESS_SKILL_CATEGORY})


def _learnings_document(session: Session, job: Job) -> SourceDocument:
    """Get or create the per-job source document that holds promoted learnings.

    Claims need a source document; interview learnings get one synthetic,
    append-only markdown file per job under the knowledge originals store.
    """
    marker = f"interview-learnings-job-{job.id}"
    existing = session.exec(
        select(SourceDocument).where(SourceDocument.content_hash == marker)
    ).first()
    if existing is not None:
        return existing
    from ..knowledge.service import knowledge_paths

    paths = knowledge_paths()
    path = paths.originals / f"{marker}.md"
    if not path.exists():
        path.write_text(f"# Interview learnings — {job.company}\n", encoding="utf-8")
    document = SourceDocument(
        filename=path.name,
        title=f"Interview learnings — {job.company}",
        original_path=str(path),
        content_hash=marker,
        source_type=SourceDocumentType.note,
        status=SourceDocumentStatus.extracted,
        summary="Learnings promoted from interview debriefs; each is reviewed in Approve facts.",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def promote_learning(
    session: Session,
    job: Job,
    *,
    claim_text: str,
    interview: Interview | None = None,
    category: str = LEARNING_CATEGORY,
) -> tuple[EvidenceClaim, bool]:
    """Turn a debrief/journey insight into a *draft* evidence claim (INT-04/INT-10).

    Never auto-verified: interview-sourced statements enter the employer-facing
    evidence bank only through the Approve facts queue. Returns
    ``(claim, created)``; re-promoting the same text is idempotent.

    Categories:
    - ``interview_learning`` — process / meta lessons
    - ``process_skill`` — substantive skills practiced during the journey
    """
    text = claim_text.strip()
    if not text:
        raise ValueError("learning text is empty")
    cat = (category or LEARNING_CATEGORY).strip()
    if cat not in LEARNING_CATEGORIES:
        raise ValueError(
            f"unsupported learning category: {cat!r} (expected one of {sorted(LEARNING_CATEGORIES)})"
        )
    claim_id = "claim-" + hashlib.sha1(f"{cat}:{job.id}:{text}".encode()).hexdigest()[:16]
    existing = session.get(EvidenceClaim, claim_id)
    if existing is not None:
        return existing, False
    document = _learnings_document(session, job)
    from pathlib import Path

    original = Path(document.original_path)
    if original.exists():
        stamp = datetime.now(UTC).date().isoformat()
        with original.open("a", encoding="utf-8") as handle:
            handle.write(f"\n- ({stamp}) [{cat}] {text}\n")
    claim = EvidenceClaim(
        id=claim_id,
        source_document_id=document.id or 0,
        claim_text=text,
        category=cat,
        confidence=0.5,
        verification_state=ClaimVerificationState.draft,
        source_span=text,
        tags=[cat, job.company, f"job-{job.id}"],
    )
    session.add(claim)
    session.commit()
    session.refresh(claim)
    log_action(
        session,
        actor=ActorType.human,
        action="promote_interview_learning",
        entity_type="evidence_claim",
        entity_id=claim.id,
        detail={
            "job_id": job.id,
            "interview_id": interview.id if interview else None,
            "category": cat,
            "claim_text": text[:200],
        },
    )
    return claim, True


def list_closeout_learning_candidates(
    session: Session,
    job: Job,
    *,
    max_items: int = 12,
) -> list[tuple[str, str, str]]:
    """Portable close-out bullets across all rejection / journey materials.

    Returns ``(category, text, source_title)``. Skills first. Reads every
    close-out doc so a custom imported essay cannot hide the generated
    Skills / Reusable Learnings sections.
    """
    from ..materials.files import read_text_content
    from .classify import extract_closeout_learnings

    rows = list(
        session.exec(
            select(GeneratedMaterial).where(
                GeneratedMaterial.job_id == job.id,
                GeneratedMaterial.material_type.in_(
                    ["rejection_reflection", "journey_summary"]
                ),
            )
        )
    )
    skills: list[tuple[str, str, str]] = []
    learnings: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda m: (0 if m.status == "imported" else 1, -(m.id or 0))):
        body = read_text_content(row) or ""
        source = row.title or row.material_type
        for category, text in extract_closeout_learnings(body, max_items=max_items):
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            item = (category, text, source)
            if category == "process_skill":
                skills.append(item)
            else:
                learnings.append(item)
    return (skills + learnings)[:max_items]


def promote_closeout_learnings(
    session: Session,
    job: Job,
    *,
    claim_texts: list[str],
    max_items: int = 12,
) -> tuple[list[EvidenceClaim], int, int]:
    """Promote operator-selected close-out bullets as draft claims (INT-07/10).

    Only texts that appear in the extracted candidate set are accepted.
    Drafts only — same Approve-facts gate as ``promote_learning``.
    """
    wanted_order: list[str] = []
    seen_wanted: set[str] = set()
    for raw in claim_texts:
        key = raw.strip().casefold()
        if not key or key in seen_wanted:
            continue
        seen_wanted.add(key)
        wanted_order.append(key)
    if not wanted_order:
        raise ValueError("select at least one close-out learning")
    candidates = list_closeout_learning_candidates(session, job, max_items=max_items)
    if not candidates:
        raise ValueError("no portable close-out learnings (skills or playbook bullets) to review")
    by_key = {text.casefold(): (category, text) for category, text, _source in candidates}
    items = [by_key[key] for key in wanted_order if key in by_key]
    if not items:
        raise ValueError("none of the selected lines are portable close-out learnings")

    claims: list[EvidenceClaim] = []
    promoted = 0
    skipped = 0
    for category, text in items:
        claim, created = promote_learning(
            session, job, claim_text=text, category=category
        )
        claims.append(claim)
        if created:
            promoted += 1
        else:
            skipped += 1
    return claims, promoted, skipped


def load_cross_job_learnings(session: Session, *, exclude_job_id: int | None = None, limit: int = 10) -> list[str]:
    """Verified interview learnings + process skills from past processes (INT-04/INT-10)."""
    stmt = (
        select(EvidenceClaim)
        .where(
            EvidenceClaim.category.in_(sorted(LEARNING_CATEGORIES)),
            EvidenceClaim.verification_state == ClaimVerificationState.verified,
        )
        .order_by(EvidenceClaim.updated_at.desc())  # type: ignore[union-attr]
        .limit(limit * 3)
    )
    learnings: list[str] = []
    exclude_marker = f"interview-learnings-job-{exclude_job_id}" if exclude_job_id else None
    for claim in session.exec(stmt):
        if exclude_marker is not None:
            document = session.get(SourceDocument, claim.source_document_id)
            if document is not None and document.content_hash == exclude_marker:
                continue
        prefix = "[skill] " if claim.category == PROCESS_SKILL_CATEGORY else ""
        learnings.append(f"{prefix}{claim.claim_text}")
        if len(learnings) >= limit:
            break
    return learnings


def import_internal_material(
    session: Session,
    job: Job,
    *,
    material_type: str,
    title: str,
    content: str,
    interview_id: int | None = None,
    effective_date: datetime | None = None,
) -> GeneratedMaterial:
    """File an existing document (e.g. a Claude-chat pack) as an internal artifact.

    Writes the markdown under the standard materials tree and records a
    ``GeneratedMaterial`` row with ``status='imported'`` and no evidence ids —
    imported packs are historical records, not generated claims.
    """
    if material_type not in INTERNAL_MATERIAL_TYPES:
        raise ValueError(
            f"unsupported internal material type: {material_type!r} "
            f"(expected one of {sorted(INTERNAL_MATERIAL_TYPES)})"
        )
    from ..materials.generator import MATERIALS_ROOT, _next_version
    from .classify import apply_import_type_suggestion

    applied_type, suggested_type = apply_import_type_suggestion(
        material_type, title, content
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    out_dir = MATERIALS_ROOT / str(job.id) / f"{stamp}-{_slug(applied_type)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{_slug(title)}.md"
    md_path.write_text(content, encoding="utf-8")
    version = _next_version(session, job.id or 0, applied_type)
    material = GeneratedMaterial(
        job_id=job.id or 0,
        interview_id=interview_id,
        material_type=applied_type,
        audience=MaterialAudience.internal,
        effective_date=effective_date,
        title=title,
        markdown_path=str(md_path),
        evidence_ids=[],
        version=version,
        status="imported",
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.human,
        action="import_internal_material",
        entity_type="job",
        entity_id=job.id,
        detail={
            "material_id": material.id,
            "material_type": applied_type,
            "submitted_type": material_type,
            "suggested_type": suggested_type,
            "interview_id": interview_id,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "version": version,
        },
    )
    return material


def update_material_meta(
    session: Session,
    job: Job,
    material: GeneratedMaterial,
    *,
    interview_id: int | None = None,
    clear_interview: bool = False,
    title: str | None = None,
    material_type: str | None = None,
) -> GeneratedMaterial:
    """Relink / retitle / reclassify an internal material (INT-08)."""
    if material.job_id != job.id:
        raise ValueError("material does not belong to job")
    if material_type is not None:
        if material_type not in INTERNAL_MATERIAL_TYPES:
            raise ValueError(
                f"unsupported internal material type: {material_type!r} "
                f"(expected one of {sorted(INTERNAL_MATERIAL_TYPES)})"
            )
        material.material_type = material_type
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("title cannot be empty")
        material.title = cleaned
    if clear_interview:
        material.interview_id = None
    elif interview_id is not None:
        interview = session.get(Interview, interview_id)
        if interview is None or interview.job_id != job.id:
            raise ValueError("interview not found on this job")
        material.interview_id = interview_id
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.human,
        action="update_material_meta",
        entity_type="job",
        entity_id=job.id,
        detail={
            "material_id": material.id,
            "interview_id": material.interview_id,
            "material_type": material.material_type,
            "title": material.title,
        },
    )
    return material


def delete_material(session: Session, job: Job, material: GeneratedMaterial) -> None:
    """Delete one material row and best-effort remove its on-disk files (INT-08)."""
    if material.job_id != job.id:
        raise ValueError("material does not belong to job")
    material_id = material.id
    from ..materials.files import material_storage_dir

    storage = material_storage_dir(material)
    session.delete(material)
    session.commit()
    if storage is not None and storage.exists():
        with suppress(OSError):
            shutil.rmtree(storage)
    log_action(
        session,
        actor=ActorType.human,
        action="delete_material",
        entity_type="job",
        entity_id=job.id,
        detail={"material_id": material_id},
    )


def list_adaptable_materials(
    session: Session,
    *,
    exclude_job_id: int,
    material_type: str | None = None,
    limit: int = 40,
) -> list[tuple[GeneratedMaterial, Job]]:
    """Recent internal materials from other jobs for cross-job adapt (INT-11)."""
    stmt = (
        select(GeneratedMaterial, Job)
        .join(Job, Job.id == GeneratedMaterial.job_id)
        .where(
            GeneratedMaterial.job_id != exclude_job_id,
            GeneratedMaterial.audience == MaterialAudience.internal,
            GeneratedMaterial.material_type.in_(sorted(INTERNAL_MATERIAL_TYPES)),
        )
        .order_by(GeneratedMaterial.created_at.desc())
        .limit(limit)
    )
    if material_type:
        stmt = stmt.where(GeneratedMaterial.material_type == material_type)
    return list(session.exec(stmt).all())
