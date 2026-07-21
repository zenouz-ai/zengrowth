"""Interview timeline endpoints (INT-01).

Rounds are backdatable via operator-settable ``scheduled_at`` / ``occurred_at``;
audit rows keep their true timestamps. Internal artifacts (imported packs,
debriefs) attach to a round or to the job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ...audit import log_action
from ...db import get_session
from ...interviews.debrief import generate_debrief, generate_email_draft
from ...interviews.packs import PACK_TYPES, generate_pack
from ...interviews.service import (
    import_internal_material,
    list_interviews,
    promote_learning,
    sync_job_outcome_from_round,
)
from ...interviews.sim_prompt import generate_sim_prompt
from ...models import ActorType, GeneratedMaterial, Interview, Job
from ..llm_errors import llm_http_exception
from ..schemas import (
    EmailDraftRequest,
    GeneratedMaterialOut,
    InterviewCreate,
    InterviewDetailOut,
    InterviewOut,
    InterviewPatch,
    InterviewTranscriptIn,
    MaterialImportRequest,
    MaterialPackRequest,
    PromoteLearningRequest,
    SimPromptRequest,
)
from ..schemas_knowledge import EvidenceClaimOut

router = APIRouter(tags=["interviews"])


def _get_job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _get_interview(session: Session, job_id: int, interview_id: int) -> Interview:
    interview = session.get(Interview, interview_id)
    if not interview or interview.job_id != job_id:
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _debrief_source(interview: Interview) -> str:
    return (interview.transcript or "").strip() or (interview.notes or "").strip()


def _to_out(interview: Interview) -> InterviewOut:
    return InterviewOut(
        id=interview.id or 0,
        job_id=interview.job_id,
        round_type=interview.round_type,
        title=interview.title,
        format=interview.format,
        status=interview.status,
        scheduled_at=interview.scheduled_at,
        occurred_at=interview.occurred_at,
        participants=interview.participants,
        notes=interview.notes,
        has_transcript=bool((interview.transcript or "").strip()),
        can_debrief=bool(_debrief_source(interview)),
        transcript_updated_at=interview.transcript_updated_at,
        created_at=interview.created_at,
        updated_at=interview.updated_at,
    )


def _to_detail(interview: Interview) -> InterviewDetailOut:
    return InterviewDetailOut(
        **_to_out(interview).model_dump(),
        transcript=interview.transcript,
    )


@router.get("/jobs/{job_id}/interviews", response_model=list[InterviewOut])
def list_job_interviews(job_id: int, session: Session = Depends(get_session)) -> list[InterviewOut]:
    _get_job(session, job_id)
    return [_to_out(row) for row in list_interviews(session, job_id)]


def _apply_transcript_timestamp(data: dict[str, object]) -> None:
    transcript = data.get("transcript")
    if isinstance(transcript, str) and transcript.strip():
        data["transcript_updated_at"] = datetime.now(UTC)


@router.post("/jobs/{job_id}/interviews", response_model=InterviewOut, status_code=201)
def create_interview(
    job_id: int,
    payload: InterviewCreate,
    session: Session = Depends(get_session),
) -> InterviewOut:
    job = _get_job(session, job_id)
    data = payload.model_dump(exclude={"sync_outcome"})
    _apply_transcript_timestamp(data)
    interview = Interview(job_id=job_id, **data)
    session.add(interview)
    if payload.sync_outcome:
        sync_job_outcome_from_round(session, job, interview.round_type)
    session.commit()
    session.refresh(interview)
    log_action(
        session,
        actor=ActorType.human,
        action="create_interview",
        entity_type="interview",
        entity_id=interview.id,
        detail={
            "job_id": job_id,
            "round_type": interview.round_type.value,
            "scheduled_at": interview.scheduled_at.isoformat() if interview.scheduled_at else None,
            "occurred_at": interview.occurred_at.isoformat() if interview.occurred_at else None,
        },
    )
    return _to_out(interview)


@router.get("/jobs/{job_id}/interviews/{interview_id}", response_model=InterviewDetailOut)
def get_interview(
    job_id: int,
    interview_id: int,
    session: Session = Depends(get_session),
) -> InterviewDetailOut:
    return _to_detail(_get_interview(session, job_id, interview_id))


@router.patch("/jobs/{job_id}/interviews/{interview_id}", response_model=InterviewOut)
def patch_interview(
    job_id: int,
    interview_id: int,
    payload: InterviewPatch,
    session: Session = Depends(get_session),
) -> InterviewOut:
    job = _get_job(session, job_id)
    interview = _get_interview(session, job_id, interview_id)
    data = payload.model_dump(exclude_unset=True, exclude={"sync_outcome"})
    if "transcript" in data:
        _apply_transcript_timestamp(data)
    for field, value in data.items():
        setattr(interview, field, value)
    interview.updated_at = datetime.now(UTC)
    session.add(interview)
    if payload.sync_outcome and ("round_type" in data or "status" in data):
        sync_job_outcome_from_round(session, job, interview.round_type)
    session.commit()
    session.refresh(interview)
    log_action(
        session,
        actor=ActorType.human,
        action="update_interview",
        entity_type="interview",
        entity_id=interview.id,
        detail={"job_id": job_id, "fields": sorted(data.keys())},
    )
    return _to_out(interview)


@router.delete("/jobs/{job_id}/interviews/{interview_id}", status_code=204, response_model=None)
def delete_interview(
    job_id: int,
    interview_id: int,
    session: Session = Depends(get_session),
) -> None:
    interview = _get_interview(session, job_id, interview_id)
    # Keep artifacts; they fall back to job-level materials.
    for material in session.exec(
        select(GeneratedMaterial).where(GeneratedMaterial.interview_id == interview_id)
    ):
        material.interview_id = None
        session.add(material)
    session.delete(interview)
    session.commit()
    log_action(
        session,
        actor=ActorType.human,
        action="delete_interview",
        entity_type="interview",
        entity_id=interview_id,
        detail={"job_id": job_id},
    )


@router.put("/jobs/{job_id}/interviews/{interview_id}/transcript", response_model=InterviewDetailOut)
def set_transcript(
    job_id: int,
    interview_id: int,
    payload: InterviewTranscriptIn,
    session: Session = Depends(get_session),
) -> InterviewDetailOut:
    interview = _get_interview(session, job_id, interview_id)
    interview.transcript = payload.transcript.strip()
    interview.transcript_updated_at = datetime.now(UTC)
    interview.updated_at = datetime.now(UTC)
    session.add(interview)
    session.commit()
    session.refresh(interview)
    log_action(
        session,
        actor=ActorType.human,
        action="set_interview_transcript",
        entity_type="interview",
        entity_id=interview.id,
        detail={"job_id": job_id, "transcript_chars": len(payload.transcript)},
    )
    return _to_detail(interview)


@router.post(
    "/jobs/{job_id}/interviews/{interview_id}/promote-learning",
    response_model=EvidenceClaimOut,
    status_code=201,
)
def promote_learning_endpoint(
    job_id: int,
    interview_id: int,
    payload: PromoteLearningRequest,
    session: Session = Depends(get_session),
) -> EvidenceClaimOut:
    job = _get_job(session, job_id)
    interview = _get_interview(session, job_id, interview_id)
    try:
        claim, _created = promote_learning(
            session, job, claim_text=payload.claim_text, interview=interview
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvidenceClaimOut.model_validate(claim)


@router.post(
    "/jobs/{job_id}/interviews/{interview_id}/debrief",
    response_model=GeneratedMaterialOut,
    status_code=201,
)
def create_debrief(
    job_id: int,
    interview_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = _get_job(session, job_id)
    interview = _get_interview(session, job_id, interview_id)
    try:
        material = generate_debrief(session, job, interview)
    except ValueError as exc:
        msg = str(exc)
        status = 409 if "transcript" in msg.lower() or "notes" in msg.lower() else 502
        raise HTTPException(status_code=status, detail=msg) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post("/jobs/{job_id}/materials/email-draft", response_model=GeneratedMaterialOut, status_code=201)
def create_email_draft(
    job_id: int,
    payload: EmailDraftRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = _get_job(session, job_id)
    interview = (
        _get_interview(session, job_id, payload.interview_id)
        if payload.interview_id is not None
        else None
    )
    if not (payload.instructions or "").strip() and not (payload.inbound_email or "").strip():
        raise HTTPException(
            status_code=400,
            detail="paste the email you received and/or say what the email should do",
        )
    try:
        material = generate_email_draft(
            session,
            job,
            instructions=payload.instructions,
            inbound_email=payload.inbound_email,
            interview=interview,
        )
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post("/jobs/{job_id}/materials/sim-prompt", response_model=GeneratedMaterialOut, status_code=201)
def create_sim_prompt(
    job_id: int,
    payload: SimPromptRequest | None = None,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    """Deterministic (no-LLM) voice-interviewer simulation prompt (INT-05)."""
    job = _get_job(session, job_id)
    interview_id = payload.interview_id if payload else None
    interview = (
        _get_interview(session, job_id, interview_id) if interview_id is not None else None
    )
    material = generate_sim_prompt(session, job, interview=interview)
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post("/jobs/{job_id}/materials/pack", response_model=GeneratedMaterialOut, status_code=201)
def create_pack(
    job_id: int,
    payload: MaterialPackRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    if payload.pack_type not in PACK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported pack type: {payload.pack_type!r} (expected one of {list(PACK_TYPES)})",
        )
    job = _get_job(session, job_id)
    interview = (
        _get_interview(session, job_id, payload.interview_id)
        if payload.interview_id is not None
        else None
    )
    try:
        material = generate_pack(
            session,
            job,
            pack_type=payload.pack_type,
            interview=interview,
            enhance=payload.enhance,
            source_material_id=payload.source_material_id,
        )
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post("/jobs/{job_id}/materials/import", response_model=GeneratedMaterialOut, status_code=201)
def import_material(
    job_id: int,
    payload: MaterialImportRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = _get_job(session, job_id)
    if payload.interview_id is not None:
        _get_interview(session, job_id, payload.interview_id)
    try:
        material = import_internal_material(
            session,
            job,
            material_type=payload.material_type,
            title=payload.title,
            content=payload.content,
            interview_id=payload.interview_id,
            effective_date=payload.effective_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)
