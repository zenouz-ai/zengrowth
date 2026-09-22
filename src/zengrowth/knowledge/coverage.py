"""KG-02 coverage aggregation: what the bank contains vs. what scored JDs demand.

Rolls the ``ClaimFacet`` / ``JobFacet`` rows up into the three Coverage-tab
surfaces (``docs/EVIDENCE-COVERAGE-PLAN.md`` §3 Stage 1):

- per-facet value counts with claim ids — the treemap and its drill-down;
- a monthly series of newly-verified evidence per value — the
  evidence-over-time chart;
- demand counts from scored JDs sharing the same vocabulary, with a ``gap``
  flag when JDs ask for something no verified claim answers — the
  coverage-vs-demand heatmap.

Pure aggregation over stored rows: deterministic, no LLM, cheap enough to
compute per request at single-operator corpus size. Rejected claims are
excluded everywhere; draft claims are counted separately so the surfaces can
show "evidence exists but is unreviewed" distinctly from a real gap.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..models import ClaimFacet, ClaimVerificationState, EvidenceClaim, Job, JobFacet
from .facets import FACET_KEYS, load_facet_vocabulary


def _month(value: Any) -> str | None:
    try:
        return value.strftime("%Y-%m")
    except AttributeError:
        return None


def coverage_report(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    """The full coverage/demand dataset the Coverage tab renders from."""
    settings = settings or get_settings()
    vocabulary = load_facet_vocabulary(settings)

    claims = {c.id: c for c in session.exec(select(EvidenceClaim))}
    jobs = {j.id: j for j in session.exec(select(Job)) if j.id is not None}
    claim_facets = session.exec(select(ClaimFacet)).all()
    job_facets = session.exec(select(JobFacet)).all()

    # facet -> value -> accumulators
    buckets: dict[str, dict[str, dict[str, Any]]] = {
        facet: defaultdict(
            lambda: {
                "verified_claim_ids": [],
                "draft_claim_ids": [],
                "job_ids": [],
                "monthly": defaultdict(int),
            }
        )
        for facet in FACET_KEYS
    }

    faceted_claim_ids: set[str] = set()
    for row in claim_facets:
        claim = claims.get(row.claim_id)
        if claim is None or row.facet not in buckets:
            continue
        # Rejected claims are excluded from every surface, including totals —
        # counting them here made faceted_claims > claims on the Coverage tab.
        if claim.verification_state == ClaimVerificationState.rejected:
            continue
        faceted_claim_ids.add(claim.id)
        bucket = buckets[row.facet][row.value]
        if claim.verification_state == ClaimVerificationState.verified:
            bucket["verified_claim_ids"].append(claim.id)
            month = _month(claim.created_at)
            if month:
                bucket["monthly"][month] += 1
        else:
            bucket["draft_claim_ids"].append(claim.id)

    faceted_job_ids: set[int] = set()
    for row in job_facets:
        if row.facet not in buckets or row.job_id not in jobs:
            continue
        faceted_job_ids.add(row.job_id)
        buckets[row.facet][row.value]["job_ids"].append(row.job_id)

    facets_out: list[dict[str, Any]] = []
    for facet in FACET_KEYS:
        values_out: list[dict[str, Any]] = []
        for value, bucket in buckets[facet].items():
            verified = sorted(bucket["verified_claim_ids"])
            draft = sorted(bucket["draft_claim_ids"])
            job_ids = sorted(set(bucket["job_ids"]))
            values_out.append(
                {
                    "value": value,
                    "verified_claims": len(verified),
                    "draft_claims": len(draft),
                    "claim_ids": verified,
                    "demand_jobs": len(job_ids),
                    "job_ids": job_ids,
                    # The heatmap's actionable signal: JDs demand it, nothing
                    # verified answers it (draft-only evidence still counts as
                    # a gap — it has not passed review).
                    "gap": bool(job_ids) and not verified,
                    "monthly": [
                        {"month": month, "claims": count}
                        for month, count in sorted(bucket["monthly"].items())
                    ],
                }
            )
        values_out.sort(
            key=lambda v: (-v["verified_claims"], -v["demand_jobs"], v["value"])
        )
        facets_out.append(
            {"facet": facet, "values": values_out, "vocabulary_size": len(vocabulary[facet])}
        )

    active_claims = [
        c for c in claims.values() if c.verification_state != ClaimVerificationState.rejected
    ]
    scored_job_ids = {j.id for j in jobs.values() if j.fit_score is not None}
    demand_jobs = [
        {
            "id": job_id,
            "company": jobs[job_id].company,
            "title": jobs[job_id].title,
        }
        for job_id in sorted(faceted_job_ids)
        if job_id in jobs
    ]
    return {
        "facets": facets_out,
        "jobs": demand_jobs,
        "totals": {
            "claims": len(active_claims),
            "faceted_claims": len(faceted_claim_ids),
            "unfaceted_claims": len([c for c in active_claims if c.id not in faceted_claim_ids]),
            "scored_jobs": len(scored_job_ids),
            "faceted_jobs": len(faceted_job_ids),
            "unfaceted_jobs": len(scored_job_ids - faceted_job_ids),
        },
    }
