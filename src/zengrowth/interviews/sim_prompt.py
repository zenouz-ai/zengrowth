"""Voice-interviewer simulation prompt (INT-05).

Deterministic composition — no LLM call. Produces a self-contained prompt the
operator pastes into ChatGPT Voice, a Claude session, or any capable assistant
to run a realistic mock interview for a specific round. Model-agnostic per
VISION Module 6.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import (
    ActorType,
    GeneratedMaterial,
    Interview,
    InterviewRoundType,
    Job,
    MaterialAudience,
)

_ROUND_FOCUS: dict[InterviewRoundType, str] = {
    InterviewRoundType.recruiter_screen: (
        "an initial recruiter screen: motivation, career narrative, logistics, "
        "compensation expectations, and communication clarity"
    ),
    InterviewRoundType.hiring_manager: (
        "a hiring-manager interview: role fit, delivery track record, how the "
        "candidate would approach the first 90 days, and working style"
    ),
    InterviewRoundType.leadership_panel: (
        "a senior leadership panel: strategy, stakeholder management, executive "
        "communication, and organisational leadership"
    ),
    InterviewRoundType.technical: (
        "a technical deep-dive: architecture and MLOps choices, GenAI/LLM systems, "
        "evaluation and governance, trade-off reasoning, and hands-on credibility"
    ),
    InterviewRoundType.team: (
        "a team/peer interview: collaboration, mentoring, cross-functional influence, "
        "and how the candidate raises the bar for the people around them"
    ),
    InterviewRoundType.final_round: (
        "a final executive round: vision, commercial impact, risk appetite, "
        "negotiation posture, and whether to make the hire"
    ),
    InterviewRoundType.other: "a general interview across motivation, experience, and fit",
}


def _job_brief(job: Job) -> dict[str, Any]:
    summary = job.job_summary or {}
    return {
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "role_overview": summary.get("role_overview"),
        "responsibilities": summary.get("responsibilities"),
        "requirements": summary.get("requirements"),
    }


def build_sim_prompt(
    job: Job,
    *,
    interview: Interview | None = None,
    evidence_topics: list[str] | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    round_type = interview.round_type if interview else InterviewRoundType.other
    focus = _ROUND_FOCUS[round_type]
    participants = interview.participants if interview else None
    persona = (
        "Adopt the perspective of the named interviewers below where given; otherwise "
        "play a realistic senior interviewer for this round."
    )
    interviewers = (
        "\n".join(
            f"- {p.get('name', 'Interviewer')}"
            + (f" ({p['role']})" if p.get("role") else "")
            for p in participants
        )
        if participants
        else "- (not named — invent one realistic interviewer for this round)"
    )
    topics = (
        "\n".join(f"- {topic}" for topic in evidence_topics[:12])
        if evidence_topics
        else "- (ask the candidate to briefly outline their background first)"
    )
    job_json = json.dumps(_job_brief(job), indent=2, default=str)
    return f"""# Mock interviewer — {job.company}, {job.title}

Copy everything below into a voice-capable assistant (ChatGPT Voice, a Claude
session, or similar) and start the conversation.

---

You are my mock interviewer. Run {focus}.

{persona}

INTERVIEWERS:
{interviewers}

THE ROLE:
{job_json}

MY BACKGROUND THEMES (probe these, and challenge me to quantify impact):
{topics}

HOW TO RUN THE SESSION:
1. Stay in character as the interviewer. Ask ONE question at a time and wait
   for my answer.
2. Ask realistic, role- and company-specific questions for this round; mix
   planned questions with follow-ups that dig into my actual answers.
3. After each of my answers, break character briefly to coach me: score the
   answer 1-10, say what was strong, what was weak or waffly, and give a
   tighter model answer in my own claimed experience (never invent facts I
   did not state).
4. Push me to be concise: flag any answer over ~90 seconds, filler phrases,
   and missing quantified outcomes (metric + action + result).
5. Every 4-5 questions, summarise my trend: what is improving, what still
   needs work.
6. End when I say "wrap up": give an overall score, my three biggest risks
   for the real interview, and the three answers I must rehearse again.

Begin by greeting me as the interviewer and asking your first question.
"""


def generate_sim_prompt(
    session: Session,
    job: Job,
    *,
    interview: Interview | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    """Compose and record the simulator prompt as an internal material."""
    settings = settings or get_settings()
    from ..materials.cv_alignment import select_relevant_evidence
    from ..materials.generator import (
        MATERIALS_ROOT,
        _load_evidence_with_source,
        _next_version,
    )

    pool, _source = _load_evidence_with_source(session, limit=settings.evidence_candidate_pool)
    evidence = select_relevant_evidence(pool, job, limit=12)
    topics = [item.claim_text for item in evidence]
    document = build_sim_prompt(job, interview=interview, evidence_topics=topics, settings=settings)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    out_dir = MATERIALS_ROOT / str(job.id) / f"{stamp}-sim-prompt"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "interviewer_sim_prompt.md"
    md_path.write_text(document, encoding="utf-8")

    round_label = (
        (interview.title or interview.round_type.value.replace("_", " ")) if interview else "general"
    )
    version = _next_version(session, job.id or 0, "interviewer_sim_prompt")
    material = GeneratedMaterial(
        job_id=job.id or 0,
        interview_id=interview.id if interview else None,
        material_type="interviewer_sim_prompt",
        audience=MaterialAudience.internal,
        title=f"Interview simulator — {round_label}",
        markdown_path=str(md_path),
        evidence_ids=[item.id for item in evidence],
        version=version,
        status="created_markdown",
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.system,
        action="generate_interviewer_sim_prompt",
        entity_type="job",
        entity_id=job.id,
        detail={
            "material_id": material.id,
            "interview_id": interview.id if interview else None,
            "evidence_topics": len(topics),
            "version": version,
        },
    )
    return material
