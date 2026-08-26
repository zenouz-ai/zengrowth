"""EVAL-05 — alias/fuzzy entity resolution unit tests.

The pairwise-F1 eval gate lives in ``tests/eval/test_entity_resolution.py``;
these tests pin the matching rules and the DB merge/ingest behaviour.
"""

from __future__ import annotations

from sqlmodel import Session, select

from zengrowth.knowledge.dedup import deduplicate_knowledge
from zengrowth.knowledge.entity_resolution import (
    alias_key,
    cluster_entity_names,
    find_entity_alias,
    names_match,
    record_alias,
    resolve_entity_aliases,
)
from zengrowth.models import (
    EntityDocumentLink,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceDocument,
)


def test_alias_key_folds_case_punctuation_and_legal_suffixes() -> None:
    assert alias_key("Acme Inc.") == "acme"
    assert alias_key("ACME CORP") == "acme"
    assert alias_key("Acme Incorporated") == "acme"
    assert alias_key("Novartis AG") == "novartis"
    assert alias_key("scikit-learn") == "scikit learn"
    # Descriptive tails are not legal suffixes and must survive.
    assert alias_key("Acme Health Ltd") == "acme health"
    # A name that is nothing but suffix tokens keeps its tokens.
    assert alias_key("Company") == "company"


def test_names_match_positive_variants() -> None:
    assert names_match("Acme", "Acme Inc")
    assert names_match("Kubernetes", "Kubernets")  # typo, fuzzy
    assert names_match("PostgreSQL", "Postgres")  # single-token prefix alias
    assert names_match("Py-Torch", "pytorch")


def test_names_match_hard_negatives() -> None:
    assert not names_match("Acme", "Acme Health")
    assert not names_match("Google", "Google DeepMind")
    assert not names_match("Meta", "Metabase")
    assert not names_match("Java", "JavaScript")
    assert not names_match("AWS", "AWS Lambda")
    # Short names never fuzzy-match: one typo away is a different entity.
    assert not names_match("Acme", "Acne")


def test_cluster_entity_names_never_crosses_entity_type() -> None:
    clusters = cluster_entity_names(
        [("a", "Python", "skill"), ("b", "Python", "tool")]
    )
    assert {frozenset(c) for c in clusters} == {frozenset({"a"}), frozenset({"b"})}


def _make_doc(session: Session, name: str) -> SourceDocument:
    doc = SourceDocument(
        filename=f"{name}.md",
        original_path=f"data/knowledge/originals/{name}.md",
        content_hash=f"hash-{name}",
        source_type="note",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_resolve_entity_aliases_merges_variants_and_preserves_links(session: Session) -> None:
    doc_a = _make_doc(session, "cv")
    doc_b = _make_doc(session, "project")
    canonical = KnowledgeEntity(name="Acme", normalized_name="acme", entity_type="employer")
    variant = KnowledgeEntity(
        name="Acme Inc", normalized_name="acme inc", entity_type="employer"
    )
    other = KnowledgeEntity(
        name="Acme Health", normalized_name="acme health", entity_type="employer"
    )
    session.add_all([canonical, variant, other])
    session.commit()
    for entity, doc in ((canonical, doc_a), (variant, doc_b)):
        session.refresh(entity)
        session.add(
            EntityDocumentLink(entity_id=entity.id, source_document_id=doc.id)
        )
    session.add(
        KnowledgeRelationship(
            source_entity_id=variant.id,
            target_entity_id=other.id,
            relationship_type="RELATED_TO",
            confidence=0.9,
        )
    )
    session.commit()

    report = resolve_entity_aliases(session)

    assert report.entities_merged == 1
    assert report.merges == {"Acme": ["Acme Inc"]}
    remaining = session.exec(select(KnowledgeEntity)).all()
    assert {e.name for e in remaining} == {"Acme", "Acme Health"}
    kept = next(e for e in remaining if e.name == "Acme")
    assert kept.meta["aliases"] == ["Acme Inc"]
    # Provenance from both documents lands on the canonical node.
    links = session.exec(
        select(EntityDocumentLink).where(EntityDocumentLink.entity_id == kept.id)
    ).all()
    assert {link.source_document_id for link in links} == {doc_a.id, doc_b.id}
    # The relationship follows the merge.
    rel = session.exec(select(KnowledgeRelationship)).one()
    assert rel.source_entity_id == kept.id


def test_deduplicate_knowledge_reports_alias_merges(session: Session) -> None:
    session.add_all(
        [
            KnowledgeEntity(name="Novartis", normalized_name="novartis", entity_type="employer"),
            KnowledgeEntity(
                name="Novartis AG", normalized_name="novartis ag", entity_type="employer"
            ),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)

    assert report.entities_alias_merged == 1
    assert [e.name for e in session.exec(select(KnowledgeEntity)).all()] == ["Novartis"]


def test_find_entity_alias_matches_variant_and_records_alias(session: Session) -> None:
    entity = KnowledgeEntity(name="Acme", normalized_name="acme", entity_type="employer")
    session.add(entity)
    session.commit()
    session.refresh(entity)

    assert find_entity_alias(session, "Acme Corporation", "employer") is not None
    # entity_type scopes identity.
    assert find_entity_alias(session, "Acme Corporation", "project") is None

    record_alias(session, entity, "Acme Corporation")
    record_alias(session, entity, "Acme Corporation")  # idempotent
    record_alias(session, entity, "Acme")  # own name is never an alias
    session.commit()
    session.refresh(entity)
    assert entity.meta["aliases"] == ["Acme Corporation"]
