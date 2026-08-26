"""Entity resolution — alias/fuzzy merge of fragmented knowledge entities (EVAL-05).

Entity identity was exact ``normalized_name + entity_type`` match, so surface
variants of the same real-world entity ("Acme" / "Acme Inc" / "Acme Corporation")
fragmented into separate nodes — and would fragment KG-02's coverage facet
counts the same way. This module resolves those variants:

- ``alias_key`` canonicalises a name (case/punctuation folding + legal-form
  suffix stripping), so corporate-suffix variants collapse deterministically.
- ``names_match`` adds a guarded fuzzy layer (``rapidfuzz`` indel similarity on
  the alias keys) for typos and spacing variants, plus a single-token prefix
  rule for common truncations ("PostgreSQL" / "Postgres").
- ``cluster_entity_names`` union-finds mention groups per ``entity_type`` — the
  same clustering the pairwise-F1 eval gate (``tests/eval/``) scores against the
  hand-labelled golden set.
- ``resolve_entity_aliases`` applies the clustering to stored
  ``KnowledgeEntity`` rows (merge onto the oldest id, aliases recorded on
  ``meta``), and ``find_entity_alias`` gives ingest the same matching so new
  mentions bind to an existing node instead of creating a fragment.

Matching is deliberately conservative: ``entity_type`` never crosses, short
keys never fuzzy-match, and distinct-but-similar names ("Acme" vs
"Acme Health", "Meta" vs "Metabase") stay separate — precision errors corrupt
the graph silently, while recall misses only leave a duplicate node visible for
review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz
from sqlmodel import Session, select

from ..models import KnowledgeEntity

# Legal-form / corporate-registration suffixes that never distinguish one
# organisation from another. Descriptive tails ("Health", "Labs", "DeepMind")
# are deliberately NOT here — they usually name a different org.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "incorporated", "ltd", "limited", "llc", "llp", "lp",
        "corp", "corporation", "co", "company", "plc", "gmbh", "ag", "sa",
        "srl", "bv", "nv", "oy", "ab", "pty", "kk", "holdings",
    }
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Fuzzy matching only applies to keys at least this long: short names ("AWS",
# "Java") are one typo away from a different entity, so they must match exactly.
_FUZZY_MIN_LEN = 5
# Indel similarity (0-100) on token-sorted alias keys required to merge.
FUZZY_MATCH_THRESHOLD = 90
# Single-token truncation aliases ("postgres" -> "postgresql") need a prefix at
# least this long, so "java"/"javascript" and "meta"/"metabase" stay separate.
_PREFIX_MIN_LEN = 6


def alias_key(name: str) -> str:
    """Canonical comparison key: casefold, fold punctuation, strip legal suffixes."""
    tokens = _NON_ALNUM_RE.sub(" ", name.casefold()).split()
    stripped = list(tokens)
    while len(stripped) > 1 and stripped[-1] in _LEGAL_SUFFIXES:
        stripped.pop()
    return " ".join(stripped or tokens)


def _prefix_alias(a: str, b: str) -> bool:
    """Single-token truncation aliases: one key is a long prefix of the other."""
    shorter, longer = sorted((a, b), key=len)
    return (
        len(shorter) >= _PREFIX_MIN_LEN
        and " " not in shorter
        and " " not in longer
        and longer.startswith(shorter)
    )


def names_match(a: str, b: str) -> bool:
    """True when two surface names refer to the same entity."""
    key_a, key_b = alias_key(a), alias_key(b)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    if (
        min(len(key_a), len(key_b)) >= _FUZZY_MIN_LEN
        and fuzz.token_sort_ratio(key_a, key_b) >= FUZZY_MATCH_THRESHOLD
    ):
        return True
    return _prefix_alias(key_a, key_b)


def cluster_entity_names(
    mentions: list[tuple[str, str, str]],
) -> list[set[str]]:
    """Union-find mention ids into same-entity clusters.

    ``mentions`` is ``(mention_id, surface_name, entity_type)``. Only mentions
    sharing an ``entity_type`` can merge. Quadratic per type — fine at
    single-operator corpus scale (hundreds of entities, not millions).
    """
    parent: dict[str, str] = {m[0]: m[0] for m in mentions}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_y] = root_x

    by_type: dict[str, list[tuple[str, str]]] = {}
    for mention_id, name, entity_type in mentions:
        by_type.setdefault(entity_type, []).append((mention_id, name))
    for group in by_type.values():
        for i, (id_a, name_a) in enumerate(group):
            for id_b, name_b in group[i + 1 :]:
                if names_match(name_a, name_b):
                    union(id_a, id_b)

    clusters: dict[str, set[str]] = {}
    for mention_id, _, _ in mentions:
        clusters.setdefault(find(mention_id), set()).add(mention_id)
    return list(clusters.values())


def find_entity_alias(
    session: Session, name: str, entity_type: str
) -> KnowledgeEntity | None:
    """Existing entity of ``entity_type`` that ``name`` is an alias of, if any."""
    candidates = session.exec(
        select(KnowledgeEntity).where(KnowledgeEntity.entity_type == entity_type)
    ).all()
    matches = [e for e in candidates if names_match(name, e.name)]
    if not matches:
        return None
    return min(matches, key=lambda e: e.id or 0)


def record_alias(session: Session, entity: KnowledgeEntity, surface_name: str) -> None:
    """Remember a merged surface form on the canonical entity's ``meta``."""
    if surface_name == entity.name:
        return
    meta = dict(entity.meta or {})
    aliases = set(meta.get("aliases") or [])
    if surface_name in aliases:
        return
    aliases.add(surface_name)
    meta["aliases"] = sorted(aliases)
    entity.meta = meta
    session.add(entity)


@dataclass
class AliasResolutionReport:
    entities_merged: int = 0
    merges: dict[str, list[str]] = field(default_factory=dict)


def resolve_entity_aliases(session: Session) -> AliasResolutionReport:
    """Merge stored entities whose names resolve to the same real-world entity.

    Within each cluster the oldest id survives (stable foreign keys, matching
    ``deduplicate_entities``); merged surface names are recorded as aliases on
    the canonical row's ``meta``.
    """
    from .dedup import merge_entity_into

    report = AliasResolutionReport()
    entities = [e for e in session.exec(select(KnowledgeEntity)) if e.id is not None]
    by_id = {str(e.id): e for e in entities}
    clusters = cluster_entity_names([(str(e.id), e.name, e.entity_type) for e in entities])
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        members = sorted((by_id[mention_id] for mention_id in cluster), key=lambda e: e.id or 0)
        keep, *dupes = members
        for dupe in dupes:
            record_alias(session, keep, dupe.name)
            merge_entity_into(session, keep, dupe)
            report.entities_merged += 1
        report.merges[keep.name] = [d.name for d in dupes]
    if report.entities_merged:
        session.commit()
    return report
