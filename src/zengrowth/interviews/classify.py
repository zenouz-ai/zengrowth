"""Lightweight classifiers for imported interview artifacts.

Intact / iwoca replay found two filing mistakes that made the learning loop
miss hand-made notes: culture write-ups landed as ``company_briefing``, and
Claude Code / practice briefs landed as ``tech_prep_pack``. Close-out
reflections already use stable ``##`` headings. Close-out promote reads Skills
and playbook sections (including imported "durable playbook" headings) and
skips gap diagnoses.
"""

from __future__ import annotations

import re

from .markdown_format import strip_llm_envelope

# Operator often leaves the import-form default (briefing) or files a session
# prompt as a tech pack. Only those two dump types are auto-corrected.
_DUMP_TYPES = frozenset({"company_briefing", "tech_prep_pack"})
_AUTO_APPLY = frozenset({"culture_comparison", "session_prep", "rejection_reflection"})

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^(?:[-*]|\d+[.)])\s+(.+)$", re.MULTILINE)
_CLAIM_CITE_RE = re.compile(r"\s*\[claim-[^\]]+\]\s*$", re.IGNORECASE)
_SKIP_BULLET_RE = re.compile(r"^(tbd|n/?a|none|todo|\.+)$", re.IGNORECASE)

# Portable close-out sections only. Gaps / "what needs to improve" / Library
# todos are process diagnoses, not Approve-facts material.
_SKILL_SECTION_NEEDLES = (
    "skills and knowledge to deepen",
    "skills to deepen",
)
_LEARNING_SECTION_NEEDLES = (
    "reusable learnings",
    "durable playbook",
    "playbook for next",
    "posture for the next",
)
_SKIP_SECTION_NEEDLES = (
    "gaps versus",
    "three gaps",
    "what needs to improve",
    "what we missed",
    "evidence to add",
)
_LIBRARY_TODO_RE = re.compile(
    r"^(write a library note|add to library|ingest into library)\b",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^(?:skill|process)\s*:\s*|^\[(?:skill|process)\]\s*", re.IGNORECASE)

_TITLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "rejection_reflection",
        (
            "rejection reflection",
            "rejection feedback",
            "what the feedback",
        ),
    ),
    (
        "culture_comparison",
        ("culture comparison", "culture vs", "culture versus", "culture notes"),
    ),
    (
        "session_prep",
        (
            "claude code",
            "practice brief",
            "session prompt",
            "runnable prompt",
            "session prep",
            "take-home",
        ),
    ),
    ("journey_summary", ("journey summary",)),
)

_SECTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "rejection_reflection",
        ("gaps versus the bar", "skills and knowledge to deepen"),
    ),
    (
        "journey_summary",
        ("reusable learnings", "timeline of rounds"),
    ),
    (
        "culture_comparison",
        ("headline comparison table", "target company culture"),
    ),
    (
        "session_prep",
        ("runnable prompt", "session goal"),
    ),
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _has_all_headings(markdown: str, headings: tuple[str, ...]) -> bool:
    found = {_norm(title) for title, _body in _iter_sections(markdown)}
    return all(h in found for h in headings)


def _iter_sections(markdown: str) -> list[tuple[str, str]]:
    cleaned = strip_llm_envelope(markdown)
    matches = list(_HEADING_RE.finditer(cleaned))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        sections.append((match.group(1).strip(), cleaned[start:end]))
    return sections


def suggest_internal_material_type(title: str, content: str = "") -> str | None:
    """Best-effort type from title + markdown. ``None`` if there is no clear signal."""
    title_blob = title.lower()
    for material_type, needles in _TITLE_RULES:
        if any(needle in title_blob for needle in needles):
            return material_type
    for material_type, headings in _SECTION_RULES:
        if _has_all_headings(content, headings):
            return material_type
    return None


def apply_import_type_suggestion(
    submitted: str, title: str, content: str
) -> tuple[str, str | None]:
    """Return ``(applied_type, suggested_type)``.

    Auto-corrects only when the operator left a dump type and the suggestion is
    one of the iwoca misfiles. Explicit interviewer/debrief/etc. choices stick.
    """
    suggested = suggest_internal_material_type(title, content)
    if (
        suggested
        and submitted in _DUMP_TYPES
        and suggested in _AUTO_APPLY
        and suggested != submitted
    ):
        return suggested, suggested
    return submitted, suggested


def _section_category(title: str) -> str | None:
    """Map a heading to a learning category, or ``None`` to skip the section."""
    n = _norm(title)
    if any(needle in n for needle in _SKIP_SECTION_NEEDLES):
        return None
    if any(needle in n for needle in _SKILL_SECTION_NEEDLES):
        return "process_skill"
    if any(needle in n for needle in _LEARNING_SECTION_NEEDLES):
        return "interview_learning"
    return None


def extract_closeout_learnings(
    markdown: str, *, max_items: int = 12
) -> list[tuple[str, str]]:
    """Pull portable ``(category, bullet)`` pairs from close-out sections.

    Skills first, then next-interview playbook lines. Skips gap diagnoses,
    "what needs to improve", and Library-ingest todos.
    """
    skills: list[tuple[str, str]] = []
    learnings: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, body in _iter_sections(markdown):
        default_category = _section_category(title)
        if default_category is None:
            continue
        for raw in _BULLET_RE.findall(body):
            text = _CLAIM_CITE_RE.sub("", raw).strip().strip("*").strip()
            text = re.sub(r"\*\*", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            if "|" in text or len(text) < 32:
                continue
            if _SKIP_BULLET_RE.match(text) or _LIBRARY_TODO_RE.match(text):
                continue
            category = _category_for_bullet(text, default_category)
            text = _PREFIX_RE.sub("", text).strip()
            if len(text) < 32:
                continue
            key = _norm(text)
            if key in seen:
                continue
            seen.add(key)
            bucket = skills if category == "process_skill" else learnings
            bucket.append((category, text))
    return (skills + learnings)[:max_items]


def _category_for_bullet(text: str, default: str) -> str:
    lower = text.lower()
    if lower.startswith("skill:") or lower.startswith("[skill]"):
        return "process_skill"
    if lower.startswith("process:") or lower.startswith("[process]"):
        return "interview_learning"
    return default
