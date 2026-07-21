# Scoring and Priority

ZenGrowth scores each role with a single strict-JSON Claude call and computes an
explainable **priority score**. Scoring is pinned to `temperature=0`, so the same
job scores the same. The full rationale is stored on the row — scores are never
hidden behind a single number.

The candidate profile that steers the prompt (target roles, sectors, location,
compensation band) is supplied entirely from local settings/`.env`; this public
doc uses a synthetic profile.

## Scoring dimensions

The scorer (`src/zengrowth/scoring/scorer.py`, `prompts.py`) returns a score plus
a short reason for each dimension:

| Dimension | Range | Meaning |
|-----------|-------|---------|
| `role_relevance` | 0–100 | Title/responsibilities vs. target roles. |
| `ai_technical_alignment` | 0–100 | Depth of AI/ML/data technical fit. |
| `leadership_alignment` | 0–100 | Leadership/scope match. |
| `compensation_fit` | 0–100 | Pay vs. the configured target band. |
| `domain_fit` | 0–100 | Sector/domain match. |
| `strategic_career_value` | 0–100 | Long-term career value of the role. |
| `hybrid_location_fit` | 0–100 | Location/hybrid expectations vs. constraints. |
| `application_effort` | 1–5 | Effort to apply (5 = highest). Shown as a separate cost axis; never divides the rank. |
| `success_probability` | 0–1 | Model's confidence guess. Uncalibrated, so it is demoted to a coarse chances band used only as a tie-breaker. |
| `match_quality` | 0–100 | Overall match summary score. |

A natural-language `summary` accompanies the dimensions. Token usage is recorded
for cost tracking.

## Priority score

`src/zengrowth/scoring/expected_value.py` ranks on **observable fit only** — a
weighted sum of the scored dimensions on a 0–100 scale:

| Dimension | Weight |
|-----------|--------|
| `role_relevance` | 0.25 |
| `ai_technical_alignment` | 0.20 |
| `compensation_fit` | 0.15 |
| `leadership_alignment` | 0.10 |
| `domain_fit` | 0.10 |
| `hybrid_location_fit` | 0.10 |
| `strategic_career_value` | 0.10 |

Missing dimensions renormalise over the weights present. Two signals are
deliberately kept **out** of the rank:

- `success_probability` is an uncalibrated model guess, so it only maps to a
  coarse chances band (*strong* ≥ 0.5, *competitive* ≥ 0.2, else *long shot*)
  used as a tie-breaker between equal-priority jobs — a tiny epsilon that never
  overcomes a real 0.1 difference in observable fit.
- `application_effort` is shown to the operator as a separate cost axis; it
  never divides the score.

An earlier formula multiplied `match_quality × strategic_career_value ×
success_probability` and divided by effort. That let the noisiest input
dominate the ranking, double-counted strategy inside the composite, and buried
great roles behind a one-point effort difference — the weighted sum replaces it.

## Worked (synthetic) example

For a fictional "Head of AI" role at *Northwind Robotics* scoring 80 on every
observable dimension with `success_probability` 0.4 and `application_effort` 3:

```
priority = 0.25×80 + 0.20×80 + 0.15×80 + 0.10×80 + 0.10×80 + 0.10×80 + 0.10×80 = 80.0
band     = competitive   (tie-breaker only)
effort   = 3/5           (separate cost axis)
```

## Gating

Auto-ingested jobs must clear `PIPELINE_MIN_FIT_SCORE` (default 55) to reach the
curated board; manually added jobs bypass the gate. CV-tailoring breadth widens
for high-fit roles via `CV_ALIGNED_FIT_THRESHOLD` (70) and
`CV_PRIORITY_FIT_THRESHOLD` (75) — see [MATERIAL_GENERATION.md](MATERIAL_GENERATION.md).

## Calibration

A deterministic calibration suite runs in CI against frozen `temperature=0`
scorer outputs: rewording the same JD may move the priority score by at most
3.0 points, the ranking must agree with a hand-ranked golden ordering
(Kendall's τ ≥ 0.8), raising any single dimension can never lower the score,
and frozen anchor fixtures turn any weight change into a loud, deliberate
update. The number is relabelled "expected value" only once it is calibrated
against real outcomes.

## Cost controls

Every scoring call's cost/latency is recorded. A soft daily ceiling
(`LLM_DAILY_BUDGET_USD`, default 0 = off) fails scoring/material/extraction calls
closed with HTTP 503 once today's spend reaches the cap, rather than spending
unbounded. See [AUDIT_LOGGING.md](AUDIT_LOGGING.md).
