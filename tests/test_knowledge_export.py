"""Tests for knowledge bank JSON / GraphML export."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from zengrowth.knowledge.export import (
    build_bank_dump,
    build_entity_graphml,
    export_knowledge_bank,
)
from zengrowth.models import (
    ClaimVerificationState,
    EvidenceClaim,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceDocument,
    SourceDocumentStatus,
    SourceDocumentType,
)


def _seed_minimal_bank(session: Session) -> None:
    doc = SourceDocument(
        filename="project.md",
        original_path="data/knowledge/originals/project.md",
        processed_path="data/knowledge/processed/project.md",
        content_hash="abc123",
        source_type=SourceDocumentType.project,
        status=SourceDocumentStatus.extracted,
        title="GraphRAG agent",
        summary="Built an investment agent.",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    assert doc.id is not None

    claim = EvidenceClaim(
        id="claim-1",
        source_document_id=doc.id,
        claim_text="Led a GraphRAG investment agent project.",
        category="technical",
        confidence=0.9,
        verification_state=ClaimVerificationState.verified,
    )
    session.add(claim)
    project = KnowledgeEntity(
        name="GraphRAG agent",
        normalized_name="graphrag agent",
        entity_type="project",
        source_document_id=doc.id,
        source_claim_id="claim-1",
    )
    tool = KnowledgeEntity(
        name="Neo4j",
        normalized_name="neo4j",
        entity_type="tool",
        source_document_id=doc.id,
        source_claim_id="claim-1",
    )
    session.add(project)
    session.add(tool)
    session.commit()
    session.refresh(project)
    session.refresh(tool)
    assert project.id is not None and tool.id is not None

    session.add(
        KnowledgeRelationship(
            source_entity_id=project.id,
            target_entity_id=tool.id,
            source_claim_id="claim-1",
            relationship_type="USED",
            confidence=0.9,
        )
    )
    session.commit()


def test_build_bank_dump_includes_entities_and_relationships(session: Session):
    _seed_minimal_bank(session)
    dump = build_bank_dump(session, include_chunks=False)

    assert dump["format"] == "zengrowth.knowledge.bank"
    assert dump["counts"]["sources"] == 1
    assert dump["counts"]["claims"] == 1
    assert dump["counts"]["entities"] == 2
    assert dump["counts"]["relationships"] == 1
    assert dump["sources"][0]["title"] == "GraphRAG agent"
    assert dump["relationships"][0]["relationship_type"] == "USED"
    assert dump["chunks"] == []


def test_export_writes_json_and_graphml(session: Session, tmp_path: Path):
    _seed_minimal_bank(session)
    out = tmp_path / "export"
    manifest = export_knowledge_bank(session, out, formats={"all"})

    assert (out / "bank.json").is_file()
    assert (out / "graph.json").is_file()
    assert (out / "entity_graph.graphml").is_file()
    assert (out / "projection.graphml").is_file()
    assert (out / "manifest.json").is_file()
    assert "bank.json" in manifest["files"]
    assert manifest["counts"]["entities"] == 2

    graphml = (out / "entity_graph.graphml").read_text(encoding="utf-8")
    assert 'edgedefault="directed"' in graphml
    assert "USED" in graphml
    assert "entity:" in graphml


def test_entity_graphml_skips_dangling_edges(session: Session):
    _seed_minimal_bank(session)
    # Orphan relationship pointing at missing entities should be omitted.
    session.add(
        KnowledgeRelationship(
            source_entity_id=9999,
            target_entity_id=9998,
            relationship_type="RELATED_TO",
            confidence=0.1,
        )
    )
    session.commit()

    root = build_entity_graphml(session)
    edges = list(root.iter("edge"))
    assert len(edges) == 1
    rel_types = [data.text for edge in edges for data in edge if data.get("key") == "d_rel_type"]
    assert rel_types == ["USED"]
