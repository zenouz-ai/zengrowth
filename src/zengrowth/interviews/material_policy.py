"""Interview material content policy — schemas, quality gates, learning-loop helpers.

Derived from the Intact Director of AI journey comparison (generated vs imported).
Three tiers: job foundation, round prep, debrief/learning pack.
"""

from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from ..models import GeneratedMaterial
from .markdown_format import strip_llm_envelope

PACK_TYPES = ("company_briefing", "interviewer_pack", "tech_prep_pack", "final_round_pack")
PREP_PACK_TYPES = ("interviewer_pack", "tech_prep_pack", "final_round_pack")

FOUNDATION_SECTIONS: list[str] = [
    "Who They Are",
    "The Org Structure That Matters",
    "Key Leaders and Interviewers",
    "Current Technology Stack",
    "What They Need You to Build — Year One Plan",
    "Agentic AI — What Can Be Built on This Stack",
    "Key Numbers to Know",
    "The Insurance Value Chain (Know This)",
    "Your Evidence to Lead With",
    "Compensation Range and Your Alignment",
]

PREP_SHARED_SECTIONS: list[str] = [
    "Anchor Sentence",
    "Who Is In The Room",
    "Core Questions",
    "Your Evidence To Lead With",
    "Questions To Ask Them",
    "Checklist",
    "Logistics",
]

# Extra sections keyed by (pack_type, round_type value).
_ROUND_PREP_EXTRAS: dict[tuple[str, str], list[str]] = {
    ("interviewer_pack", "recruiter_screen"): [
        "Seniority Bridge",
        "What The Recruiter Is Gating",
    ],
    ("interviewer_pack", "leadership_panel"): [
        "Frameworks To Know Cold",
        "Executive Opening (2 Minutes)",
        "When You Drift Too Technical",
    ],
    ("interviewer_pack", "team"): [
        "Prior Round Intelligence",
        "Stakeholder Map",
    ],
    ("interviewer_pack", "other"): [
        "Prior Round Intelligence",
    ],
    ("tech_prep_pack", "technical"): [
        "Likely Technical Themes",
        "Concepts To Know Cold",
        "Architecture and Stack Talking Points",
        "Mock Performance Summary",
    ],
    ("final_round_pack", "final_round"): [
        "Where the Process Stands",
        "What the Final Round Decides",
        "Learnings from Earlier Rounds",
        "Negotiation and Compensation Posture",
        "CIO vs CDO Dynamic",
    ],
}

DEBRIEF_SECTIONS: list[str] = [
    "Goal",
    "Outcome",
    "What Went Well",
    "Gaps To Close",
    "New Organisational Intelligence",
    "Learnings For The Next Stage",
    "Suggested Follow-Up Actions",
]

LINE_BUDGETS: dict[str, tuple[int, int]] = {
    "company_briefing": (200, 450),
    "interviewer_pack": (150, 380),
    "tech_prep_pack": (150, 380),
    "final_round_pack": (150, 380),
    "debrief": (80, 200),
}

_PREP_MATERIAL_TYPES = frozenset(PREP_PACK_TYPES)

_QUESTION_RE = re.compile(r"^###\s*Q\d+", re.MULTILINE | re.IGNORECASE)
_GAP_RE = re.compile(r"^###\s*Gap\s*\d+", re.MULTILINE | re.IGNORECASE)
_CLAIM_ID_RE = re.compile(r"\[claim-[A-Za-z0-9_.:-]+\]")


def resolve_round_type(interview: Any | None) -> str:
    if interview is None:
        return "other"
    rt = getattr(interview, "round_type", None)
    if rt is None:
        return "other"
    return rt.value if hasattr(rt, "value") else str(rt)


def pack_sections(pack_type: str, *, round_type: str | None = None) -> list[str]:
    """Section headings the LLM must produce for this pack."""
    if pack_type == "company_briefing":
        return list(FOUNDATION_SECTIONS)
    rt = round_type or "other"
    extras = _ROUND_PREP_EXTRAS.get((pack_type, rt), [])
    if not extras and pack_type == "interviewer_pack":
        extras = _ROUND_PREP_EXTRAS.get(("interviewer_pack", "other"), [])
    seen: set[str] = set()
    ordered: list[str] = []
    for section in extras + PREP_SHARED_SECTIONS:
        key = section.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(section)
    return ordered


def missing_sections(markdown: str, sections: list[str]) -> list[str]:
    lower = markdown.lower()
    return [s for s in sections if s.lower() not in lower]


def count_numbered_questions(markdown: str) -> int:
    return len(_QUESTION_RE.findall(markdown))


def count_gap_blocks(markdown: str) -> int:
    return len(_GAP_RE.findall(markdown))


def count_claim_citations(markdown: str) -> int:
    return len(_CLAIM_ID_RE.findall(markdown))


def line_count(markdown: str) -> int:
    return len(markdown.splitlines())


def quality_warnings(
    markdown: str,
    *,
    material_kind: str,
    pack_type: str | None = None,
    round_type: str | None = None,
) -> list[str]:
    """Non-fatal quality signals logged after generation."""
    warnings: list[str] = []
    body = strip_llm_envelope(markdown)
    lines = line_count(body)

    if material_kind == "debrief":
        budget = LINE_BUDGETS["debrief"]
        if lines > budget[1]:
            warnings.append(f"debrief exceeds line budget ({lines} > {budget[1]})")
        if count_gap_blocks(body) < 1:
            warnings.append("debrief missing gap blocks (### Gap 1)")
        if "answer to learn" not in body.lower():
            warnings.append("debrief missing 'answer to learn' scripts")
        return warnings

    pt = pack_type or "interviewer_pack"
    budget = LINE_BUDGETS.get(pt, (150, 380))
    if lines > budget[1]:
        warnings.append(f"pack exceeds line budget ({lines} > {budget[1]})")

    if pt != "company_briefing":
        if "anchor sentence" not in body.lower():
            warnings.append("prep pack missing Anchor Sentence section")
        q_count = count_numbered_questions(body)
        if q_count < 5:
            warnings.append(f"prep pack has only {q_count} numbered questions (want >= 5)")
    return warnings


def extract_material_snippets(body: str) -> dict[str, Any]:
    """Pull reusable snippets from prior materials for the learning loop."""
    cleaned = strip_llm_envelope(body)
    snippets: dict[str, Any] = {}

    anchor_match = re.search(
        r"##\s*Anchor Sentence\s*\n+>\s*\"?([^\"\n]+)\"?",
        cleaned,
        re.IGNORECASE,
    )
    if anchor_match:
        snippets["anchor_sentence"] = anchor_match.group(1).strip()

    gaps = re.findall(
        r"###\s*Gap\s*\d+\s*[—–-]\s*([^\n]+)(.*?)(?=###\s*Gap|\Z)",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if gaps:
        snippets["gaps"] = [
            {"title": title.strip(), "detail": detail.strip()[:800]} for title, detail in gaps[:3]
        ]

    intel_match = re.search(
        r"##\s*New Organisational Intelligence\s*\n+(.*?)(?=\n##\s|\Z)",
        cleaned,
        re.DOTALL | re.IGNORECASE,
    )
    if intel_match:
        snippets["new_intelligence"] = intel_match.group(1).strip()[:1200]

    questions = _QUESTION_RE.findall(cleaned)
    if questions:
        snippets["question_count"] = len(questions)

    return snippets


def _body_for_prompt(text: str | None, *, max_chars: int) -> str | None:
    if not text:
        return None
    stripped = strip_llm_envelope(text)
    return stripped[:max_chars] if stripped.strip() else None


def _pick_better(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    existing_len = len(existing.get("content") or "")
    candidate_len = len(candidate.get("content") or "")
    # Prefer imported-style gap-rich debriefs when longer.
    if candidate.get("status") == "imported" and candidate_len > existing_len:
        return candidate
    if existing.get("status") != "imported" and candidate_len > existing_len * 1.2:
        return candidate
    return existing


def load_prior_debriefs(
    session: Session,
    job_id: int,
    *,
    limit: int = 4,
    max_chars: int = 4000,
) -> list[dict[str, Any]]:
    """Latest debrief per interview round (INT-04), body stripped of YAML envelope."""
    from ..materials.files import read_text_content

    rows = list(
        session.exec(
            select(GeneratedMaterial)
            .where(
                GeneratedMaterial.job_id == job_id,
                GeneratedMaterial.material_type == "debrief",
            )
            .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
        )
    )
    by_round: dict[int | None, dict[str, Any]] = {}
    for row in rows:
        key = row.interview_id
        if key in by_round and key is not None:
            continue
        raw = read_text_content(row)
        content = _body_for_prompt(raw, max_chars=max_chars)
        if not content:
            continue
        entry = {
            "title": row.title,
            "date": (row.effective_date or row.created_at).date().isoformat(),
            "status": row.status,
            "content": content,
            "snippets": extract_material_snippets(content),
        }
        by_round[key] = _pick_better(by_round.get(key), entry)

    picked = list(by_round.values())[:limit]
    return picked


def load_prior_prep_materials(
    session: Session,
    job_id: int,
    *,
    limit: int = 4,
    max_chars: int = 3500,
) -> list[dict[str, Any]]:
    """Latest prep pack per round (generated or imported), for the learning loop."""
    rows = list(
        session.exec(
            select(GeneratedMaterial)
            .where(
                GeneratedMaterial.job_id == job_id,
                GeneratedMaterial.material_type.in_(_PREP_MATERIAL_TYPES),  # type: ignore[attr-defined]
            )
            .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
        )
    )
    by_key: dict[tuple[int | None, str], dict[str, Any]] = {}
    for row in rows:
        dedup_key = (row.interview_id, row.material_type)
        if dedup_key in by_key:
            continue
        from ..materials.files import read_text_content

        raw = read_text_content(row)
        content = _body_for_prompt(raw, max_chars=max_chars)
        if not content:
            continue
        entry = {
            "title": row.title,
            "material_type": row.material_type,
            "interview_id": row.interview_id,
            "date": (row.effective_date or row.created_at).date().isoformat(),
            "status": row.status,
            "content": content,
            "snippets": extract_material_snippets(content),
        }
        by_key[dedup_key] = _pick_better(by_key.get(dedup_key), entry)

    return list(by_key.values())[:limit]


def find_enhance_source(
    session: Session,
    job_id: int,
    *,
    pack_type: str,
    interview_id: int | None,
) -> GeneratedMaterial | None:
    """Latest imported prep pack to enhance (same job, type, optional round)."""
    stmt = (
        select(GeneratedMaterial)
        .where(
            GeneratedMaterial.job_id == job_id,
            GeneratedMaterial.material_type == pack_type,
            GeneratedMaterial.status == "imported",
        )
        .order_by(GeneratedMaterial.created_at.desc())  # type: ignore[union-attr]
    )
    rows = list(session.exec(stmt))
    for row in rows:
        if interview_id is not None and row.interview_id not in (interview_id, None):
            continue
        return row
    return None


PACK_SYSTEM_PROMPT = """You are a senior career coach preparing a candidate for a job interview.
Write a focused, practical preparation pack in Markdown.

Priority order for facts (highest first):
1. Transcript, notes, and prior_round_materials on this job
2. Verified evidence bank (cite claim ids inline)
3. Web search for net-new company/interviewer facts only

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
  Do NOT include YAML frontmatter or a top-level `#` title.
- Open with `> [!tip] Read this first: {one sentence round intent}.`
- Under Core Questions use `### Q1 — {topic} ({interviewer name})` through at least Q5 with:
  - Likely phrasing
  - Strong answer outline (bullets)
  - Evidence: [claim-id] when citing your experience
- For round prep packs: do NOT repeat full company history from prior foundation briefings;
  reference them briefly and focus on this round's script.
- Target 200-350 lines for round prep; 250-400 for company foundation. Be concise and actionable.
- Company facts from web search must be explicit when inferred.
- Never invent candidate employers, dates, metrics, or qualifications.
- Avoid em dashes; no wrapping code fence around the whole document."""

DEBRIEF_SYSTEM_PROMPT = """You are a senior career coach reviewing a candidate's interview performance.
Write an honest, specific debrief in Markdown grounded in the transcript or notes.

Rules:
- Return ONLY the document body. Use `##` headings exactly matching required_sections, in order.
  Do NOT include YAML frontmatter or a top-level `#` title.
- Under Gaps To Close use at most 3 blocks: `### Gap 1 — {title}` with bullets:
  - What happened: (quote a short phrase from the transcript)
  - Why it matters:
  - Answer to learn: (script the candidate can say next time)
- New Organisational Intelligence: facts learned in-room only (not web search).
- Learnings For The Next Stage: numbered list, reusable in the next prep pack.
- Target 120-180 lines. Be candid but concise.
- Avoid em dashes; no wrapping code fence around the whole document."""

ENHANCE_SYSTEM_APPEND = """
You are ENHANCING an existing operator-authored prep pack skeleton.
Keep the skeleton's structure, anchor sentence, numbered questions, and checklist.
Add verified evidence citations [claim-id] in Your Evidence and Core Questions.
Add a ## Sources section only for net-new web facts not already in the skeleton.
Do not remove or shorten existing question prep; merge and enrich."""
