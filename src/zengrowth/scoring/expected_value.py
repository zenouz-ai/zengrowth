"""Priority score — ranks jobs on observable fit (TA-04).

The v1 formula multiplied three noisy estimates and divided by effort:
``EV = (match_quality × strategic_value × success_probability) / effort``.
Audit findings: ``success_probability`` is an uncalibrated LLM guess and, as a
multiplier, dominated the product's variance; ``match_quality`` is itself a
composite of the other dimensions, so multiplying it by
``strategic_career_value`` double-counted strategy; and dividing by
``application_effort`` silently buried otherwise-great roles behind a
one-point effort difference.

v2 ranks on **observable fit only**: a weighted sum of the scorer's
per-dimension 0–100 scores. ``success_probability`` is demoted to a coarse
band used purely as a tie-breaker between equal-priority jobs, and
``application_effort`` is a separate cost axis the operator sees next to the
score — neither multiplies nor divides the rank. The stored number is
deliberately labelled **Priority score** in the UI, not "expected value",
until it is calibrated against real outcomes (TA-09 → then relabel).
"""

from __future__ import annotations

# Observable-fit weights (sum to 1.0). Role and technical alignment carry the
# most signal for a targeted senior search; strategic_career_value is a single
# weighted input here — never a multiplier — which removes the old
# match × strategic double-count.
DIMENSION_WEIGHTS: dict[str, float] = {
    "role_relevance": 0.25,
    "ai_technical_alignment": 0.20,
    "compensation_fit": 0.15,
    "leadership_alignment": 0.10,
    "domain_fit": 0.10,
    "hybrid_location_fit": 0.10,
    "strategic_career_value": 0.10,
}

# Tie-breaker epsilons by success band. Small enough never to cross a 0.1
# priority-score step (scores are rounded to 1 dp before adding), so the band
# can only order jobs whose observable fit is identical.
_BAND_EPSILON: dict[str, float] = {"strong": 0.03, "competitive": 0.02, "long_shot": 0.01}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def priority_score(dimensions: dict[str, float]) -> float:
    """Weighted sum of observable 0–100 dimension scores → 0–100.

    Missing dimensions renormalise over the weights present, so a scorer
    response that omits one dimension degrades gracefully instead of silently
    deflating the score.
    """
    total = 0.0
    weight_used = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        value = dimensions.get(dim)
        if value is None:
            continue
        total += weight * _clamp(float(value))
        weight_used += weight
    if weight_used == 0.0:
        return 0.0
    return round(total / weight_used, 1)


def success_band(probability: float | None) -> str:
    """Coarse chances band from the model's 0–1 confidence guess.

    Deliberately three-valued: the underlying number is not calibrated
    (TA-09), so anything finer-grained would be false precision.
    """
    if probability is None:
        return "unknown"
    if probability >= 0.5:
        return "strong"
    if probability >= 0.2:
        return "competitive"
    return "long_shot"


def ranked_priority(dimensions: dict[str, float], probability: float | None) -> float:
    """The stored ranking value: priority score plus a band tie-break epsilon.

    The epsilon (< 0.05) never changes the displayed 1-dp score and can never
    overcome a real 0.1 difference in observable fit — it only orders jobs
    whose priority scores are exactly equal, favouring the better chances band.
    """
    return priority_score(dimensions) + _BAND_EPSILON.get(success_band(probability), 0.0)
