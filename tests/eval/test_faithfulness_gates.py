"""EVAL-02 — deterministic faithfulness CI gates (no LLM, full golden set).

These are the *safety* gates. They run on every PR in the normal pytest job and
reuse the runtime grounding primitives (TP-01/01b), so a regression that opens a
hole in the write-time gate is caught here too.

The threshold is deliberately exact (``== []`` / 1.0), not a soft score: an
employer-submitted document cannot trade away a single fabricated metric,
employer, or tool.
"""

from __future__ import annotations

import pytest

from zengrowth.eval import forbidden_fact_hits, hard_fact_violations

from ._golden import build_evidence, build_job, load_cases

CASES = load_cases("generation")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_accepted_output_has_no_hard_fact_violations(case: dict) -> None:
    """Every grounded golden output passes the hard-fact gate (faithfulness 1.0)."""
    job = build_job(case["job"])
    evidence = build_evidence(case["evidence_bank"])
    violations = hard_fact_violations(case["accepted_output"], evidence, job)
    assert violations == [], f"{case['id']}: ungrounded hard facts {violations}"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_accepted_output_avoids_forbidden_facts(case: dict) -> None:
    """The adversarial channel: a faithful output never asserts a forbidden fact."""
    hits = forbidden_fact_hits(case["accepted_output"], case.get("forbidden_facts", []))
    assert hits == [], f"{case['id']}: leaked forbidden facts {hits}"


@pytest.mark.parametrize(
    "case", [c for c in CASES if "negative_output" in c], ids=[c["id"] for c in CASES if "negative_output" in c]
)
def test_negative_output_is_flagged(case: dict) -> None:
    """The gate must actually catch a fabricated draft — proves it is not vacuous."""
    job = build_job(case["job"])
    evidence = build_evidence(case["evidence_bank"])
    violations = hard_fact_violations(case["negative_output"], evidence, job)
    assert violations, f"{case['id']}: gate failed to flag a fabricated draft"
