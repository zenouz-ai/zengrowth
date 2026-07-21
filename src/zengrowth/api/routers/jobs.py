"""Jobs domain: manual entry, extraction, scoring, summaries, state, materials."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlmodel import Session, select

from ...audit import log_action
from ...config import get_settings
from ...db import get_session
from ...ingestion.dedup import dedup_hash
from ...ingestion.job_description_extractor import extract_job_fields
from ...ingestion.job_summarizer import summarize_job
from ...jobs.delete import delete_job, delete_jobs_by_state
from ...materials.files import file_available, read_text_content, resolve_material_file
from ...materials.generator import (
    effective_cv_draft_json,
    generate_answer,
    generate_cover_letter,
    generate_cv,
)
from ...materials.names import material_export_filename
from ...materials.revise import (
    MaterialDraftPatch,
    MaterialInstructionRequest,
    MaterialReviseRequest,
    fit_material_to_two_pages,
    mark_material_final,
    preview_mode_for,
    revise_material,
    revise_material_with_instruction,
    unmark_material_final,
)
from ...models import (
    ActorType,
    GeneratedMaterial,
    Job,
    JobSource,
    LifecycleState,
    OutcomeResult,
    OutcomeStage,
)
from ...scoring.scorer import score_job
from ..schemas import (
    GeneratedMaterialDetailOut,
    GeneratedMaterialOut,
    JobCreate,
    JobExtractRequest,
    JobExtractResponse,
    JobOut,
    JobPatch,
    JobPurgeRequest,
    JobPurgeResponse,
    MaterialAnswerRequest,
    MaterialReviseIn,
    OutcomeFunnel,
    OutcomeUpdate,
    StateChange,
    material_tailoring_from_draft,
)

router = APIRouter(tags=["jobs"])

# Ordered stages, so "reached at least interview" is a simple comparison.
_STAGE_ORDER: dict[OutcomeStage, int] = {
    OutcomeStage.applied: 0,
    OutcomeStage.acknowledged: 1,
    OutcomeStage.recruiter_screen: 2,
    OutcomeStage.interview: 3,
    OutcomeStage.final_round: 4,
    OutcomeStage.offer: 5,
}
_OFFER_RESULTS = {OutcomeResult.offer, OutcomeResult.accepted, OutcomeResult.declined}
_PRE_APPLIED_STATES = {
    LifecycleState.discovered,
    LifecycleState.shortlisted,
    LifecycleState.prepared,
    LifecycleState.awaiting_approval,
    LifecycleState.approved,
}


def _reached(job: Job, stage: OutcomeStage) -> bool:
    return job.outcome_stage is not None and _STAGE_ORDER[job.outcome_stage] >= _STAGE_ORDER[stage]


def _has_responded(job: Job) -> bool:
    return job.first_response_at is not None or _reached(job, OutcomeStage.acknowledged)


def _sync_lifecycle_from_outcome(job: Job) -> None:
    """Keep the coarse ``lifecycle_state`` consistent with detailed outcome fields."""
    if job.outcome_result == OutcomeResult.rejected:
        job.lifecycle_state = LifecycleState.rejected
    elif job.outcome_result in _OFFER_RESULTS or job.outcome_stage == OutcomeStage.offer:
        job.lifecycle_state = LifecycleState.offer
    elif _reached(job, OutcomeStage.recruiter_screen):
        job.lifecycle_state = LifecycleState.interviewing
    elif job.applied_at is not None and job.lifecycle_state in _PRE_APPLIED_STATES:
        job.lifecycle_state = LifecycleState.applied


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    state: LifecycleState | None = None,
    curated: bool = False,
    limit: int = 200,
    session: Session = Depends(get_session),
) -> list[Job]:
    stmt = select(Job)
    if curated:
        # SQL pre-filter matches is_curated_pipeline_job; manual jobs bypass the fit floor.
        settings = get_settings()
        min_fit = settings.pipeline_min_fit_score
        stmt = stmt.where(
            Job.lifecycle_state != LifecycleState.archived,
            Job.summary_updated_at.is_not(None),  # type: ignore[union-attr]
            Job.job_summary.is_not(None),  # type: ignore[union-attr]
            Job.fit_score.is_not(None),  # type: ignore[union-attr]
            Job.expected_value.is_not(None),  # type: ignore[union-attr]
            or_(Job.source == JobSource.manual, Job.fit_score >= min_fit),  # type: ignore[arg-type]
        )
    if state is not None:
        stmt = stmt.where(Job.lifecycle_state == state)
    stmt = stmt.order_by(Job.expected_value.desc().nullslast()).limit(limit)  # type: ignore[union-attr]
    return list(session.exec(stmt))


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_job(payload: JobCreate, session: Session = Depends(get_session)) -> Job:
    h = dedup_hash(payload.company, payload.title, payload.posting_date)
    existing = session.exec(select(Job).where(Job.dedup_hash == h)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "duplicate", "job_id": existing.id})
    job = Job(**payload.model_dump(), dedup_hash=h)
    session.add(job)
    session.commit()
    session.refresh(job)
    log_action(
        session,
        actor=ActorType.human,
        action="create_job",
        entity_type="job",
        entity_id=job.id,
        detail={"source": job.source.value, "company": job.company, "title": job.title},
    )
    return job


@router.post("/jobs/extract", response_model=JobExtractResponse)
def extract_job(payload: JobExtractRequest) -> JobExtractResponse:
    try:
        extracted = extract_job_fields(
            raw_text=payload.raw_text,
            application_url=payload.application_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return JobExtractResponse.model_validate(extracted.model_dump())


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.patch("/jobs/{job_id}", response_model=JobOut)
def patch_job(
    job_id: int,
    payload: JobPatch,
    session: Session = Depends(get_session),
) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if payload.application_url is not None:
        job.application_url = payload.application_url or None
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    log_action(
        session,
        actor=ActorType.human,
        action="patch_job",
        entity_type="job",
        entity_id=job.id,
        detail={"application_url": job.application_url},
    )
    return job


@router.post("/jobs/purge", response_model=JobPurgeResponse)
def purge_jobs(payload: JobPurgeRequest, session: Session = Depends(get_session)) -> JobPurgeResponse:
    """Permanently delete all jobs in the given lifecycle state."""
    deleted = delete_jobs_by_state(session, payload.lifecycle_state)
    return JobPurgeResponse(deleted=deleted, lifecycle_state=payload.lifecycle_state)


@router.delete("/jobs/{job_id}", status_code=204, response_model=None)
def remove_job(job_id: int, session: Session = Depends(get_session)) -> None:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    detail = {"company": job.company, "title": job.title}
    delete_job(session, job)
    session.commit()
    log_action(
        session,
        actor=ActorType.human,
        action="delete_job",
        entity_type="job",
        entity_id=job_id,
        detail=detail,
    )


@router.post("/jobs/{job_id}/summarize", response_model=JobOut)
def summarize(job_id: int, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return summarize_job(session, job)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/score", response_model=JobOut)
def score(job_id: int, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return score_job(session, job)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"scoring response invalid: {exc}") from exc


@router.post("/jobs/{job_id}/state", response_model=JobOut)
def change_state(
    job_id: int,
    payload: StateChange,
    session: Session = Depends(get_session),
) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    old = job.lifecycle_state
    job.lifecycle_state = payload.state
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    log_action(
        session,
        actor=ActorType.human,
        action="change_state",
        entity_type="job",
        entity_id=job.id,
        detail={"from": old.value, "to": payload.state.value, "note": payload.note},
    )
    return job


def _round_analytics(session: Session) -> tuple[int, float | None]:
    """Rounds recorded + mean gap in days between consecutive dated rounds (INT-04)."""
    from collections import defaultdict

    from ...models import Interview

    rows = list(session.exec(select(Interview)))
    dated: dict[int, list[datetime]] = defaultdict(list)
    for row in rows:
        when = row.occurred_at or row.scheduled_at
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            dated[row.job_id].append(when)
    gaps: list[float] = []
    for dates in dated.values():
        ordered = sorted(dates)
        gaps.extend(
            (later - earlier).total_seconds() / 86400
            for earlier, later in zip(ordered, ordered[1:], strict=False)
        )
    avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else None
    return len(rows), avg_gap


@router.get("/jobs/outcomes/funnel", response_model=OutcomeFunnel)
def outcome_funnel(session: Session = Depends(get_session)) -> OutcomeFunnel:
    jobs = list(session.exec(select(Job).where(Job.applied_at.is_not(None))))  # type: ignore[union-attr]
    total = len(jobs)
    responded = sum(1 for j in jobs if _has_responded(j))
    interviewed = sum(1 for j in jobs if _reached(j, OutcomeStage.interview))
    offers = sum(
        1 for j in jobs if j.outcome_result in _OFFER_RESULTS or j.outcome_stage == OutcomeStage.offer
    )
    rejected = sum(1 for j in jobs if j.outcome_result == OutcomeResult.rejected)

    def rate(n: int) -> float | None:
        return round(n / total, 3) if total else None

    rounds_recorded, avg_gap_days = _round_analytics(session)
    return OutcomeFunnel(
        total_applied=total,
        responded=responded,
        interviewed=interviewed,
        offers=offers,
        rejected=rejected,
        response_rate=rate(responded),
        interview_rate=rate(interviewed),
        offer_rate=rate(offers),
        rounds_recorded=rounds_recorded,
        avg_days_between_rounds=avg_gap_days,
    )


@router.post("/jobs/{job_id}/outcome", response_model=JobOut)
def record_outcome(
    job_id: int,
    payload: OutcomeUpdate,
    session: Session = Depends(get_session),
) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    data = payload.model_dump(exclude_unset=True)
    for field in ("applied_at", "first_response_at", "outcome_stage", "outcome_result", "rejection_stage"):
        if field in data:
            setattr(job, field, data[field])
    if "notes" in data:
        job.outcome_notes = data["notes"]
    # Recording any stage implies an application exists; backfill applied_at.
    if job.outcome_stage is not None and job.applied_at is None:
        job.applied_at = datetime.now(UTC)
    if payload.sync_lifecycle:
        _sync_lifecycle_from_outcome(job)
    job.outcome_updated_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    detail = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in data.items()}
    detail["lifecycle_state"] = job.lifecycle_state.value
    log_action(
        session,
        actor=ActorType.human,
        action="record_outcome",
        entity_type="job",
        entity_id=job.id,
        detail=detail,
    )
    return job


@router.get("/jobs/{job_id}/materials", response_model=list[GeneratedMaterialOut])
def list_materials(job_id: int, session: Session = Depends(get_session)) -> list[GeneratedMaterialOut]:
    if not session.get(Job, job_id):
        raise HTTPException(status_code=404, detail="job not found")
    stmt = (
        select(GeneratedMaterial)
        .where(GeneratedMaterial.job_id == job_id)
        .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
    )
    return [_to_material_out(material) for material in session.exec(stmt)]


def _get_job_material(session: Session, job_id: int, material_id: int) -> tuple[Job, GeneratedMaterial]:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    material = session.get(GeneratedMaterial, material_id)
    if not material or material.job_id != job_id:
        raise HTTPException(status_code=404, detail="material not found")
    return job, material


def _to_material_out(material: GeneratedMaterial) -> GeneratedMaterialOut:
    return GeneratedMaterialOut(
        id=material.id or 0,
        job_id=material.job_id,
        interview_id=material.interview_id,
        material_type=material.material_type,
        audience=material.audience,
        effective_date=material.effective_date,
        title=material.title,
        question=material.question,
        word_limit=material.word_limit,
        tex_path=material.tex_path,
        pdf_path=material.pdf_path,
        markdown_path=material.markdown_path,
        evidence_ids=material.evidence_ids,
        version=material.version,
        is_final=material.is_final,
        supersedes_id=material.supersedes_id,
        page_count=material.page_count,
        page_fill=material.page_fill,
        status=material.status,
        created_at=material.created_at,
        tailoring=material_tailoring_from_draft(material.draft_json, material_type=material.material_type),
    )


def _material_detail(material: GeneratedMaterial) -> GeneratedMaterialDetailOut:
    mode = preview_mode_for(material)
    fallback = None if material.draft_json else read_text_content(material)
    tex_content = (
        read_text_content(material)
        if material.material_type in {"cv", "cover_letter"}
        else None
    )
    draft_json = material.draft_json
    if material.material_type == "cv" and tex_content:
        effective = effective_cv_draft_json(draft_json, tex_content=tex_content)
        draft_json = effective
        if isinstance(material.draft_json, dict):
            merged = dict(draft_json or {})
            for key in ("template_baseline", "tailoring", "quality_report"):
                if key in material.draft_json:
                    merged[key] = material.draft_json[key]
            draft_json = merged
    return GeneratedMaterialDetailOut(
        id=material.id or 0,
        job_id=material.job_id,
        interview_id=material.interview_id,
        material_type=material.material_type,
        audience=material.audience,
        effective_date=material.effective_date,
        title=material.title,
        question=material.question,
        word_limit=material.word_limit,
        tex_path=material.tex_path,
        pdf_path=material.pdf_path,
        markdown_path=material.markdown_path,
        evidence_ids=material.evidence_ids,
        version=material.version,
        is_final=material.is_final,
        supersedes_id=material.supersedes_id,
        page_count=material.page_count,
        page_fill=material.page_fill,
        status=material.status,
        created_at=material.created_at,
        tailoring=material_tailoring_from_draft(draft_json, material_type=material.material_type),
        draft_json=draft_json,
        preview_mode=mode,
        pdf_available=file_available(material, "pdf"),
        tex_available=file_available(material, "tex"),
        markdown_available=file_available(material, "md"),
        fallback_content=fallback,
        tex_content=tex_content,
    )


@router.get("/jobs/{job_id}/materials/{material_id}", response_model=GeneratedMaterialDetailOut)
def get_material(job_id: int, material_id: int, session: Session = Depends(get_session)) -> GeneratedMaterialDetailOut:
    _, material = _get_job_material(session, job_id, material_id)
    return _material_detail(material)


@router.get("/jobs/{job_id}/materials/{material_id}/file/{kind}")
def download_material_file(
    job_id: int,
    material_id: int,
    kind: str,
    disposition: str = Query(default="attachment"),
    session: Session = Depends(get_session),
) -> FileResponse:
    job, material = _get_job_material(session, job_id, material_id)
    if kind not in {"pdf", "tex", "md"}:
        raise HTTPException(status_code=400, detail="unsupported file kind")
    try:
        path = resolve_material_file(material, kind)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media = {
        "pdf": "application/pdf",
        "tex": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }[kind]
    filename = material_export_filename(
        material,
        company=job.company,
        candidate=get_settings().materials_export_name,
        kind=kind,
    )
    headers = {}
    if disposition == "inline":
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    else:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(path, media_type=media, filename=filename, headers=headers)


@router.patch("/jobs/{job_id}/materials/{material_id}", response_model=GeneratedMaterialDetailOut)
def revise_material_endpoint(
    job_id: int,
    material_id: int,
    payload: MaterialReviseIn,
    session: Session = Depends(get_session),
) -> GeneratedMaterialDetailOut:
    job, material = _get_job_material(session, job_id, material_id)
    draft_patch = MaterialDraftPatch.model_validate(payload.draft) if payload.draft else None
    request = MaterialReviseRequest(
        mode=payload.mode,  # type: ignore[arg-type]
        draft=draft_patch,
        tex=payload.tex,
        markdown_body=payload.markdown_body,
    )
    try:
        revised = revise_material(session, job, material, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _material_detail(revised)


@router.post("/jobs/{job_id}/materials/{material_id}/revise-request", response_model=GeneratedMaterialDetailOut)
def revise_material_request_endpoint(
    job_id: int,
    material_id: int,
    payload: MaterialInstructionRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialDetailOut:
    job, material = _get_job_material(session, job_id, material_id)
    if not (payload.instruction or "").strip():
        raise HTTPException(status_code=400, detail="instruction is required")
    try:
        revised = revise_material_with_instruction(session, job, material, payload.instruction)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _material_detail(revised)


@router.post("/jobs/{job_id}/materials/{material_id}/fit-pages", response_model=GeneratedMaterialDetailOut)
def fit_material_pages_endpoint(
    job_id: int,
    material_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialDetailOut:
    job, material = _get_job_material(session, job_id, material_id)
    try:
        revised = fit_material_to_two_pages(session, job, material)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _material_detail(revised)


@router.post("/jobs/{job_id}/materials/{material_id}/mark-final", response_model=GeneratedMaterialDetailOut)
def mark_material_final_endpoint(
    job_id: int,
    material_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialDetailOut:
    job, material = _get_job_material(session, job_id, material_id)
    try:
        marked = mark_material_final(session, job, material)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _material_detail(marked)


@router.post("/jobs/{job_id}/materials/{material_id}/unmark-final", response_model=GeneratedMaterialDetailOut)
def unmark_material_final_endpoint(
    job_id: int,
    material_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialDetailOut:
    job, material = _get_job_material(session, job_id, material_id)
    try:
        updated = unmark_material_final(session, job, material)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _material_detail(updated)


@router.post("/jobs/{job_id}/materials/cv", response_model=GeneratedMaterialOut)
def create_cv(job_id: int, session: Session = Depends(get_session)) -> GeneratedMaterialOut:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return _to_material_out(generate_cv(session, job))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/materials/cover-letter", response_model=GeneratedMaterialOut)
def create_cover_letter(job_id: int, session: Session = Depends(get_session)) -> GeneratedMaterialOut:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return _to_material_out(generate_cover_letter(session, job))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/materials/answer", response_model=GeneratedMaterialOut)
def create_answer(
    job_id: int,
    payload: MaterialAnswerRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        return _to_material_out(
            generate_answer(
                session,
                job,
                question=payload.question,
                word_limit=payload.word_limit,
                instructions=payload.instructions,
            )
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
