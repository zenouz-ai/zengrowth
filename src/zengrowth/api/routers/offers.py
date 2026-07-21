"""Offer stage endpoints (OFF-01).

Record an offer's terms once a process reaches the offer stage, generate a
market-benchmarked evaluation, and draft the acceptance / counter-offer /
clarification email. Domain dates are backdatable; audit rows never are.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session

from ...audit import log_action
from ...db import get_session
from ...interviews.offer_extractor import ExtractedOfferFields, extract_offer_fields
from ...interviews.offers import (
    generate_offer_evaluation,
    generate_offer_response,
    generate_onboarding_pack,
    list_offers,
    sync_job_outcome_from_offer,
)
from ...models import ActorType, Job, JobOffer
from ..llm_errors import llm_http_exception
from ..schemas import (
    DeparturePackRequest,
    GeneratedMaterialOut,
    OfferCreate,
    OfferExtractRequest,
    OfferExtractResponse,
    OfferOut,
    OfferPatch,
    OfferResponseDraftRequest,
)
from .interviews import _get_job

# Offer letters are small documents; refuse anything that plainly is not one.
_MAX_OFFER_UPLOAD_BYTES = 10 * 1024 * 1024
_OFFER_UPLOAD_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}

router = APIRouter(tags=["offers"])


def _get_offer(session: Session, job_id: int, offer_id: int) -> JobOffer:
    offer = session.get(JobOffer, offer_id)
    if not offer or offer.job_id != job_id:
        raise HTTPException(status_code=404, detail="offer not found")
    return offer


def _to_out(offer: JobOffer) -> OfferOut:
    return OfferOut.model_validate(offer, from_attributes=True)


@router.get("/jobs/{job_id}/offers", response_model=list[OfferOut])
def list_job_offers(job_id: int, session: Session = Depends(get_session)) -> list[OfferOut]:
    _get_job(session, job_id)
    return [_to_out(row) for row in list_offers(session, job_id)]


@router.post("/jobs/{job_id}/offers", response_model=OfferOut, status_code=201)
def create_offer(
    job_id: int,
    payload: OfferCreate,
    session: Session = Depends(get_session),
) -> OfferOut:
    job = _get_job(session, job_id)
    data = payload.model_dump(exclude={"sync_outcome"})
    offer = JobOffer(job_id=job_id, **data)
    session.add(offer)
    if payload.sync_outcome:
        sync_job_outcome_from_offer(session, job, offer)
    session.commit()
    session.refresh(offer)
    log_action(
        session,
        actor=ActorType.human,
        action="create_offer",
        entity_type="offer",
        entity_id=offer.id,
        detail={
            "job_id": job_id,
            "status": offer.status.value,
            "base_salary": offer.base_salary,
            "currency": offer.currency,
            "received_at": offer.received_at.isoformat() if offer.received_at else None,
            "deadline_at": offer.deadline_at.isoformat() if offer.deadline_at else None,
        },
    )
    return _to_out(offer)


@router.patch("/jobs/{job_id}/offers/{offer_id}", response_model=OfferOut)
def patch_offer(
    job_id: int,
    offer_id: int,
    payload: OfferPatch,
    session: Session = Depends(get_session),
) -> OfferOut:
    job = _get_job(session, job_id)
    offer = _get_offer(session, job_id, offer_id)
    data = payload.model_dump(exclude_unset=True, exclude={"sync_outcome"})
    for field, value in data.items():
        setattr(offer, field, value)
    offer.updated_at = datetime.now(UTC)
    session.add(offer)
    if payload.sync_outcome and "status" in data:
        sync_job_outcome_from_offer(session, job, offer)
    session.commit()
    session.refresh(offer)
    log_action(
        session,
        actor=ActorType.human,
        action="update_offer",
        entity_type="offer",
        entity_id=offer.id,
        detail={"job_id": job_id, "fields": sorted(data.keys()), "status": offer.status.value},
    )
    return _to_out(offer)


@router.delete("/jobs/{job_id}/offers/{offer_id}", status_code=204, response_model=None)
def delete_offer(
    job_id: int,
    offer_id: int,
    session: Session = Depends(get_session),
) -> None:
    offer = _get_offer(session, job_id, offer_id)
    session.delete(offer)
    session.commit()
    log_action(
        session,
        actor=ActorType.human,
        action="delete_offer",
        entity_type="offer",
        entity_id=offer_id,
        detail={"job_id": job_id},
    )


def _run_extraction(
    session: Session,
    job: Job,
    raw_text: str,
    *,
    action: str,
    extra_detail: dict | None = None,
) -> ExtractedOfferFields:
    """Shared extraction tail for the paste and upload entry points."""
    try:
        extracted = extract_offer_fields(raw_text=raw_text, session=session, entity_id=job.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    log_action(
        session,
        actor=ActorType.agent,
        action=action,
        entity_type="job",
        entity_id=job.id,
        detail={
            "chars": len(raw_text),
            "missing_fields": extracted.missing_fields,
            **(extra_detail or {}),
        },
    )
    return extracted


@router.post("/jobs/{job_id}/offers/extract", response_model=OfferExtractResponse)
def extract_offer(
    job_id: int,
    payload: OfferExtractRequest,
    session: Session = Depends(get_session),
) -> ExtractedOfferFields:
    """Paste-to-fill (OFF-04a): extract terms from a pasted offer email/letter.

    Returns prefill values for the offer form — nothing is saved until the
    operator reviews and submits. The raw text is preserved as ``offer_text``
    and never enters knowledge extraction.
    """
    job = _get_job(session, job_id)
    return _run_extraction(session, job, payload.raw_text, action="extract_offer_fields")


@router.post("/jobs/{job_id}/offers/extract-file", response_model=OfferExtractResponse)
def extract_offer_file(
    job_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> ExtractedOfferFields:
    """Upload-to-fill (OFF-04b): parse a PDF/DOCX offer letter, then extract terms.

    Reuses the knowledge document parsers for text extraction only — the letter
    is deliberately NOT ingested into the knowledge bank, so employer statements
    never become evidence claims.
    """
    job = _get_job(session, job_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _OFFER_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported offer document type: {suffix or '<none>'} "
            f"(expected one of {sorted(_OFFER_UPLOAD_SUFFIXES)})",
        )
    from ...knowledge.parsers import parse_document

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"offer{suffix}"
        written = 0
        with tmp_path.open("wb") as fh:
            # Enforce the cap while streaming so an oversized upload is
            # rejected at the boundary, not after a full disk copy.
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > _MAX_OFFER_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="offer document exceeds 10 MB")
                fh.write(chunk)
        try:
            parsed = parse_document(tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_extraction(
        session,
        job,
        parsed.text,
        action="extract_offer_file",
        extra_detail={"filename": file.filename},
    )


@router.post(
    "/jobs/{job_id}/materials/departure-pack",
    response_model=GeneratedMaterialOut,
    status_code=201,
)
def create_departure_pack(
    job_id: int,
    payload: DeparturePackRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    """Generate the leave-well pack (OFF-05): resignation, handover, checklist."""
    from ...interviews.departure import generate_departure_pack

    job = _get_job(session, job_id)
    try:
        material = generate_departure_pack(
            session,
            job,
            current_company=payload.current_company,
            current_role=payload.current_role,
            manager_name=payload.manager_name,
            notice_period=payload.notice_period,
            last_day_target=payload.last_day_target,
            responsibilities=payload.responsibilities,
            achievements=payload.achievements,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post(
    "/jobs/{job_id}/materials/onboarding-pack",
    response_model=GeneratedMaterialOut,
    status_code=201,
)
def create_onboarding_pack(
    job_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    """Generate the new-role start pack (OFF-03) for an accepted offer."""
    job = _get_job(session, job_id)
    try:
        material = generate_onboarding_pack(session, job)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post(
    "/jobs/{job_id}/offers/{offer_id}/evaluate",
    response_model=GeneratedMaterialOut,
    status_code=201,
)
def evaluate_offer(
    job_id: int,
    offer_id: int,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = _get_job(session, job_id)
    offer = _get_offer(session, job_id, offer_id)
    try:
        material = generate_offer_evaluation(session, job, offer)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)


@router.post(
    "/jobs/{job_id}/offers/{offer_id}/response-draft",
    response_model=GeneratedMaterialOut,
    status_code=201,
)
def draft_offer_response(
    job_id: int,
    offer_id: int,
    payload: OfferResponseDraftRequest,
    session: Session = Depends(get_session),
) -> GeneratedMaterialOut:
    job = _get_job(session, job_id)
    offer = _get_offer(session, job_id, offer_id)
    try:
        material = generate_offer_response(
            session,
            job,
            offer,
            response_type=payload.response_type,
            instructions=payload.instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise llm_http_exception(exc) from exc
    from .jobs import _to_material_out

    return _to_material_out(material)
