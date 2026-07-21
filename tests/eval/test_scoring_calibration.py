"""EVAL-07 — scoring calibration suite (deterministic, no LLM).

The priority score is an LLM-as-judge output: the scorer emits per-dimension
0-100 values (pinned to temperature 0, TP-07) and ``priority_score`` aggregates
them. This suite calibrates the deterministic half against frozen scorer
outputs in ``golden/scoring_calibration.json``:

- **Rewording stability** — the same JD scored under two rewordings jitters a
  few points per dimension; the aggregation must dampen, never amplify, that
  jitter (|delta| <= 3.0 points on the 0-100 scale).
- **Monotonicity** — Kendall's tau >= 0.8 against the operator's hand-ranked
  ordering, and raising any single dimension never lowers the score. The
  hand-ranked set gives weak fits optimistic success probabilities, so it also
  re-proves TA-04: probability cannot rescue a weak fit.
- **Anchor drift alarm** — frozen expected scores; any weight change fails
  here and must consciously update the fixtures alongside the rationale.

The judged half (bias probes over live scorer outputs) needs an LLM and stays
with the sampled judged layer (EVAL-03), not in the per-PR deterministic gates.
"""

from __future__ import annotations

import pytest

from zengrowth.eval import kendall_tau
from zengrowth.scoring.expected_value import (
    DIMENSION_WEIGHTS,
    priority_score,
    ranked_priority,
)

from ._golden import load_golden

GOLDEN = load_golden("scoring_calibration")
REWORDING_PAIRS = GOLDEN["rewording_pairs"]
HAND_RANKED = GOLDEN["hand_ranked"]
ANCHORS = GOLDEN["anchors"]

REWORDING_MAX_DELTA = 3.0
KENDALL_TAU_THRESHOLD = 0.8


@pytest.mark.parametrize("pair", REWORDING_PAIRS, ids=[p["id"] for p in REWORDING_PAIRS])
def test_priority_score_stable_under_jd_rewording(pair: dict) -> None:
    delta = abs(priority_score(pair["variant_a"]) - priority_score(pair["variant_b"]))
    assert delta <= REWORDING_MAX_DELTA, (
        f"{pair['id']}: rewording moved the priority score by {delta:.1f} "
        f"(> {REWORDING_MAX_DELTA}) — aggregation is amplifying scorer jitter"
    )


def test_rewording_never_changes_the_success_band_tiebreak_by_more_than_epsilon() -> None:
    """Probability is not a rank input: identical dimensions with different
    probability guesses must produce the identical displayed score."""
    dims = REWORDING_PAIRS[0]["variant_a"]
    assert priority_score(dims) == priority_score(dims)
    spread = ranked_priority(dims, 0.9) - ranked_priority(dims, 0.05)
    assert 0.0 < spread < 0.05


def test_hand_ranked_ordering_kendall_tau_meets_threshold() -> None:
    """The headline monotonicity gate against the operator's hand ranking.

    One deliberate human/formula disagreement stays in the golden set (the
    operator weights compensation harder than the formula), so perfect tau is
    not expected — a real calibration signal for TA-09, not noise.
    """
    gold = [float(len(HAND_RANKED) - i) for i in range(len(HAND_RANKED))]
    predicted = [
        ranked_priority(job["dimensions"], job["probability"]) for job in HAND_RANKED
    ]
    tau = kendall_tau(gold, predicted)
    assert tau >= KENDALL_TAU_THRESHOLD, (
        f"hand-ranked Kendall tau {tau:.3f} < {KENDALL_TAU_THRESHOLD} "
        f"(predicted order: {sorted(zip(predicted, [j['id'] for j in HAND_RANKED], strict=False), reverse=True)})"
    )


def test_optimistic_probability_never_rescues_weak_fit_in_hand_ranked_set() -> None:
    """TA-04 regression at suite scale: the golden set pairs weak fits with
    optimistic probabilities, and they must still rank at the bottom."""
    predicted = sorted(
        HAND_RANKED,
        key=lambda job: ranked_priority(job["dimensions"], job["probability"]),
        reverse=True,
    )
    assert [job["id"] for job in predicted][-3:] == [
        "high-comp-weak-role",
        "junior-misaligned",
        "poor-fit",
    ]


@pytest.mark.parametrize("anchor", ANCHORS, ids=[a["id"] for a in ANCHORS])
def test_anchor_scores_have_not_drifted(anchor: dict) -> None:
    """Drift alarm: a weight change must consciously update these fixtures."""
    score = priority_score(anchor["dimensions"])
    assert score == anchor["expected_priority"], (
        f"{anchor['id']}: priority {score} != frozen {anchor['expected_priority']} — "
        "if the weights changed deliberately, update the anchor and the rationale"
    )


@pytest.mark.parametrize("anchor", ANCHORS, ids=[a["id"] for a in ANCHORS])
@pytest.mark.parametrize("dimension", sorted(DIMENSION_WEIGHTS))
def test_raising_any_single_dimension_never_lowers_the_score(
    anchor: dict, dimension: str
) -> None:
    base = priority_score(anchor["dimensions"])
    raised = priority_score({**anchor["dimensions"], dimension: 100.0})
    assert raised >= base
