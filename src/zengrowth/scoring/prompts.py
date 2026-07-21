"""Scoring prompt.

Single-agent Phase 1. Dual-agent + moderator is # TODO(phase-2).
Returns strict JSON; the parser fails loud on malformed output (with one
fence-strip retry in scorer.py).
"""

from __future__ import annotations

import json

from ..config import Settings

SYSTEM_PROMPT = """You are a senior career strategist evaluating job postings for a specific candidate.
You always reply with ONE JSON object and nothing else: no markdown, no code fences, no commentary.
You score conservatively: high scores require strong evidence in the job description."""


REQUIRED_KEYS = (
    "role_relevance",
    "ai_technical_alignment",
    "leadership_alignment",
    "compensation_fit",
    "domain_fit",
    "strategic_career_value",
    "hybrid_location_fit",
    "application_effort",
    "success_probability",
    "match_quality",
    "summary",
)


def build_user_prompt(settings: Settings, *, job: dict, posting_age_days: int | None) -> str:
    profile = {
        "location": settings.user_location,
        "target_roles": settings.user_target_roles,
        "target_sectors": settings.user_target_sectors,
        "hybrid_max_office_days_per_week": settings.user_hybrid_max_office_days,
        "compensation_min_gbp": settings.user_comp_min_gbp,
        "compensation_target_gbp": settings.user_comp_target_gbp,
        "recency_preference_days": 14,
    }
    schema = {
        "role_relevance": "integer 0-100 + one-line reason",
        "ai_technical_alignment": "integer 0-100 + reason",
        "leadership_alignment": "integer 0-100 + reason",
        "compensation_fit": "integer 0-100 + reason",
        "domain_fit": "integer 0-100 + reason",
        "strategic_career_value": "integer 0-100 + reason",
        "hybrid_location_fit": "integer 0-100 + reason",
        "application_effort": "integer 1-5 (5 = highest effort) + reason",
        "success_probability": "float 0.0-1.0 (calibrated) + reason",
        "match_quality": "integer 0-100 overall composite + reason",
        "summary": "two-sentence recommendation",
    }
    example = {
        "role_relevance": {"score": 75, "reason": "Title matches Director of AI."},
        "ai_technical_alignment": {"score": 80, "reason": "Mentions GenAI, MLOps."},
        "leadership_alignment": {"score": 70, "reason": "Manages a team of 8."},
        "compensation_fit": {"score": 60, "reason": "Band overlaps target minimum."},
        "domain_fit": {"score": 65, "reason": "FinTech matches sectors list."},
        "strategic_career_value": {"score": 70, "reason": "Builds platform from scratch."},
        "hybrid_location_fit": {"score": 80, "reason": "London hybrid, 2 days/week."},
        "application_effort": {"score": 3, "reason": "Standard CV + cover letter."},
        "success_probability": {"score": 0.35, "reason": "Competitive but credible."},
        "match_quality": {"score": 72, "reason": "Strong overall alignment."},
        "summary": "Strong fit on title and tech. Compensation is on the low end of target.",
    }

    return (
        "Score this job posting for the candidate below. Reply with a single JSON object only.\n\n"
        f"CANDIDATE PROFILE:\n{json.dumps(profile, indent=2)}\n\n"
        f"JOB POSTING:\n{json.dumps(job, indent=2, default=str)}\n\n"
        f"POSTING AGE (days since posted, lower is better): {posting_age_days}\n\n"
        f"REQUIRED OUTPUT SCHEMA (each dimension is an object with 'score' and 'reason'):\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        f"EXAMPLE OUTPUT FORMAT:\n{json.dumps(example, indent=2)}\n"
    )
