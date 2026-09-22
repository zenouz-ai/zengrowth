from __future__ import annotations

from sqlmodel import Session, select

from zengrowth.knowledge.dedup import deduplicate_knowledge
from zengrowth.models import (
    ClaimDocumentLink,
    ClaimVerificationState,
    EntityDocumentLink,
    EvidenceClaim,
    GeneratedMaterial,
    Job,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceDocument,
)


def test_deduplicate_claims_same_document_substring(session: Session) -> None:
    doc = SourceDocument(
        filename="cv.md",
        original_path="data/knowledge/originals/a.md",
        content_hash="hash-a",
        source_type="cv",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    session.add_all(
        [
            EvidenceClaim(
                id="c-long",
                source_document_id=doc.id,
                claim_text="Jordan Avery holds a PhD in Mathematics.",
                category="education",
                confidence=0.95,
                verification_state=ClaimVerificationState.verified,
                source_span="PhD in Mathematics",
            ),
            EvidenceClaim(
                id="c-short",
                source_document_id=doc.id,
                claim_text="Holds a PhD in Mathematics.",
                category="education",
                confidence=0.95,
                verification_state=ClaimVerificationState.verified,
                source_span="PhD in Mathematics",
            ),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)

    remaining = {c.id for c in session.exec(select(EvidenceClaim)).all()}
    assert report.claims_removed == 1
    assert "c-long" in remaining
    assert "c-short" not in remaining
    links = session.exec(select(ClaimDocumentLink).where(ClaimDocumentLink.claim_id == "c-long")).all()
    assert len(links) == 1
    assert links[0].source_document_id == doc.id


def test_deduplicate_cross_document_claim_preserves_provenance(session: Session) -> None:
    cv = SourceDocument(
        filename="cv.md",
        original_path="data/knowledge/originals/cv.md",
        content_hash="hash-cv",
        source_type="cv",
        is_current=True,
    )
    project = SourceDocument(
        filename="project-zengrowth.md",
        original_path="data/knowledge/originals/project-zengrowth.md",
        content_hash="hash-proj",
        source_type="project",
    )
    session.add_all([cv, project])
    session.commit()
    session.refresh(cv)
    session.refresh(project)
    session.add_all(
        [
            EvidenceClaim(
                id="claim-cv",
                source_document_id=cv.id,
                claim_text="Built ZenGrowth, a personal career operating system.",
                category="experience",
                confidence=0.95,
                verification_state=ClaimVerificationState.verified,
                source_span="Built ZenGrowth",
            ),
            EvidenceClaim(
                id="claim-proj",
                source_document_id=project.id,
                claim_text="ZenGrowth is a personal career operating system.",
                category="experience",
                confidence=0.9,
                verification_state=ClaimVerificationState.verified,
                source_span="Built ZenGrowth",
            ),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)

    claims = list(session.exec(select(EvidenceClaim)).all())
    assert len(claims) == 1
    assert report.claims_removed == 1
    canonical_id = claims[0].id
    linked_docs = {
        link.source_document_id
        for link in session.exec(select(ClaimDocumentLink).where(ClaimDocumentLink.claim_id == canonical_id))
    }
    assert linked_docs == {cv.id, project.id}


def test_deduplicate_remaps_material_evidence_ids(session: Session) -> None:
    doc = SourceDocument(
        filename="cv.md",
        original_path="data/knowledge/originals/a.md",
        content_hash="hash-a",
        source_type="cv",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    session.add_all(
        [
            EvidenceClaim(
                id="keep-claim",
                source_document_id=doc.id,
                claim_text="Long canonical claim about Python and FastAPI.",
                category="skill",
                confidence=0.95,
                verification_state=ClaimVerificationState.verified,
                source_span="Python and FastAPI",
            ),
            EvidenceClaim(
                id="drop-claim",
                source_document_id=doc.id,
                claim_text="Python and FastAPI",
                category="skill",
                confidence=0.95,
                verification_state=ClaimVerificationState.verified,
                source_span="Python and FastAPI",
            ),
        ]
    )
    session.commit()
    job = Job(company="Acme", title="Role", source="manual", dedup_hash="dedup-test")
    session.add(job)
    session.commit()
    session.refresh(job)
    material = GeneratedMaterial(
        job_id=job.id or 0,
        material_type="answer",
        title="Test",
        status="created_markdown",
        evidence_ids=["keep-claim", "drop-claim"],
    )
    session.add(material)
    session.commit()

    report = deduplicate_knowledge(session)

    session.refresh(material)
    assert report.materials_rewritten == 1
    assert material.evidence_ids == ["keep-claim"]


def test_deduplicate_entities_merges_document_links(session: Session) -> None:
    cv = SourceDocument(
        filename="cv.md",
        original_path="data/knowledge/originals/cv.md",
        content_hash="hash-cv",
        source_type="cv",
    )
    project = SourceDocument(
        filename="project.md",
        original_path="data/knowledge/originals/project.md",
        content_hash="hash-proj",
        source_type="project",
    )
    session.add_all([cv, project])
    session.commit()
    session.refresh(cv)
    session.refresh(project)
    keep = KnowledgeEntity(
        name="Python",
        normalized_name="python",
        entity_type="tool",
        source_document_id=cv.id,
    )
    dupe = KnowledgeEntity(
        name="Python",
        normalized_name="python",
        entity_type="tool",
        source_document_id=project.id,
    )
    session.add_all([keep, dupe])
    session.commit()
    session.refresh(keep)
    session.refresh(dupe)
    session.add_all(
        [
            EntityDocumentLink(entity_id=keep.id or 0, source_document_id=cv.id),
            EntityDocumentLink(entity_id=dupe.id or 0, source_document_id=project.id),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)

    entities = list(session.exec(select(KnowledgeEntity)))
    assert len(entities) == 1
    assert report.entities_removed == 1
    canonical = entities[0]
    linked_docs = {
        link.source_document_id
        for link in session.exec(
            select(EntityDocumentLink).where(EntityDocumentLink.entity_id == canonical.id)
        )
    }
    assert linked_docs == {cv.id, project.id}


def test_deduplicate_relationships(session: Session) -> None:
    a = KnowledgeEntity(name="Python", normalized_name="python", entity_type="tool")
    b = KnowledgeEntity(name="FastAPI", normalized_name="fastapi", entity_type="tool")
    session.add_all([a, b])
    session.commit()
    session.refresh(a)
    session.refresh(b)
    session.add_all(
        [
            KnowledgeRelationship(
                source_entity_id=a.id,
                target_entity_id=b.id,
                relationship_type="USED",
                confidence=0.9,
            ),
            KnowledgeRelationship(
                source_entity_id=a.id,
                target_entity_id=b.id,
                relationship_type="USED",
                confidence=0.8,
            ),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)

    rels = list(session.exec(select(KnowledgeRelationship)).all())
    assert report.relationships_removed == 1
    assert len(rels) == 1
