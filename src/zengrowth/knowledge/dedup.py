"""Remove duplicate evidence claims, entities, and relationships from the knowledge store.

Cross-document duplicates are merged onto a canonical claim/entity while
``ClaimDocumentLink`` / ``EntityDocumentLink`` rows preserve which projects
still cite them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from ..models import (
    EvidenceClaim,
    GeneratedMaterial,
    KnowledgeEntity,
    KnowledgeRelationship,
    SourceDocument,
)
from .provenance import (
    backfill_provenance_links,
    merge_entity_document_links,
    norm_text,
    pick_canonical_claim,
    redirect_claim_references,
)


def _pick_claim(
    group: list[EvidenceClaim], sources: dict[int, SourceDocument]
) -> EvidenceClaim:
    return pick_canonical_claim(group, sources)


def _is_subsumed(shorter: str, longer: str) -> bool:
    a, b = norm_text(shorter), norm_text(longer)
    return a != b and a in b


@dataclass
class DedupReport:
    claims_removed: int = 0
    entities_removed: int = 0
    entities_alias_merged: int = 0
    relationships_removed: int = 0
    materials_rewritten: int = 0
    claim_links_backfilled: int = 0
    entity_links_backfilled: int = 0
    removed_claim_ids: list[str] = field(default_factory=list)
    claim_id_map: dict[str, str] = field(default_factory=dict)


def _rewrite_material_evidence(session: Session, id_map: dict[str, str]) -> int:
    if not id_map:
        return 0
    updated = 0
    for material in session.exec(select(GeneratedMaterial)):
        ids = material.evidence_ids or []
        if not ids:
            continue
        new_ids: list[str] = []
        seen: set[str] = set()
        for eid in ids:
            canonical = id_map.get(eid, eid)
            if canonical not in seen:
                seen.add(canonical)
                new_ids.append(canonical)
        if new_ids != ids:
            material.evidence_ids = new_ids or None
            session.add(material)
            updated += 1
    return updated


def _merge_claim(session: Session, removed: EvidenceClaim, keep: EvidenceClaim) -> None:
    redirect_claim_references(session, removed.id, keep.id)
    session.delete(removed)


def deduplicate_claims(session: Session) -> tuple[dict[str, str], int]:
    """Return removed→canonical claim id map and removal count."""
    claims = list(session.exec(select(EvidenceClaim)))
    sources = {s.id: s for s in session.exec(select(SourceDocument)) if s.id is not None}
    id_map: dict[str, str] = {}
    remove: set[str] = set()

    by_doc_text: dict[tuple[int, str], list[EvidenceClaim]] = {}
    for claim in claims:
        by_doc_text.setdefault((claim.source_document_id, norm_text(claim.claim_text)), []).append(claim)
    for group in by_doc_text.values():
        if len(group) < 2:
            continue
        keep = _pick_claim(group, sources)
        for claim in group:
            if claim.id != keep.id:
                remove.add(claim.id)
                id_map[claim.id] = keep.id

    remaining = [c for c in claims if c.id not in remove]
    by_doc: dict[int, list[EvidenceClaim]] = {}
    for claim in remaining:
        by_doc.setdefault(claim.source_document_id, []).append(claim)
    for doc_claims in by_doc.values():
        ordered = sorted(doc_claims, key=lambda c: len(c.claim_text), reverse=True)
        kept: list[EvidenceClaim] = []
        for claim in ordered:
            if any(_is_subsumed(claim.claim_text, other.claim_text) for other in kept):
                remove.add(claim.id)
                subsume_targets = [
                    other for other in kept if _is_subsumed(claim.claim_text, other.claim_text)
                ]
                canonical = max(subsume_targets, key=lambda c: len(c.claim_text))
                id_map[claim.id] = canonical.id
            else:
                kept.append(claim)

    by_span: dict[str, list[EvidenceClaim]] = {}
    for claim in claims:
        if claim.id in remove or not claim.source_span:
            continue
        by_span.setdefault(norm_text(claim.source_span), []).append(claim)
    for group in by_span.values():
        if len(group) < 2:
            continue
        keep = _pick_claim(group, sources)
        for claim in group:
            if claim.id != keep.id and claim.id not in remove:
                remove.add(claim.id)
                id_map[claim.id] = keep.id

    for removed_id in remove:
        keep_id = id_map[removed_id]
        removed = session.get(EvidenceClaim, removed_id)
        keep = session.get(EvidenceClaim, keep_id)
        if removed is None or keep is None:
            continue
        _merge_claim(session, removed, keep)
    if remove:
        session.commit()
    return id_map, len(remove)


def merge_entity_into(session: Session, keep: KnowledgeEntity, dupe: KnowledgeEntity) -> bool:
    """Fold ``dupe`` into ``keep``: links, relationships, claim FK, then delete."""
    if dupe.id is None or keep.id is None:
        return False
    merge_entity_document_links(session, keep.id, dupe.id)
    for rel in session.exec(select(KnowledgeRelationship)):
        changed = False
        if rel.source_entity_id == dupe.id:
            rel.source_entity_id = keep.id
            changed = True
        if rel.target_entity_id == dupe.id:
            rel.target_entity_id = keep.id
            changed = True
        if changed:
            session.add(rel)
    if dupe.source_claim_id and keep.source_claim_id is None:
        keep.source_claim_id = dupe.source_claim_id
        session.add(keep)
    session.delete(dupe)
    return True


def deduplicate_entities(session: Session) -> int:
    """Merge rows that share normalized_name + entity_type (keep oldest id)."""
    entities = list(session.exec(select(KnowledgeEntity)))
    groups: dict[tuple[str, str], list[KnowledgeEntity]] = {}
    for entity in entities:
        groups.setdefault((entity.normalized_name, entity.entity_type), []).append(entity)

    removed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda e: e.id or 0)
        keep, *dupes = group
        for dupe in dupes:
            if merge_entity_into(session, keep, dupe):
                removed += 1
    if removed:
        session.commit()
    return removed


def deduplicate_relationships(session: Session) -> int:
    rels = list(session.exec(select(KnowledgeRelationship)))
    seen: set[tuple[int | None, int | None, str]] = set()
    removed = 0
    for rel in rels:
        key = (rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
        if key in seen:
            session.delete(rel)
            removed += 1
        else:
            seen.add(key)
    if removed:
        session.commit()
    return removed


def deduplicate_knowledge(session: Session) -> DedupReport:
    from .entity_resolution import resolve_entity_aliases

    report = DedupReport()
    report.claim_links_backfilled, report.entity_links_backfilled = backfill_provenance_links(session)
    id_map, report.claims_removed = deduplicate_claims(session)
    report.claim_id_map = id_map
    report.removed_claim_ids = sorted(id_map.keys())
    report.entities_removed = deduplicate_entities(session)
    # EVAL-05: after exact-name dedup, fold alias/fuzzy variants of the same
    # real-world entity ("Acme" / "Acme Inc") onto one canonical node.
    report.entities_alias_merged = resolve_entity_aliases(session).entities_merged
    report.relationships_removed = deduplicate_relationships(session)
    report.materials_rewritten = _rewrite_material_evidence(session, id_map)
    if report.materials_rewritten:
        session.commit()
    return report


def _main(argv: list[str] | None = None) -> int:
    from ..db import get_engine, init_db

    init_db()
    with Session(get_engine()) as session:
        report = deduplicate_knowledge(session)
    print(
        f"Dedup complete: {report.claims_removed} claim(s), "
        f"{report.entities_removed} entity(ies) exact, "
        f"{report.entities_alias_merged} entity(ies) alias-merged, "
        f"{report.relationships_removed} relationship(s) removed; "
        f"{report.materials_rewritten} material(s) remapped; "
        f"backfilled {report.claim_links_backfilled} claim link(s), "
        f"{report.entity_links_backfilled} entity link(s)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
