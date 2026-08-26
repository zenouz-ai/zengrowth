"""EVAL-05 — entity-resolution eval gate (pairwise F1 >= 0.85, no LLM).

Scores ``cluster_entity_names`` against the hand-labelled golden clustering in
``golden/entity_resolution.json``. Pairwise F1 penalises both failure modes:
over-merging (precision — distinct entities glued together corrupt the graph
silently) and fragmentation (recall — "Acme" / "Acme Inc" as separate nodes,
the original EVAL-05 finding). The golden set keeps known-hard recall misses
(initialisms, abbreviation aliases) so the gate stays honest below 1.0, and
every ``must_not_merge`` pair is asserted exactly — precision failures are
never tradeable against recall headroom.
"""

from __future__ import annotations

import pytest

from zengrowth.eval import pairwise_f1
from zengrowth.knowledge.entity_resolution import cluster_entity_names

from ._golden import load_cases

CASES = load_cases("entity_resolution")
PAIRWISE_F1_THRESHOLD = 0.85


def _gold_clusters(mentions: list[dict]) -> list[set[str]]:
    by_label: dict[tuple[str, str], set[str]] = {}
    for mention in mentions:
        # Gold identity is scoped by entity_type, matching the resolver.
        by_label.setdefault((mention["gold_cluster"], mention["entity_type"]), set()).add(
            mention["id"]
        )
    return list(by_label.values())


def _predicted_clusters(mentions: list[dict]) -> list[set[str]]:
    return cluster_entity_names(
        [(m["id"], m["name"], m["entity_type"]) for m in mentions]
    )


def test_pairwise_f1_meets_threshold_across_full_golden_set() -> None:
    """The headline EVAL-05 gate: aggregate pairwise F1 >= 0.85."""
    mentions = [m for case in CASES for m in case["mentions"]]
    score = pairwise_f1(_predicted_clusters(mentions), _gold_clusters(mentions))
    assert score >= PAIRWISE_F1_THRESHOLD, (
        f"entity-resolution pairwise F1 {score:.3f} < {PAIRWISE_F1_THRESHOLD}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_hard_negatives_never_merge(case: dict) -> None:
    """Precision is non-negotiable: listed distinct-entity pairs must stay apart."""
    clusters = _predicted_clusters(case["mentions"])
    by_id = {m["id"]: m["name"] for m in case["mentions"]}
    for id_a, id_b in case.get("must_not_merge", []):
        together = any(id_a in cluster and id_b in cluster for cluster in clusters)
        assert not together, (
            f"{case['id']}: {by_id[id_a]!r} and {by_id[id_b]!r} merged but are distinct entities"
        )


def test_alias_variants_of_same_employer_cluster_together() -> None:
    """The original finding: corporate-suffix variants must resolve to one node."""
    employers = next(c for c in CASES if c["id"] == "employers")
    clusters = _predicted_clusters(employers["mentions"])
    acme_ids = {
        m["id"] for m in employers["mentions"] if m["gold_cluster"] == "acme"
    }
    assert any(acme_ids <= cluster for cluster in clusters), (
        "Acme surface variants did not resolve to a single cluster"
    )
