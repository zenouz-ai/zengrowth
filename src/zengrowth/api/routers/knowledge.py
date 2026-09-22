"""Knowledge ingestion, review, and graph search routes."""

from __future__ import annotations

import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ...audit import log_action
from ...config import get_settings
from ...db import get_session
from ...knowledge.coverage import coverage_report
from ...knowledge.facets import backfill_facets, facets_available
from ...knowledge.local_graph import build_local_graph
from ...knowledge.service import (
    IngestResult,
    activate_version,
    diff_source_versions,
    import_inbox,
    ingest_path,
    is_cv_style_upload,
    knowledge_paths,
    paste_document,
    set_active_template,
    summarize_version_diff,
)
from ...models import (
    ActorType,
    ClaimVerificationState,
    EvidenceClaim,
    KnowledgeEntity,
    SourceChunk,
    SourceDocument,
    SourceDocumentType,
)
from ..schemas_knowledge import (
    ClaimUpdate,
    CoverageOut,
    DiffSummaryOut,
    DiffSummaryRequest,
    EvidenceClaimOut,
    FacetBackfillOut,
    GraphEdgeOut,
    GraphNodeOut,
    InboxImportOut,
    IngestResultOut,
    KnowledgeGraphOut,
    PasteIngestRequest,
    SourceDocumentDetailOut,
    SourceDocumentOut,
    VersionDiffOut,
)

router = APIRouter(tags=["knowledge"])

# Extensions served as inline plain text in the knowledge preview pane.
_TEXTLIKE_SUFFIXES = {".tex", ".md", ".markdown", ".txt", ".rst", ".csv", ".json", ".log"}


@router.post("/knowledge/upload", response_model=IngestResultOut)
def upload_knowledge_source(
    file: UploadFile = File(...),
    source_type: SourceDocumentType = SourceDocumentType.document,
    session: Session = Depends(get_session),
) -> IngestResultOut:
    paths = knowledge_paths()
    upload_path = paths.inbox / Path(file.filename or "upload").name
    with upload_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    promote = is_cv_style_upload(upload_path)
    if promote:
        source_type = SourceDocumentType.cv
    try:
        result = ingest_path(
            session, upload_path, source_type=source_type, promote_template=promote
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ingest_result_out(result)


@router.post("/knowledge/import-inbox", response_model=InboxImportOut)
def import_knowledge_inbox(session: Session = Depends(get_session)) -> InboxImportOut:
    try:
        results = import_inbox(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InboxImportOut(results=[_ingest_result_out(result) for result in results])


@router.post("/knowledge/paste", response_model=IngestResultOut)
def paste_knowledge_source(
    payload: PasteIngestRequest,
    session: Session = Depends(get_session),
) -> IngestResultOut:
    try:
        result = paste_document(
            session,
            text=payload.text,
            filename=payload.filename,
            fmt=payload.format,
            source_type=payload.source_type,
            title=payload.title,
            lineage_id=payload.lineage_id,
            supersedes_id=payload.supersedes_id,
            promote_template=payload.promote_template,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ingest_result_out(result)


@router.get("/knowledge/sources", response_model=list[SourceDocumentOut])
def list_knowledge_sources(session: Session = Depends(get_session)) -> list[SourceDocument]:
    stmt = select(SourceDocument).order_by(SourceDocument.created_at.desc())  # type: ignore[union-attr]
    return list(session.exec(stmt))


@router.get("/knowledge/sources/{source_id}", response_model=SourceDocumentDetailOut)
def get_knowledge_source(
    source_id: int,
    session: Session = Depends(get_session),
) -> SourceDocumentDetailOut:
    source = session.get(SourceDocument, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="source document not found")
    chunks = list(
        session.exec(
            select(SourceChunk)
            .where(SourceChunk.source_document_id == source_id)
            .order_by(SourceChunk.chunk_index)
        )
    )
    claims = list(
        session.exec(
            select(EvidenceClaim)
            .where(EvidenceClaim.source_document_id == source_id)
            .order_by(EvidenceClaim.created_at.desc())  # type: ignore[union-attr]
        )
    )
    entities = list(
        session.exec(
            select(KnowledgeEntity)
            .where(KnowledgeEntity.source_document_id == source_id)
            .order_by(KnowledgeEntity.name)
        )
    )
    versions: list[SourceDocument] = []
    if source.lineage_id:
        versions = list(
            session.exec(
                select(SourceDocument)
                .where(SourceDocument.lineage_id == source.lineage_id)
                .order_by(SourceDocument.version.desc())  # type: ignore[union-attr]
            )
        )
    return SourceDocumentDetailOut(
        **SourceDocumentOut.model_validate(source).model_dump(),
        chunks=chunks,
        claims=claims,
        entities=entities,
        versions=[SourceDocumentOut.model_validate(v) for v in versions],
    )


@router.get("/knowledge/sources/{source_id}/file")
def get_knowledge_source_file(
    source_id: int,
    kind: str = Query(default="original", pattern="^(original|processed)$"),
    session: Session = Depends(get_session),
) -> FileResponse:
    source = session.get(SourceDocument, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="source document not found")
    raw_path = source.original_path if kind == "original" else source.processed_path
    if not raw_path:
        raise HTTPException(status_code=404, detail=f"{kind} file not available")
    resolved = Path(raw_path).resolve()
    root = knowledge_paths().root.resolve()
    if root not in resolved.parents and resolved != root:
        raise HTTPException(status_code=403, detail="file outside knowledge root")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="file not found on disk")
    media_type = mimetypes.guess_type(source.filename)[0] or "application/octet-stream"
    # Serve text-like sources (incl. LaTeX/Markdown originals) as plain text so
    # they render in the preview pane instead of triggering a browser download.
    suffix = Path(source.filename).suffix.lower()
    if kind == "processed" or suffix in _TEXTLIKE_SUFFIXES:
        media_type = "text/plain; charset=utf-8"
    # Inline disposition lets the dashboard iframe (and "open in new tab") render
    # previewable formats; non-previewable binaries still download.
    previewable = media_type.startswith("text/") or media_type == "application/pdf"
    return FileResponse(
        resolved,
        media_type=media_type,
        filename=source.filename if kind == "original" else f"{source.filename}.txt",
        content_disposition_type="inline" if previewable else "attachment",
    )


@router.get("/knowledge/sources/{source_id}/diff", response_model=VersionDiffOut)
def knowledge_version_diff(
    source_id: int,
    against: int = Query(..., description="Older version id to diff against"),
    session: Session = Depends(get_session),
) -> VersionDiffOut:
    try:
        result = diff_source_versions(session, against, source_id)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc
    return VersionDiffOut(**result)  # type: ignore[arg-type]


@router.post("/knowledge/sources/{source_id}/diff-summary", response_model=DiffSummaryOut)
def knowledge_version_diff_summary(
    source_id: int,
    payload: DiffSummaryRequest,
    session: Session = Depends(get_session),
) -> DiffSummaryOut:
    try:
        summary = summarize_version_diff(session, payload.against, source_id)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc
    return DiffSummaryOut(summary=summary)


@router.get("/knowledge/graph", response_model=KnowledgeGraphOut)
def knowledge_graph(
    include_claims: bool = False,
    include_entities: bool = False,
    include_lineage: bool = False,
    session: Session = Depends(get_session),
) -> KnowledgeGraphOut:
    graph = build_local_graph(
        session,
        include_claims=include_claims,
        include_entities=include_entities,
        include_lineage=include_lineage,
    )
    return KnowledgeGraphOut(
        nodes=[GraphNodeOut(**vars(node)) for node in graph.nodes],
        edges=[GraphEdgeOut(**vars(edge)) for edge in graph.edges],
    )


@router.get("/knowledge/coverage", response_model=CoverageOut)
def knowledge_coverage(session: Session = Depends(get_session)) -> CoverageOut:
    """KG-02: facet counts, evidence-over-time, and coverage-vs-demand data."""
    return CoverageOut(**coverage_report(session))


@router.post("/knowledge/coverage/backfill", response_model=FacetBackfillOut)
def knowledge_coverage_backfill(
    force: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> FacetBackfillOut:
    """Batch-facet extracted documents and scored jobs (skips already-faceted unless force)."""
    settings = get_settings()
    if not facets_available(settings):
        raise HTTPException(
            status_code=400,
            detail="Facet assignment needs an Anthropic API key — add one in Setup first.",
        )
    report = backfill_facets(session, settings=settings, force=force)
    log_action(
        session,
        actor=ActorType.human,
        action="knowledge_facet_backfill",
        entity_type="knowledge",
        entity_id=None,
        detail={
            "documents_faceted": report.documents_faceted,
            "jobs_faceted": report.jobs_faceted,
            "facet_rows": report.facet_rows,
            "force": force,
        },
    )
    return FacetBackfillOut(
        documents_faceted=report.documents_faceted,
        documents_skipped=report.documents_skipped,
        jobs_faceted=report.jobs_faceted,
        jobs_skipped=report.jobs_skipped,
        facet_rows=report.facet_rows,
        rejected=report.rejected[:50],
    )


@router.post("/knowledge/sources/{source_id}/promote-template", response_model=SourceDocumentOut)
def promote_template(
    source_id: int,
    session: Session = Depends(get_session),
) -> SourceDocument:
    try:
        return set_active_template(session, source_id, role="cv_style")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/sources/{source_id}/activate", response_model=SourceDocumentOut)
def activate_source_version(
    source_id: int,
    session: Session = Depends(get_session),
) -> SourceDocument:
    try:
        return activate_version(session, source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge/claims", response_model=list[EvidenceClaimOut])
def list_knowledge_claims(
    state: ClaimVerificationState | None = None,
    session: Session = Depends(get_session),
) -> list[EvidenceClaim]:
    stmt = select(EvidenceClaim)
    if state is not None:
        stmt = stmt.where(EvidenceClaim.verification_state == state)
    stmt = stmt.order_by(EvidenceClaim.created_at.desc())  # type: ignore[union-attr]
    return list(session.exec(stmt))


@router.post("/knowledge/claims/{claim_id}/verify", response_model=EvidenceClaimOut)
def verify_claim(claim_id: str, session: Session = Depends(get_session)) -> EvidenceClaim:
    return _set_claim_state(session, claim_id, ClaimVerificationState.verified)


@router.post("/knowledge/claims/{claim_id}/reject", response_model=EvidenceClaimOut)
def reject_claim(claim_id: str, session: Session = Depends(get_session)) -> EvidenceClaim:
    return _set_claim_state(session, claim_id, ClaimVerificationState.rejected)


@router.post("/knowledge/claims/{claim_id}/reopen", response_model=EvidenceClaimOut)
def reopen_claim(claim_id: str, session: Session = Depends(get_session)) -> EvidenceClaim:
    return _set_claim_state(session, claim_id, ClaimVerificationState.draft)


@router.patch("/knowledge/claims/{claim_id}", response_model=EvidenceClaimOut)
def update_claim(
    claim_id: str,
    payload: ClaimUpdate,
    session: Session = Depends(get_session),
) -> EvidenceClaim:
    claim = session.get(EvidenceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="claim not found")
    update = payload.model_dump(exclude_unset=True)
    for key, value in update.items():
        setattr(claim, key, value)
    # TP-13: editing the substance of an already-decided claim invalidates the
    # prior decision. If claim_text or source_span changed on a verified/rejected
    # claim (and the caller didn't explicitly set a new state), reopen it to draft
    # so the edited wording is re-reviewed rather than silently inheriting trust.
    substance_changed = bool({"claim_text", "source_span"} & set(update))
    reopened = False
    if (
        substance_changed
        and "verification_state" not in update
        and claim.verification_state != ClaimVerificationState.draft
    ):
        claim.verification_state = ClaimVerificationState.draft
        reopened = True
    claim.updated_at = datetime.now(UTC)
    session.add(claim)
    session.commit()
    session.refresh(claim)
    log_action(
        session,
        actor=ActorType.human,
        action="knowledge_claim_edited",
        entity_type="evidence_claim",
        entity_id=claim.id,
        detail={"fields": sorted(update), "reopened_to_draft": reopened},
    )
    return claim


def _set_claim_state(
    session: Session,
    claim_id: str,
    state: ClaimVerificationState,
) -> EvidenceClaim:
    claim = session.get(EvidenceClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="claim not found")
    claim.verification_state = state
    claim.updated_at = datetime.now(UTC)
    session.add(claim)
    session.commit()
    session.refresh(claim)
    log_action(
        session,
        actor=ActorType.human,
        action=f"knowledge_claim_{state.value}",
        entity_type="evidence_claim",
        entity_id=claim.id,
    )
    return claim


def _ingest_result_out(result: IngestResult) -> IngestResultOut:
    return IngestResultOut(
        source_document=SourceDocumentOut.model_validate(result.document),
        created=result.created,
        chunks=result.chunks,
        claims=result.claims,
        verified_claims=result.verified_claims,
    )
