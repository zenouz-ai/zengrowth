from datetime import date
from typing import Any

import pytest
from sqlmodel import select

from zengrowth.audit import log_action
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.models import ActorType, AuditLog, Job, JobSource, LifecycleState
from zengrowth.scoring.expected_value import (
    DIMENSION_WEIGHTS,
    priority_score,
    ranked_priority,
    success_band,
)
from zengrowth.scoring.scorer import score_job, validate_scoring_response


class FakeLLM:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str]] = []

    def score(self, system: str, user: str, model: str) -> dict[str, Any]:
        self.calls.append((system, user, model))
        return self.response


def test_priority_score_is_weighted_sum_on_0_100_scale():
    uniform = {dim: 80.0 for dim in DIMENSION_WEIGHTS}
    assert priority_score(uniform) == 80.0
    assert priority_score({dim: 0.0 for dim in DIMENSION_WEIGHTS}) == 0.0


def test_priority_score_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 6) == 1.0


def test_priority_score_renormalises_missing_dimensions():
    partial = {"role_relevance": 90.0, "ai_technical_alignment": 90.0}
    assert priority_score(partial) == 90.0
    assert priority_score({}) == 0.0


def test_priority_score_clamps_out_of_range_values():
    assert priority_score({"role_relevance": 150.0}) == 100.0
    assert priority_score({"role_relevance": -20.0}) == 0.0


def test_success_band_thresholds():
    assert success_band(0.7) == "strong"
    assert success_band(0.5) == "strong"
    assert success_band(0.35) == "competitive"
    assert success_band(0.1) == "long_shot"
    assert success_band(None) == "unknown"


def test_ranked_priority_band_breaks_ties_but_never_beats_observable_fit():
    dims_a = {dim: 70.0 for dim in DIMENSION_WEIGHTS}
    # Equal observable fit: the stronger band wins the tie.
    assert ranked_priority(dims_a, 0.7) > ranked_priority(dims_a, 0.1)
    # A real 0.1 observable-fit difference always beats any band epsilon.
    dims_b = {dim: 70.0 for dim in DIMENSION_WEIGHTS} | {"role_relevance": 71.0}
    assert ranked_priority(dims_b, 0.05) > ranked_priority(dims_a, 0.9)


def test_ranking_snapshot_observable_fit_dominates():
    """TA-04 regression: rank on observable signal, not the old noisy product.

    Under the v1 product formula, job C (mediocre fit, optimistic
    success_probability, low effort) outranked job A (strong observable fit,
    conservative probability, high effort). The priority score must order by
    observable fit and keep effort/probability out of the rank.
    """
    jobs = {
        "A_strong_fit_low_confidence": (
            {dim: 85.0 for dim in DIMENSION_WEIGHTS},
            0.15,  # conservative guess
        ),
        "B_solid_fit": ({dim: 72.0 for dim in DIMENSION_WEIGHTS}, 0.4),
        "C_weak_fit_high_confidence": (
            {dim: 55.0 for dim in DIMENSION_WEIGHTS},
            0.9,  # optimistic guess — must not rescue a weak fit
        ),
    }
    ranked = sorted(
        jobs, key=lambda name: ranked_priority(jobs[name][0], jobs[name][1]), reverse=True
    )
    assert ranked == ["A_strong_fit_low_confidence", "B_solid_fit", "C_weak_fit_high_confidence"]


def _make_job() -> Job:
    return Job(
        company="Acme",
        title="Head of AI",
        location="London",
        hybrid_policy="2 days",
        seniority="Director",
        application_url="https://example.com/apply/1",
        posting_date=date.today(),
        description="Lead AI strategy across the group.",
        source=JobSource.manual,
        dedup_hash=dedup_hash("Acme", "Head of AI", date.today()),
    )


def test_score_job_persists_rationale_and_audit(session, fake_score_response):
    from zengrowth.config import Settings

    job = _make_job()
    session.add(job)
    session.commit()
    session.refresh(job)

    client = FakeLLM(fake_score_response)
    settings = Settings(anthropic_api_key="test", scoring_model="claude-test")

    scored = score_job(session, job, client=client, settings=settings)

    assert scored.fit_score == 74
    # TA-04: weighted observable fit (72.7 for the fixture dims) plus the
    # "competitive" band tie-break epsilon (0.02) for success_probability 0.4.
    assert scored.expected_value == pytest.approx(72.72)
    # TP-08 companion: scoring a discovered job (incl. manual paste) shortlists it.
    assert scored.lifecycle_state == LifecycleState.shortlisted
    assert scored.score_rationale is not None
    assert scored.score_rationale["summary"] == "Solid match; comp slightly below target."
    assert len(client.calls) == 1

    audit_rows = list(session.exec(select(AuditLog).where(AuditLog.action == "score_job")))
    assert len(audit_rows) == 1
    detail = audit_rows[0].detail
    assert detail["model"] == "claude-test"
    assert detail["tokens_in"] == 1200
    assert detail["tokens_out"] == 450
    # TA-04: chances band and effort are logged as separate axes, not rank inputs.
    assert detail["success_band"] == "competitive"
    assert detail["application_effort"] == 3
    # TP-07: the full rationale is persisted in the audit log so a later re-score
    # (which overwrites job.score_rationale) stays reconstructable. _usage is stripped.
    assert detail["rationale"]["match_quality"] == {"score": 74, "reason": "Strong overall."}
    assert "_usage" not in detail["rationale"]


def test_score_job_raises_on_missing_keys(session, fake_score_response):
    from zengrowth.config import Settings

    job = _make_job()
    session.add(job)
    session.commit()
    session.refresh(job)

    incomplete = dict(fake_score_response)
    del incomplete["match_quality"]

    settings = Settings(anthropic_api_key="test")
    with pytest.raises(ValueError, match="missing keys"):
        score_job(session, job, client=FakeLLM(incomplete), settings=settings)


def test_validate_scoring_response_requires_all_numeric_dimensions(fake_score_response):
    validate_scoring_response(fake_score_response)
    broken = dict(fake_score_response)
    broken["role_relevance"] = {"score": "high", "reason": "vague"}
    with pytest.raises(ValueError, match="role_relevance"):
        validate_scoring_response(broken)


def test_audit_log_helper_writes_row(session):
    entry = log_action(
        session,
        actor=ActorType.system,
        action="test_action",
        entity_type="test",
        entity_id=1,
        detail={"k": "v"},
    )
    assert entry.id is not None
    assert entry.actor == ActorType.system
    assert entry.detail == {"k": "v"}
