"""TP-02b — claim-vs-span distortion gates (deterministic, no LLM).

TP-02 proves a cited span exists in the source; these gates prove the *claim*
matches the *span*. Both directions are exact: a faithful claim must produce
zero violations (no false demotions eroding auto-verify), and a distorted
claim must be flagged with exactly the offending tokens (the gate is not
vacuous, and the review queue shows the operator precisely what to check).
"""

from __future__ import annotations

import pytest

from zengrowth.knowledge.service import claim_span_distortions

from ._golden import load_cases

CASES = load_cases("claim_distortion")
FAITHFUL = [c for c in CASES if not c["distorted"]]
DISTORTED = [c for c in CASES if c["distorted"]]


@pytest.mark.parametrize("case", FAITHFUL, ids=[c["id"] for c in FAITHFUL])
def test_faithful_claim_produces_no_violations(case: dict) -> None:
    violations = claim_span_distortions(case["claim_text"], case["source_span"])
    assert violations == [], f"{case['id']}: false distortions {violations}"


@pytest.mark.parametrize("case", DISTORTED, ids=[c["id"] for c in DISTORTED])
def test_distorted_claim_is_flagged_with_exact_tokens(case: dict) -> None:
    violations = claim_span_distortions(case["claim_text"], case["source_span"])
    assert violations == case["expected_violations"], (
        f"{case['id']}: expected {case['expected_violations']}, got {violations}"
    )


def test_spanless_claim_reports_no_distortions() -> None:
    """No span → nothing to check; TP-02 already keeps spanless claims draft."""
    assert claim_span_distortions("Increased revenue by 40%.", None) == []
    assert claim_span_distortions("Increased revenue by 40%.", "   ") == []
