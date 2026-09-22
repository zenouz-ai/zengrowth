"""Provenance links between canonical facts/entities and the documents that cite them."""

from __future__ import annotations

import re

from sqlmodel import Session, select

from ..models import (
    ClaimDocumentLink,
    ClaimFacet,
    EntityDocumentLink,
    EvidenceClaim,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceDocument,
)


def norm_text(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def claim_rank_score(claim: EvidenceClaim, source: SourceDocument | None) -> float:
    score = claim.confidence * 10.0
    if claim.verification_state.value == "verified":
        score += 100.0
    if source and source.is_current:
        score += 50.0
    if source and source.template_role == "cv_style":
        score += 25.0
    score += len(claim.claim_text) * 0.01
    return score


def pick_canonical_claim(
    claims: list[EvidenceClaim],
    sources: dict[int, SourceDocument],
) -> EvidenceClaim:
    return max(claims, key=lambda c: claim_rank_score(c, sources.get(c.source_document_id)))


def ensure_claim_document_link(
    session: Session,
    *,
    claim_id: str,
    source_document_id: int,
    source_chunk_id: int | None = None,
    source_span: str | None = None,
) -> ClaimDocumentLink:
    existing = session.exec(
        select(ClaimDocumentLink).where(
            ClaimDocumentLink.claim_id == claim_id,
            ClaimDocumentLink.source_document_id == source_document_id,
        )
    ).first()
    if existing is not None:
        if source_chunk_id and existing.source_chunk_id is None:
            existing.source_chunk_id = source_chunk_id
        if source_span and not existing.source_span:
            existing.source_span = source_span
            session.add(existing)
        return existing
    row = ClaimDocumentLink(
        claim_id=claim_id,
        source_document_id=source_document_id,
        source_chunk_id=source_chunk_id,
        source_span=source_span,
    )
    session.add(row)
    return row


def ensure_entity_document_link(
    session: Session,
    *,
    entity_id: int,
    source_document_id: int,
) -> EntityDocumentLink:
    existing = session.exec(
        select(EntityDocumentLink).where(
            EntityDocumentLink.entity_id == entity_id,
            EntityDocumentLink.source_document_id == source_document_id,
        )
    ).first()
    if existing is not None:
        return existing
    row = EntityDocumentLink(
        entity_id=entity_id,
        source_document_id=source_document_id,
    )
    session.add(row)
    return row


def claim_document_ids(session: Session, claim_id: str) -> set[int]:
    return {
        link.source_document_id
        for link in session.exec(
            select(ClaimDocumentLink).where(ClaimDocumentLink.claim_id == claim_id)
        )
    }


def entity_document_ids(session: Session, entity_id: int) -> set[int]:
    return {
        link.source_document_id
        for link in session.exec(
            select(EntityDocumentLink).where(EntityDocumentLink.entity_id == entity_id)
        )
    }


def backfill_provenance_links(session: Session) -> tuple[int, int]:
    """Create link rows from legacy single-document foreign keys."""
    claim_links = 0
    for claim in session.exec(select(EvidenceClaim)):
        before = claim_document_ids(session, claim.id)
        ensure_claim_document_link(
            session,
            claim_id=claim.id,
            source_document_id=claim.source_document_id,
            source_chunk_id=claim.source_chunk_id,
            source_span=claim.source_span,
        )
        after = claim_document_ids(session, claim.id)
        if len(after) > len(before):
            claim_links += 1

    entity_links = 0
    for entity in session.exec(select(KnowledgeEntity)):
        if entity.id is None:
            continue
        doc_id = entity.source_document_id
        if doc_id is None:
            continue
        before = entity_document_ids(session, entity.id)
        ensure_entity_document_link(session, entity_id=entity.id, source_document_id=doc_id)
        after = entity_document_ids(session, entity.id)
        if len(after) > len(before):
            entity_links += 1

    session.commit()
    return claim_links, entity_links


def find_claims_by_normalized_span(session: Session, source_span: str) -> list[EvidenceClaim]:
    if not source_span or not source_span.strip():
        return []
    target = norm_text(source_span)
    return [
        claim
        for claim in session.exec(select(EvidenceClaim))
        if claim.source_span and norm_text(claim.source_span) == target
    ]


def redirect_claim_references(session: Session, removed_id: str, keep_id: str) -> None:
    """Point foreign keys and provenance links at the canonical claim."""
    for rel in session.exec(select(KnowledgeRelationship)):
        if rel.source_claim_id == removed_id:
            rel.source_claim_id = keep_id
            session.add(rel)
    for entity in session.exec(select(KnowledgeEntity)):
        if entity.source_claim_id == removed_id:
            entity.source_claim_id = keep_id
            session.add(entity)

    # KG-02: coverage facets follow the canonical claim so counts survive dedup.
    keep_facets = {
        (facet.facet, facet.value)
        for facet in session.exec(select(ClaimFacet).where(ClaimFacet.claim_id == keep_id))
    }
    for facet in session.exec(select(ClaimFacet).where(ClaimFacet.claim_id == removed_id)):
        if (facet.facet, facet.value) in keep_facets:
            session.delete(facet)
        else:
            keep_facets.add((facet.facet, facet.value))
            facet.claim_id = keep_id
            session.add(facet)

    removed_links = session.exec(
        select(ClaimDocumentLink).where(ClaimDocumentLink.claim_id == removed_id)
    ).all()
    for link in removed_links:
        ensure_claim_document_link(
            session,
            claim_id=keep_id,
            source_document_id=link.source_document_id,
            source_chunk_id=link.source_chunk_id,
            source_span=link.source_span,
        )
        session.delete(link)

    removed = session.get(EvidenceClaim, removed_id)
    if removed is not None:
        ensure_claim_document_link(
            session,
            claim_id=keep_id,
            source_document_id=removed.source_document_id,
            source_chunk_id=removed.source_chunk_id,
            source_span=removed.source_span,
        )


def merge_entity_document_links(session: Session, keep_id: int, dupe_id: int) -> None:
    for link in session.exec(
        select(EntityDocumentLink).where(EntityDocumentLink.entity_id == dupe_id)
    ):
        ensure_entity_document_link(
            session,
            entity_id=keep_id,
            source_document_id=link.source_document_id,
        )
        session.delete(link)
