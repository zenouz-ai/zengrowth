"""EVAL-04 (lite) — deterministic retrieval quality + RET-01 regression.

Measures context recall/precision of ``select_relevant_evidence`` against the
golden ``job -> expected_claim_ids`` set, and proves the RET-01 fix: a relevant
but lower-confidence claim that the old confidence-first cap dropped is now
retrieved.

No Ragas dependency — recall/precision here are exact set metrics. The judged
Ragas exploration layer (full EVAL-04) is a separate offline harness.
"""

from __future__ import annotations

import pytest

from zengrowth.eval import precision_at_k, recall_at_k
from zengrowth.materials.cv_alignment import select_relevant_evidence
from zengrowth.materials.evidence import ParsedEvidence

from ._golden import build_evidence, build_job, load_cases

CASES = load_cases("retrieval")
RECALL_THRESHOLD = 0.80


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_context_recall_meets_threshold(case: dict) -> None:
    job = build_job(case["job"])
    evidence = build_evidence(case["evidence_bank"])
    selected = select_relevant_evidence(evidence, job, limit=case["limit"])
    selected_ids = [e.id for e in selected]
    recall = recall_at_k(selected_ids, case["expected_claim_ids"])
    assert recall >= RECALL_THRESHOLD, (
        f"{case['id']}: context recall {recall:.2f} < {RECALL_THRESHOLD} "
        f"(selected {selected_ids}, expected {case['expected_claim_ids']})"
    )
    # Precision is monitored, not gated, on a small corpus — assert it is at least
    # well-formed so the metric stays exercised.
    assert 0.0 <= precision_at_k(selected_ids, case["expected_claim_ids"]) <= 1.0


def test_rank_before_cap_recovers_relevant_low_confidence_claim() -> None:
    """RET-01: the old confidence-first cap dropped a relevant low-confidence claim
    ranked beyond the limit; relevance-ranking before the cap recovers it."""
    job = build_job(
        {
            "company": "Novartis",
            "title": "Director Agentic AI",
            "description": "Agentic AI using LangGraph.",
            "job_summary": {"requirements": ["LangGraph"]},
            "fit_score": 88.0,
        }
    )
    limit = 40
    # 44 high-confidence but irrelevant claims, plus one relevant low-confidence gem.
    fillers = [
        ParsedEvidence(
            id=f"f{i:02d}",
            category="ops",
            claim_text="Administrative task about scheduling and filing.",
            verified=True,
            tags=[],
        )
        for i in range(44)
    ]
    gem = ParsedEvidence(
        id="gem",
        category="technical",
        claim_text="Built LangGraph multi-agent platforms for enterprise AI.",
        verified=True,
        tags=["agentic"],
    )
    pool = fillers + [gem]
    confidence = {e.id: 0.9 for e in fillers} | {"gem": 0.1}

    # Old behaviour: order by confidence desc, then cap (the bug).
    old_selected = sorted(pool, key=lambda e: -confidence[e.id])[:limit]
    assert "gem" not in {e.id for e in old_selected}

    # New behaviour: relevance-rank the full pool, then cap.
    new_selected = select_relevant_evidence(pool, job, limit=limit)
    assert "gem" in {e.id for e in new_selected}


def test_select_returns_pool_when_under_limit() -> None:
    job = build_job({"company": "Acme", "title": "Engineer"})
    evidence = build_evidence(
        [{"id": "a", "claim_text": "x"}, {"id": "b", "claim_text": "y"}]
    )
    assert select_relevant_evidence(evidence, job, limit=40) == evidence
