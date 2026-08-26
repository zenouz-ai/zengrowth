"""Build a knowledge graph projection from the local SQLite store.

This intentionally avoids any Neo4j dependency: it aggregates the canonical
``SourceDocument`` / ``EvidenceClaim`` / ``KnowledgeEntity`` rows we already
persist into a ``{nodes, edges}`` shape the frontend can render with React Flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from ..models import (
    ClaimDocumentLink,
    EntityDocumentLink,
    EvidenceClaim,
    GeneratedMaterial,
    KnowledgeEntity,
    SourceChunk,
    SourceDocument,
)


@dataclass
class GraphNode:
    id: str
    kind: str
    label: str
    detail: str | None = None
    group: str | None = None
    ref_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    kind: str


@dataclass
class KnowledgeGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def _source_node_id(source_id: int) -> str:
    return f"source:{source_id}"


def _claim_node_id(claim_id: str) -> str:
    return f"claim:{claim_id}"


def _entity_node_id(entity_id: int) -> str:
    return f"entity:{entity_id}"


def _chunk_node_id(chunk_id: int) -> str:
    return f"chunk:{chunk_id}"


def _material_node_id(material_id: int) -> str:
    return f"material:{material_id}"


def build_local_graph(
    session: Session,
    *,
    include_claims: bool = False,
    include_entities: bool = False,
    include_lineage: bool = False,
) -> KnowledgeGraph:
    sources = list(session.exec(select(SourceDocument)))
    claims = list(session.exec(select(EvidenceClaim)))
    entities = list(session.exec(select(KnowledgeEntity)))
    claim_links = list(session.exec(select(ClaimDocumentLink)))
    entity_links = list(session.exec(select(EntityDocumentLink)))
    claims_by_id = {claim.id: claim for claim in claims}
    entities_by_id = {entity.id: entity for entity in entities if entity.id is not None}

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    source_ids = {src.id for src in sources if src.id is not None}
    for src in sources:
        if src.id is None:
            continue
        nodes.append(
            GraphNode(
                id=_source_node_id(src.id),
                kind="source",
                label=src.title or src.filename,
                detail=src.summary,
                group=src.source_type.value,
                ref_id=str(src.id),
                meta={
                    "status": src.status.value,
                    "version": src.version,
                    "is_current": src.is_current,
                    "template_role": src.template_role,
                    "lineage_id": src.lineage_id,
                    "filename": src.filename,
                },
            )
        )

    # Version-in-time edges (newer supersedes older).
    for src in sources:
        if src.id is None or src.supersedes_id is None:
            continue
        if src.supersedes_id in source_ids:
            edges.append(
                GraphEdge(
                    id=f"sup:{src.id}",
                    source=_source_node_id(src.id),
                    target=_source_node_id(src.supersedes_id),
                    kind="supersedes",
                )
            )

    # Topic edges via shared entities / claim categories (one edge per pair).
    entities_by_source: dict[int, set[str]] = {}
    for link in entity_links:
        entity = entities_by_id.get(link.entity_id)
        if entity and link.source_document_id in source_ids:
            entities_by_source.setdefault(link.source_document_id, set()).add(entity.normalized_name)
    for entity in entities:
        if entity.source_document_id in source_ids:
            entities_by_source.setdefault(entity.source_document_id, set()).add(
                entity.normalized_name
            )
    categories_by_source: dict[int, set[str]] = {}
    for link in claim_links:
        claim = claims_by_id.get(link.claim_id)
        if claim and link.source_document_id in source_ids:
            categories_by_source.setdefault(link.source_document_id, set()).add(claim.category)
    for claim in claims:
        if claim.source_document_id in source_ids:
            categories_by_source.setdefault(claim.source_document_id, set()).add(
                claim.category
            )

    ordered = sorted(source_ids)
    seen_pairs: set[tuple[int, int]] = set()
    superseded_pairs = {
        tuple(sorted((src.id, src.supersedes_id)))  # type: ignore[arg-type]
        for src in sources
        if src.id is not None and src.supersedes_id in source_ids
    }
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            pair = (a, b)
            if pair in seen_pairs or pair in superseded_pairs:
                continue
            shared_entities = entities_by_source.get(a, set()) & entities_by_source.get(b, set())
            shared_categories = categories_by_source.get(a, set()) & categories_by_source.get(
                b, set()
            )
            if shared_entities or len(shared_categories) >= 2:
                seen_pairs.add(pair)
                edges.append(
                    GraphEdge(
                        id=f"rel:{a}:{b}",
                        source=_source_node_id(a),
                        target=_source_node_id(b),
                        kind="related_to",
                    )
                )

    if include_claims:
        seen_claim_nodes: set[str] = set()
        for claim in claims:
            if claim.id in seen_claim_nodes:
                continue
            seen_claim_nodes.add(claim.id)
            nodes.append(
                GraphNode(
                    id=_claim_node_id(claim.id),
                    kind="claim",
                    label=claim.claim_text,
                    detail=f"{claim.category} · {claim.verification_state.value}",
                    group=claim.category,
                    ref_id=claim.id,
                    meta={
                        "confidence": claim.confidence,
                        "verification_state": claim.verification_state.value,
                    },
                )
            )
        seen_has_claim: set[tuple[int, str]] = set()
        for link in claim_links:
            if link.source_document_id not in source_ids or link.claim_id not in claims_by_id:
                continue
            key = (link.source_document_id, link.claim_id)
            if key in seen_has_claim:
                continue
            seen_has_claim.add(key)
            edges.append(
                GraphEdge(
                    id=f"hasclaim:{link.source_document_id}:{link.claim_id}",
                    source=_source_node_id(link.source_document_id),
                    target=_claim_node_id(link.claim_id),
                    kind="has_claim",
                )
            )
        for claim in claims:
            key = (claim.source_document_id, claim.id)
            if key in seen_has_claim or claim.source_document_id not in source_ids:
                continue
            edges.append(
                GraphEdge(
                    id=f"hasclaim:{claim.id}",
                    source=_source_node_id(claim.source_document_id),
                    target=_claim_node_id(claim.id),
                    kind="has_claim",
                )
            )

    if include_entities:
        entity_docs: dict[int, set[int]] = {}
        for link in entity_links:
            entity_docs.setdefault(link.entity_id, set()).add(link.source_document_id)
        for entity in entities:
            if entity.id is None:
                continue
            nodes.append(
                GraphNode(
                    id=_entity_node_id(entity.id),
                    kind="entity",
                    label=entity.name,
                    detail=entity.entity_type,
                    group=entity.entity_type,
                    ref_id=str(entity.id),
                    meta={},
                )
            )
            linked_docs = entity_docs.get(entity.id, set())
            if entity.source_document_id is not None:
                linked_docs = linked_docs | {entity.source_document_id}
            if entity.source_claim_id and include_claims:
                edges.append(
                    GraphEdge(
                        id=f"mentions:{entity.id}:{entity.source_claim_id}",
                        source=_claim_node_id(entity.source_claim_id),
                        target=_entity_node_id(entity.id),
                        kind="mentions",
                    )
                )
            else:
                for doc_id in sorted(linked_docs):
                    if doc_id not in source_ids:
                        continue
                    edges.append(
                        GraphEdge(
                            id=f"mentions:{entity.id}:{doc_id}",
                            source=_source_node_id(doc_id),
                            target=_entity_node_id(entity.id),
                            kind="mentions",
                        )
                    )

    if include_lineage:
        chunks = list(session.exec(select(SourceChunk)))
        for chunk in chunks:
            if chunk.id is None or chunk.source_document_id not in source_ids:
                continue
            nodes.append(
                GraphNode(
                    id=_chunk_node_id(chunk.id),
                    kind="chunk",
                    label=f"Chunk {chunk.chunk_index}",
                    detail=chunk.section_path,
                    group="chunk",
                    ref_id=str(chunk.id),
                    meta={"token_estimate": chunk.token_estimate},
                )
            )
            edges.append(
                GraphEdge(
                    id=f"chunk:{chunk.id}",
                    source=_source_node_id(chunk.source_document_id),
                    target=_chunk_node_id(chunk.id),
                    kind="contains_chunk",
                )
            )
            if include_claims:
                for claim in claims:
                    if claim.source_chunk_id == chunk.id:
                        edges.append(
                            GraphEdge(
                                id=f"chunkclaim:{chunk.id}:{claim.id}",
                                source=_chunk_node_id(chunk.id),
                                target=_claim_node_id(claim.id),
                                kind="extracted_from",
                            )
                        )
        materials = list(session.exec(select(GeneratedMaterial)))
        for material in materials:
            if material.id is None:
                continue
            nodes.append(
                GraphNode(
                    id=_material_node_id(material.id),
                    kind="material",
                    label=material.title,
                    detail=material.material_type,
                    group=material.material_type,
                    ref_id=str(material.id),
                    meta={"job_id": material.job_id, "version": material.version},
                )
            )
            if material.evidence_ids:
                for eid in material.evidence_ids:
                    edges.append(
                        GraphEdge(
                            id=f"matclaim:{material.id}:{eid}",
                            source=_material_node_id(material.id),
                            target=_claim_node_id(eid),
                            kind="uses_evidence",
                        )
                    )

    return KnowledgeGraph(nodes=nodes, edges=edges)
