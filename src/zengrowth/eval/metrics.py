"""Deterministic, LLM-free eval metrics for the RAG pipeline (EVAL-02 / EVAL-04).

These are the *safety* metrics: they cost nothing (no judge), so they run on the
full golden set on every PR. The faithfulness metrics deliberately **reuse the
runtime grounding primitives** (TP-01/01b) from ``materials.generator`` so the CI
eval gate and the write-time gate share one definition and cannot silently drift
apart — if the gate develops a hole, the eval sees the same hole.

Judged metrics (prose faithfulness, relevancy via DeepEval/Ragas) are a separate,
sampled, cached layer (EVAL-03) and are intentionally not here.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..materials.evidence import ParsedEvidence
from ..materials.generator import (
    _entity_tokens,
    _grounding_entity_tokens,
    _grounding_number_tokens,
    _num_tokens,
)
from ..models import Job


def hard_fact_violations(text: str, evidence: list[ParsedEvidence], job: Job) -> list[str]:
    """Numbers and named entities asserted in ``text`` grounded in neither the
    evidence bank nor the job context.

    Empty list == faithful on hard facts. This is the highest-blast fabrication
    class (invented metrics / employers / tools), so the CI threshold is an exact
    ``== []`` (faithfulness 1.0), not a soft score: a single ungrounded figure in
    an employer-submitted document is a safety incident.
    """
    allowed_nums = _grounding_number_tokens(evidence, job)
    allowed_ents = _grounding_entity_tokens(evidence, job)
    bad_nums = sorted(_num_tokens(text) - allowed_nums)
    bad_ents = sorted(_entity_tokens(text) - allowed_ents)
    return bad_nums + bad_ents


def hard_fact_faithful(text: str, evidence: list[ParsedEvidence], job: Job) -> bool:
    """True iff every number/entity in ``text`` traces to evidence or job context."""
    return not hard_fact_violations(text, evidence, job)


def forbidden_fact_hits(text: str, forbidden: Iterable[str]) -> list[str]:
    """Adversarial channel: facts that must NOT appear in the output.

    Turns "the model happened not to hallucinate this run" into an explicit
    assertion. Returns the forbidden strings that leaked; empty list == passed.
    """
    low = text.lower()
    return [f for f in forbidden if f.lower() in low]


def recall_at_k(selected_ids: Iterable[str], expected_ids: Iterable[str]) -> float:
    """Fraction of the evidence a case *needs* that retrieval actually surfaced.

    The metric most at risk in this codebase (RET-01): a vacuous-high score is
    impossible because an empty expected set returns 1.0 only when nothing was
    required.
    """
    expected = set(expected_ids)
    if not expected:
        return 1.0
    return len(set(selected_ids) & expected) / len(expected)


def kendall_tau(a: list[float], b: list[float]) -> float:
    """Kendall's τ-a rank correlation between two aligned score sequences (EVAL-07).

    Item ``i`` of ``a`` and ``b`` score the same job under two orderings (e.g.
    the hand ranking vs the priority score). +1 = perfect agreement, −1 =
    perfect inversion. A pair tied in either sequence counts as neither
    concordant nor discordant, so ties dilute τ rather than inflate it —
    a scorer that flattens everything to one value cannot pass the gate.
    """
    if len(a) != len(b):
        raise ValueError("kendall_tau requires equal-length sequences")
    n = len(a)
    if n < 2:
        return 1.0
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            product = (a[i] - a[j]) * (b[i] - b[j])
            if product > 0:
                concordant += 1
            elif product < 0:
                discordant += 1
    return (concordant - discordant) / (n * (n - 1) / 2)


def _cluster_pairs(clusters: Iterable[Iterable[str]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for cluster in clusters:
        items = sorted(cluster)
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                pairs.add((a, b))
    return pairs


def pairwise_f1(
    predicted: Iterable[Iterable[str]], gold: Iterable[Iterable[str]]
) -> float:
    """Pairwise F1 between a predicted and a gold clustering (EVAL-05).

    A "pair" is two mention ids placed in the same cluster. Precision penalises
    over-merging (distinct entities glued together), recall penalises
    fragmentation ("Acme" / "Acme Inc" left apart) — exactly the two failure
    modes entity resolution trades off. Singleton-only clusterings on both
    sides count as perfect agreement.
    """
    predicted_pairs = _cluster_pairs(predicted)
    gold_pairs = _cluster_pairs(gold)
    if not predicted_pairs and not gold_pairs:
        return 1.0
    if not predicted_pairs or not gold_pairs:
        return 0.0
    true_positives = len(predicted_pairs & gold_pairs)
    precision = true_positives / len(predicted_pairs)
    recall = true_positives / len(gold_pairs)
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def precision_at_k(selected_ids: Iterable[str], expected_ids: Iterable[str]) -> float:
    """Fraction of retrieved claims that were relevant. Monitored, not gated on
    a small single-operator corpus where over-retrieval is cheap (see EVAL.md)."""
    selected = list(selected_ids)
    if not selected:
        return 0.0
    expected = set(expected_ids)
    return len([s for s in selected if s in expected]) / len(selected)
