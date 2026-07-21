"""Knowledge ingestion orchestration."""

from __future__ import annotations

import difflib
import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from ..audit import log_action, log_action_safe
from ..config import Settings, get_settings
from ..models import (
    ActorType,
    ClaimFacet,
    ClaimVerificationState,
    EvidenceClaim,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceChunk,
    SourceDocument,
    SourceDocumentStatus,
    SourceDocumentType,
)
from ..observability.tracing import pipeline_run, tool_step
from .chunking import chunk_text
from .embeddings import EmbeddingClient, build_default_embedder
from .entity_resolution import find_entity_alias, record_alias
from .extractor import ExtractionResult, KnowledgeExtractionClient, build_default_extractor
from .facets import (
    FacetAssignmentClient,
    assign_document_facets,
    build_default_facet_assigner,
    facets_available,
)
from .parsers import SUPPORTED_EXTENSIONS, parse_document
from .provenance import (
    ensure_claim_document_link,
    ensure_entity_document_link,
    find_claims_by_normalized_span,
    pick_canonical_claim,
)


@dataclass
class KnowledgePaths:
    root: Path
    inbox: Path
    originals: Path
    processed: Path


@dataclass
class IngestResult:
    document: SourceDocument
    created: bool
    chunks: int
    claims: int
    verified_claims: int


def knowledge_paths(settings: Settings | None = None) -> KnowledgePaths:
    settings = settings or get_settings()
    root = Path(settings.knowledge_root)
    paths = KnowledgePaths(
        root=root,
        inbox=root / "inbox",
        originals=root / "originals",
        processed=root / "processed",
    )
    for path in (paths.inbox, paths.originals, paths.processed):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def ingest_path(
    session: Session,
    path: str | Path,
    *,
    source_type: SourceDocumentType = SourceDocumentType.document,
    title: str | None = None,
    lineage_id: str | None = None,
    supersedes_id: int | None = None,
    template_role: str | None = None,
    promote_template: bool = False,
    extractor: KnowledgeExtractionClient | None = None,
    embedder: EmbeddingClient | None = None,
    facet_assigner: FacetAssignmentClient | None = None,
    settings: Settings | None = None,
) -> IngestResult:
    settings = settings or get_settings()
    paths = knowledge_paths(settings)
    source_path = Path(path)
    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported knowledge document type: {source_path.suffix or '<none>'}")
    if promote_template:
        template_role = "cv_style"
        if supersedes_id is None:
            active = active_template_document(session, role="cv_style")
            if active is not None:
                supersedes_id = active.id
    digest = file_sha256(source_path)
    existing = session.exec(select(SourceDocument).where(SourceDocument.content_hash == digest)).first()
    if existing is not None:
        if existing.status != SourceDocumentStatus.extracted:
            _clear_document_derivatives(session, existing)
            existing.error = None
            existing.source_type = source_type
            existing.updated_at = datetime.now(UTC)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            log_action_safe(
                session,
                actor=ActorType.system,
                action="knowledge_source_retry",
                entity_type="source_document",
                entity_id=existing.id,
                detail={"filename": existing.filename},
            )
            try:
                result = process_document(
                    session,
                    existing,
                    extractor=extractor,
                    embedder=embedder,
                    facet_assigner=facet_assigner,
                    settings=settings,
                    created=False,
                )
            except Exception as exc:
                _mark_document_failed(session, existing, exc)
                raise
            if promote_template and result.document.id is not None:
                set_active_template(session, result.document.id, role="cv_style")
            return result
        log_action_safe(
            session,
            actor=ActorType.system,
            action="knowledge_source_duplicate",
            entity_type="source_document",
            entity_id=existing.id,
            detail={"filename": existing.filename},
        )
        if promote_template and existing.id is not None:
            set_active_template(session, existing.id, role="cv_style")
        return IngestResult(existing, False, 0, 0, 0)

    stored_path = _copy_original(source_path, digest, paths)
    document = SourceDocument(
        filename=source_path.name,
        title=title or source_path.name,
        original_path=str(stored_path),
        content_hash=digest,
        source_type=source_type,
        status=SourceDocumentStatus.imported,
        meta={"extension": source_path.suffix.lower()},
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    if lineage_id is not None or supersedes_id is not None or template_role is not None:
        _link_version(
            session,
            document,
            lineage_id=lineage_id,
            supersedes_id=supersedes_id,
            template_role=template_role,
        )
    log_action(
        session,
        actor=ActorType.human,
        action="knowledge_source_imported",
        entity_type="source_document",
        entity_id=document.id,
        detail={"filename": document.filename, "source_type": document.source_type.value},
    )

    try:
        result = process_document(
            session,
            document,
            extractor=extractor,
            embedder=embedder,
            facet_assigner=facet_assigner,
            settings=settings,
        )
    except Exception as exc:
        _mark_document_failed(session, document, exc)
        raise
    if promote_template and result.document.id is not None:
        set_active_template(session, result.document.id, role="cv_style")
    return result


def process_document(
    session: Session,
    document: SourceDocument,
    *,
    extractor: KnowledgeExtractionClient | None = None,
    embedder: EmbeddingClient | None = None,
    facet_assigner: FacetAssignmentClient | None = None,
    settings: Settings | None = None,
    created: bool = True,
) -> IngestResult:
    settings = settings or get_settings()
    extractor = extractor or build_default_extractor(settings, session=session, entity_id=document.id)
    # Embeddings are opt-in (settings.knowledge_embeddings_enabled): nothing reads
    # the chunk vectors today, so by default we skip the OpenAI call entirely. An
    # explicitly-supplied embedder (tests, or a future hybrid retriever) is always
    # honoured.
    if embedder is None and settings.knowledge_embeddings_enabled:
        embedder = build_default_embedder(settings, session=session, entity_id=document.id)
    paths = knowledge_paths(settings)

    with pipeline_run(
        session,
        pipeline_type="knowledge_ingest",
        entity_type="source_document",
        entity_id=document.id,
        detail={"filename": document.filename},
    ):
        return _process_document_body(
            session,
            document,
            extractor=extractor,
            embedder=embedder,
            facet_assigner=facet_assigner,
            settings=settings,
            paths=paths,
            created=created,
        )


def _process_document_body(
    session: Session,
    document: SourceDocument,
    *,
    extractor: KnowledgeExtractionClient,
    embedder: EmbeddingClient | None,
    facet_assigner: FacetAssignmentClient | None,
    settings: Settings,
    paths: KnowledgePaths,
    created: bool,
) -> IngestResult:
    parsed = parse_document(document.original_path)
    processed_path = paths.processed / f"{document.content_hash}.txt"
    processed_path.write_text(parsed.text, encoding="utf-8")
    document.processed_path = str(processed_path)
    document.status = SourceDocumentStatus.parsed
    document.meta = {**(document.meta or {}), **parsed.metadata}
    document.updated_at = datetime.now(UTC)
    session.add(document)
    session.commit()
    session.refresh(document)
    log_action(
        session,
        actor=ActorType.system,
        action="knowledge_source_parsed",
        entity_type="source_document",
        entity_id=document.id,
        detail={"processed_path": document.processed_path},
    )

    chunks = chunk_text(parsed.text)
    if embedder is not None:
        with tool_step(
            session, step_name="embed_chunks", step_type="llm", detail={"chunk_count": len(chunks)}
        ):
            embeddings: list[list[float] | None] = list(embedder.embed([chunk.text for chunk in chunks]))
    else:
        # Embeddings disabled: store the chunks without vectors (no OpenAI spend).
        embeddings = [None] * len(chunks)
    chunk_rows: list[SourceChunk] = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        row = SourceChunk(
            source_document_id=document.id or 0,
            chunk_index=chunk.index,
            text=chunk.text,
            section_path=chunk.section_path,
            page_start=chunk.page_start,
            line_start=chunk.line_start,
            token_estimate=chunk.token_estimate,
            embedding=embedding,
        )
        session.add(row)
        chunk_rows.append(row)
    session.commit()
    for row in chunk_rows:
        session.refresh(row)

    claim_count = 0
    verified_count = 0
    entity_by_name: dict[str, KnowledgeEntity] = {}
    for chunk_row in chunk_rows:
        with tool_step(
            session,
            step_name=f"extract_chunk_{chunk_row.chunk_index}",
            step_type="llm",
            detail={"chunk_id": chunk_row.id},
        ):
            result = extractor.extract(
                text=chunk_row.text,
                metadata={"filename": document.filename, "chunk_index": chunk_row.chunk_index},
                model=settings.scoring_model,
            )
        created_claims = _store_extraction(
            session,
            document,
            chunk_row,
            result,
            entity_by_name,
            threshold=settings.knowledge_auto_verify_threshold,
        )
        claim_count += len(created_claims)
        verified_count += sum(
            1
            for claim in created_claims
            if claim.verification_state == ClaimVerificationState.verified
        )
    document.status = SourceDocumentStatus.extracted
    document.summary = _derive_summary(session, document, parsed.text)
    document.updated_at = datetime.now(UTC)
    session.add(document)
    session.commit()
    session.refresh(document)
    log_action(
        session,
        actor=ActorType.agent,
        action="knowledge_claims_extracted",
        entity_type="source_document",
        entity_id=document.id,
        detail={"claims": claim_count, "verified": verified_count},
    )

    # KG-02: facet the document's claims for the coverage map. Facets are
    # derived metadata, so this pass is skipped without an Anthropic key (or an
    # explicitly injected assigner) and a failure never fails the ingest.
    if facet_assigner is None and facets_available(settings):
        facet_assigner = build_default_facet_assigner(
            settings, session=session, entity_type="source_document", entity_id=document.id
        )
    if facet_assigner is not None and claim_count:
        try:
            with tool_step(
                session,
                step_name="assign_facets",
                step_type="llm",
                detail={"claims": claim_count},
            ):
                assign_document_facets(
                    session, document, assigner=facet_assigner, settings=settings
                )
        except Exception as exc:
            session.rollback()
            log_action_safe(
                session,
                actor=ActorType.system,
                action="knowledge_facets_failed",
                entity_type="source_document",
                entity_id=document.id,
                detail={"error": str(exc)},
            )

    return IngestResult(document, created, len(chunk_rows), claim_count, verified_count)


def import_inbox(
    session: Session,
    *,
    settings: Settings | None = None,
    extractor: KnowledgeExtractionClient | None = None,
    embedder: EmbeddingClient | None = None,
    facet_assigner: FacetAssignmentClient | None = None,
) -> list[IngestResult]:
    paths = knowledge_paths(settings)
    results: list[IngestResult] = []
    for path in sorted(paths.inbox.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            results.append(
                ingest_path(
                    session,
                    path,
                    source_type=infer_source_type(path),
                    promote_template=is_cv_style_upload(path),
                    settings=settings,
                    extractor=extractor,
                    embedder=embedder,
                    facet_assigner=facet_assigner,
                )
            )
    return results


def is_cv_style_upload(path: str | Path) -> bool:
    """Return True when an uploaded file should be treated as the CV LaTeX style.

    The CV style is the only ``.tex`` template the system maintains, so any
    ``.tex`` source is promoted to the active ``cv_style`` template on import.
    """
    return Path(path).suffix.lower() == ".tex"


def infer_source_type(path: Path) -> SourceDocumentType:
    lower = path.name.lower()
    if "cv" in lower or "resume" in lower:
        return SourceDocumentType.cv
    if "project" in lower or "case" in lower:
        return SourceDocumentType.project
    if lower.endswith(".md") or "note" in lower:
        return SourceDocumentType.note
    return SourceDocumentType.document


_FORMAT_EXTENSIONS: dict[str, str] = {"md": ".md", "txt": ".txt", "tex": ".tex"}


def paste_document(
    session: Session,
    *,
    text: str,
    filename: str,
    fmt: str,
    source_type: SourceDocumentType = SourceDocumentType.document,
    title: str | None = None,
    lineage_id: str | None = None,
    supersedes_id: int | None = None,
    promote_template: bool = False,
    settings: Settings | None = None,
    extractor: KnowledgeExtractionClient | None = None,
    embedder: EmbeddingClient | None = None,
    facet_assigner: FacetAssignmentClient | None = None,
) -> IngestResult:
    """Persist pasted text as a versioned knowledge source via the normal pipeline."""
    suffix = _FORMAT_EXTENSIONS.get(fmt.lower())
    if suffix is None:
        raise ValueError(f"unsupported paste format: {fmt}")
    if not text.strip():
        raise ValueError("pasted text is empty")
    safe_name = _safe_filename(filename, suffix)
    tmp_dir = Path(tempfile.mkdtemp(prefix="zg-paste-"))
    try:
        tmp_path = tmp_dir / safe_name
        tmp_path.write_text(text, encoding="utf-8")
        result = ingest_path(
            session,
            tmp_path,
            source_type=source_type,
            title=title or safe_name,
            lineage_id=lineage_id,
            supersedes_id=supersedes_id,
            promote_template=promote_template,
            settings=settings,
            extractor=extractor,
            embedder=embedder,
            facet_assigner=facet_assigner,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


def _safe_filename(filename: str, suffix: str) -> str:
    base = Path(filename or "pasted").name.strip() or "pasted"
    stem = Path(base).stem or "pasted"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "pasted"
    return f"{stem}{suffix}"


def _link_version(
    session: Session,
    document: SourceDocument,
    *,
    lineage_id: str | None = None,
    supersedes_id: int | None = None,
    template_role: str | None = None,
) -> SourceDocument:
    """Attach ``document`` to a version lineage and mark it the current head."""
    parent = session.get(SourceDocument, supersedes_id) if supersedes_id else None
    if parent is not None:
        lineage = parent.lineage_id or f"lin-{parent.id}"
        if parent.lineage_id != lineage:
            parent.lineage_id = lineage
            session.add(parent)
        document.supersedes_id = parent.id
        document.version = parent.version + 1
        inherited_role = template_role or parent.template_role
    else:
        lineage = lineage_id or f"lin-{document.id}"
        document.version = _next_lineage_version(session, lineage)
        inherited_role = template_role
    document.lineage_id = lineage
    document.template_role = inherited_role
    members = session.exec(
        select(SourceDocument).where(SourceDocument.lineage_id == lineage)
    ).all()
    for member in members:
        if member.id != document.id and member.is_current:
            member.is_current = False
            session.add(member)
        if inherited_role is not None and member.template_role != inherited_role:
            member.template_role = inherited_role
            session.add(member)
    document.is_current = True
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _next_lineage_version(session: Session, lineage_id: str) -> int:
    versions = session.exec(
        select(SourceDocument.version).where(SourceDocument.lineage_id == lineage_id)
    ).all()
    return (max(versions) + 1) if versions else 1


def active_template_document(
    session: Session, *, role: str = "cv_style"
) -> SourceDocument | None:
    stmt = (
        select(SourceDocument)
        .where(
            SourceDocument.template_role == role,
            SourceDocument.is_current == True,  # noqa: E712 - SQLModel column comparison
        )
        .order_by(SourceDocument.updated_at.desc())  # type: ignore[union-attr]
    )
    return session.exec(stmt).first()


def read_source_text(document: SourceDocument | None) -> str | None:
    """Return a document's text, preferring the original file then processed text."""
    if document is None:
        return None
    path = Path(document.original_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    if document.processed_path and Path(document.processed_path).exists():
        return Path(document.processed_path).read_text(encoding="utf-8")
    return None


def active_cv_template_text(session: Session) -> str | None:
    """Return the active CV template text, or None if none is promoted."""
    return read_source_text(active_template_document(session, role="cv_style"))


def set_active_template(
    session: Session, document_id: int, *, role: str = "cv_style"
) -> SourceDocument:
    """Promote a document's lineage to own ``role``; clear it from other lineages."""
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise ValueError("source document not found")
    lineage = document.lineage_id or f"lin-{document.id}"
    if document.lineage_id != lineage:
        document.lineage_id = lineage
    others = session.exec(
        select(SourceDocument).where(SourceDocument.template_role == role)
    ).all()
    for other in others:
        if (other.lineage_id or f"lin-{other.id}") != lineage:
            other.template_role = None
            session.add(other)
    members = session.exec(
        select(SourceDocument).where(SourceDocument.lineage_id == lineage)
    ).all()
    has_current = any(member.is_current for member in members if member.id != document.id)
    for member in members:
        member.template_role = role
        session.add(member)
    if not has_current:
        for member in members:
            member.is_current = member.id == document.id
            session.add(member)
    session.add(document)
    session.commit()
    session.refresh(document)
    log_action_safe(
        session,
        actor=ActorType.human,
        action="knowledge_template_promoted",
        entity_type="source_document",
        entity_id=document.id,
        detail={"role": role, "lineage_id": lineage},
    )
    return document


def activate_version(session: Session, document_id: int) -> SourceDocument:
    """Make ``document_id`` the current head of its lineage (version rollback)."""
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise ValueError("source document not found")
    lineage = document.lineage_id or f"lin-{document.id}"
    members = session.exec(
        select(SourceDocument).where(SourceDocument.lineage_id == lineage)
    ).all()
    for member in members:
        target = member.id == document.id
        if member.is_current != target:
            member.is_current = target
            session.add(member)
    if not members:
        document.is_current = True
        session.add(document)
    session.commit()
    session.refresh(document)
    log_action_safe(
        session,
        actor=ActorType.human,
        action="knowledge_version_activated",
        entity_type="source_document",
        entity_id=document.id,
        detail={"lineage_id": lineage, "version": document.version},
    )
    return document


_DIFF_CONTEXT = 3
_DIFF_MAX_LINES = 1200


def _collapse_equal(lines: list[str], *, head: bool, tail: bool) -> list[dict[str, str]]:
    """Emit context lines, collapsing long unchanged runs to keep the diff scannable."""
    if len(lines) <= _DIFF_CONTEXT * 2 + 1:
        return [{"op": "context", "text": line} for line in lines]
    out: list[dict[str, str]] = []
    lead = lines[-_DIFF_CONTEXT:] if head else lines[:_DIFF_CONTEXT]
    if not head:
        out.extend({"op": "context", "text": line} for line in lines[:_DIFF_CONTEXT])
        hidden = len(lines) - (_DIFF_CONTEXT if tail else _DIFF_CONTEXT * 2)
        out.append({"op": "gap", "text": f"@@ {hidden} unchanged lines @@"})
        if not tail:
            out.extend({"op": "context", "text": line} for line in lines[-_DIFF_CONTEXT:])
        return out
    # Leading equal block before the first change: show only the trailing context.
    out.append({"op": "gap", "text": f"@@ {len(lines) - _DIFF_CONTEXT} unchanged lines @@"})
    out.extend({"op": "context", "text": line} for line in lead)
    return out


def diff_source_versions(
    session: Session, base_id: int, target_id: int
) -> dict[str, object]:
    """Compute a line-level diff between two versions of the same lineage.

    ``base_id`` is the older side; ``target_id`` is the newer side. Removed lines
    come from base, added lines from target.
    """
    base = session.get(SourceDocument, base_id)
    target = session.get(SourceDocument, target_id)
    if base is None or target is None:
        raise ValueError("source document not found")
    base_lineage = base.lineage_id or f"lin-{base.id}"
    target_lineage = target.lineage_id or f"lin-{target.id}"
    if base_lineage != target_lineage:
        raise ValueError("versions are not in the same lineage")

    base_lines = (read_source_text(base) or "").splitlines()
    target_lines = (read_source_text(target) or "").splitlines()
    matcher = difflib.SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    lines: list[dict[str, str]] = []
    added = removed = 0
    for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            lines.extend(
                _collapse_equal(
                    base_lines[i1:i2],
                    head=index == 0,
                    tail=index == len(opcodes) - 1,
                )
            )
        else:
            for line in base_lines[i1:i2]:
                lines.append({"op": "remove", "text": line})
                removed += 1
            for line in target_lines[j1:j2]:
                lines.append({"op": "add", "text": line})
                added += 1
        if len(lines) > _DIFF_MAX_LINES:
            lines = lines[:_DIFF_MAX_LINES]
            lines.append({"op": "gap", "text": "@@ diff truncated @@"})
            break

    return {
        "base_id": base.id,
        "base_version": base.version,
        "target_id": target.id,
        "target_version": target.version,
        "added": added,
        "removed": removed,
        "lines": lines,
    }


_DIFF_SUMMARY_SYSTEM = (
    "You compare two versions of a candidate's career document (CV, cover letter, "
    "or notes). Summarize only the substantive differences in plain English for the "
    "document owner. Be concise and specific. Ignore pure whitespace/formatting noise. "
    'Respond as strict JSON: {"summary": "<2-4 short sentences or bullet-style clauses>"}.'
)


def summarize_version_diff(
    session: Session,
    base_id: int,
    target_id: int,
    *,
    client: object | None = None,
    settings: Settings | None = None,
) -> str:
    """Plain-English summary of the main changes between two versions (on-demand LLM)."""
    settings = settings or get_settings()
    result = diff_source_versions(session, base_id, target_id)
    changed = "\n".join(
        ("+ " if line["op"] == "add" else "- ") + line["text"]
        for line in result["lines"]  # type: ignore[union-attr]
        if line["op"] in ("add", "remove")
    ).strip()
    if not changed:
        return "No textual differences between these versions."
    prompt = (
        f"Version {result['base_version']} -> version {result['target_version']}.\n"
        f"Changed lines (+ added, - removed), truncated:\n\n{changed[:6000]}"
    )
    if client is None:
        from ..materials.generator import _build_client

        client = _build_client(settings, session=session, entity_id=base_id)
    parsed = client.generate(  # type: ignore[attr-defined]
        _DIFF_SUMMARY_SYSTEM,
        prompt,
        settings.scoring_model,
        operation_name="summarize_version_diff",
    )
    summary = str(parsed.get("summary", "")).strip() if isinstance(parsed, dict) else ""
    return summary or "No summary produced."


def _derive_summary(session: Session, document: SourceDocument, text: str) -> str:
    """Cheap, deterministic summary from top claims + leading prose (no LLM)."""
    claims = session.exec(
        select(EvidenceClaim)
        .where(EvidenceClaim.source_document_id == document.id)
        .order_by(EvidenceClaim.confidence.desc())  # type: ignore[union-attr]
        .limit(3)
    ).all()
    if claims:
        categories = sorted({claim.category for claim in claims})
        lead = claims[0].claim_text.strip()
        prefix = f"[{', '.join(categories)}] " if categories else ""
        return _truncate(f"{prefix}{lead}", 280)
    snippet = " ".join(text.split())
    return _truncate(snippet, 280) if snippet else ""


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "\u2026"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_original(source_path: Path, digest: str, paths: KnowledgePaths) -> Path:
    dest = paths.originals / f"{digest}{source_path.suffix.lower()}"
    shutil.copy2(source_path, dest)
    return dest


def _mark_document_failed(session: Session, document: SourceDocument, exc: Exception) -> None:
    # EA-02: the ingest pipeline commits chunks/claims/entities incrementally, so
    # a failure partway through (e.g. an embedding or extraction error on a later
    # chunk) leaves committed partial derivatives under a "failed" parent. Roll
    # them back so a failed document is an all-or-nothing unit — no orphan chunks
    # or half-extracted claims survive. The retry path reprocesses cleanly.
    session.rollback()
    _clear_document_derivatives(session, document)
    document.status = SourceDocumentStatus.failed
    document.error = str(exc)
    document.updated_at = datetime.now(UTC)
    session.add(document)
    session.commit()
    log_action_safe(
        session,
        actor=ActorType.system,
        action="knowledge_source_failed",
        entity_type="source_document",
        entity_id=document.id,
        detail={"error": str(exc)},
    )


def _clear_document_derivatives(session: Session, document: SourceDocument) -> None:
    if document.id is None:
        return
    entity_rows = session.exec(
        select(KnowledgeEntity).where(KnowledgeEntity.source_document_id == document.id)
    ).all()
    entity_ids = [entity.id for entity in entity_rows if entity.id is not None]
    if entity_ids:
        relationships = session.exec(
            select(KnowledgeRelationship).where(
                (KnowledgeRelationship.source_entity_id.in_(entity_ids))  # type: ignore[attr-defined]
                | (KnowledgeRelationship.target_entity_id.in_(entity_ids))  # type: ignore[attr-defined]
            )
        ).all()
        for relationship in relationships:
            session.delete(relationship)
    for claim in session.exec(
        select(EvidenceClaim).where(EvidenceClaim.source_document_id == document.id)
    ).all():
        for facet in session.exec(select(ClaimFacet).where(ClaimFacet.claim_id == claim.id)):
            session.delete(facet)
        session.delete(claim)
    for chunk in session.exec(
        select(SourceChunk).where(SourceChunk.source_document_id == document.id)
    ).all():
        session.delete(chunk)
    for entity in entity_rows:
        session.delete(entity)
    session.commit()


def _normalize_for_span(text: str) -> str:
    """Lowercase + collapse whitespace for span-vs-source containment checks."""
    return " ".join(text.lower().split())


def _claim_number_tokens(text: str) -> set[str]:
    """Numeric tokens with grouping commas folded, so "1,200" matches "1200"."""
    from ..materials.generator import _num_tokens

    return {tok.replace(",", "") for tok in _num_tokens(text)}


def _claim_entity_tokens(text: str) -> set[str]:
    from ..materials.generator import _GENERIC_ACRONYMS, _entity_tokens

    return _entity_tokens(text) - {a.lower() for a in _GENERIC_ACRONYMS}


def claim_span_distortions(claim_text: str, source_span: str | None) -> list[str]:
    """Numbers/entities the claim asserts that its cited span does not contain (TP-02b).

    TP-02 (``span_supported_by_source``) proves the span exists in the source —
    but not that the *claim* matches the *span*. A correct-span, wrong-claim
    distortion ("Increased revenue by 40%" citing a span that says 30%) passed
    the span check untouched. This is a containment check of the claim's hard
    facts against the span it cites: every numeric token (grouping commas
    folded) and named-entity token (CamelCase names, 3+-char acronyms; the
    generic business acronyms are exempt) in the claim must appear in the span.
    Returns the offending tokens; empty list == consistent. Claims without a
    span return no distortions — they already never auto-verify.
    """
    if not source_span or not source_span.strip():
        return []
    bad_numbers = sorted(_claim_number_tokens(claim_text) - _claim_number_tokens(source_span))
    bad_entities = sorted(_claim_entity_tokens(claim_text) - _claim_entity_tokens(source_span))
    return bad_numbers + bad_entities


def span_supported_by_source(source_span: str | None, chunk_text: str) -> bool:
    """True iff ``source_span`` actually occurs (verbatim) in the chunk text.

    Auto-verification (TP-02) must not trust a model-asserted ``source_span``
    on its own: ``bool(source_span)`` only proves the model emitted *a* string,
    not that the string is grounded in the source. A confident hallucination
    ("increased revenue 40%") would otherwise auto-verify even when "40%" never
    appears in the document. We require the span to be a normalized substring of
    the chunk it was extracted from; anything else stays ``draft`` for human
    review rather than being trusted as evidence.
    """
    if not source_span or not source_span.strip():
        return False
    return _normalize_for_span(source_span) in _normalize_for_span(chunk_text)


def _store_extraction(
    session: Session,
    document: SourceDocument,
    chunk: SourceChunk,
    result: ExtractionResult,
    entity_by_name: dict[str, KnowledgeEntity],
    *,
    threshold: float,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    sources = {document.id: document} if document.id is not None else {}
    for claim in result.claims:
        span_ok = span_supported_by_source(claim.source_span, chunk.text)
        # TP-02b: a span that exists in the source is not enough — the claim's
        # own numbers/entities must match the span it cites, or the claim stays
        # draft for human review (correct-span, wrong-claim distortion).
        distortions = claim_span_distortions(claim.claim_text, claim.source_span)
        state = (
            ClaimVerificationState.verified
            if claim.confidence >= threshold and span_ok and not distortions
            else ClaimVerificationState.draft
        )
        if claim.source_span:
            span_matches = find_claims_by_normalized_span(session, claim.source_span)
            if span_matches:
                canonical = pick_canonical_claim(span_matches, sources)
                ensure_claim_document_link(
                    session,
                    claim_id=canonical.id,
                    source_document_id=document.id or 0,
                    source_chunk_id=chunk.id,
                    source_span=claim.source_span,
                )
                session.commit()
                claims.append(canonical)
                continue

        claim_id = _claim_id(document.content_hash, chunk.chunk_index, claim.claim_text)
        row = EvidenceClaim(
            id=claim_id,
            source_document_id=document.id or 0,
            source_chunk_id=chunk.id,
            claim_text=claim.claim_text,
            category=claim.category,
            confidence=claim.confidence,
            verification_state=state,
            source_span=claim.source_span,
            tags=claim.tags,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        if span_ok and distortions:
            log_action_safe(
                session,
                actor=ActorType.system,
                action="knowledge_claim_distortion_flagged",
                entity_type="evidence_claim",
                entity_id=row.id,
                detail={"distortions": distortions, "source_span": claim.source_span},
            )
        ensure_claim_document_link(
            session,
            claim_id=row.id,
            source_document_id=document.id or 0,
            source_chunk_id=chunk.id,
            source_span=claim.source_span,
        )
        session.commit()
        claims.append(row)
        if row.verification_state == ClaimVerificationState.verified:
            log_action_safe(
                session,
                actor=ActorType.agent,
                action="knowledge_claim_auto_verified",
                entity_type="evidence_claim",
                entity_id=row.id,
                detail={"confidence": row.confidence},
            )

    for entity in result.entities:
        normalized = normalize_name(entity.name)
        existing = entity_by_name.get(normalized) or session.exec(
            select(KnowledgeEntity).where(
                KnowledgeEntity.normalized_name == normalized,
                KnowledgeEntity.entity_type == entity.entity_type,
            )
        ).first()
        if existing is None:
            # EVAL-05: no exact match — bind alias variants ("Acme Inc" when
            # "Acme" already exists) to the canonical node instead of
            # fragmenting the graph one surface form at a time.
            existing = find_entity_alias(session, entity.name, entity.entity_type)
            if existing is not None:
                record_alias(session, existing, entity.name)
                session.commit()
        if existing is None:
            existing = KnowledgeEntity(
                name=entity.name,
                normalized_name=normalized,
                entity_type=entity.entity_type,
                source_document_id=document.id,
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
            if document.id is not None and existing.id is not None:
                ensure_entity_document_link(
                    session,
                    entity_id=existing.id,
                    source_document_id=document.id,
                )
                session.commit()
        elif document.id is not None and existing.id is not None:
            ensure_entity_document_link(
                session,
                entity_id=existing.id,
                source_document_id=document.id,
            )
            session.commit()
        entity_by_name[normalized] = existing

    for relationship in result.relationships:
        source = entity_by_name.get(normalize_name(relationship.source))
        target = entity_by_name.get(normalize_name(relationship.target))
        row = KnowledgeRelationship(
            source_entity_id=source.id if source else None,
            target_entity_id=target.id if target else None,
            relationship_type=relationship.relationship_type,
            confidence=relationship.confidence,
        )
        session.add(row)
    session.commit()
    return claims


def normalize_name(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _claim_id(content_hash: str, chunk_index: int, claim_text: str) -> str:
    digest = hashlib.sha1(f"{content_hash}:{chunk_index}:{claim_text}".encode()).hexdigest()
    return f"claim-{digest[:16]}"
