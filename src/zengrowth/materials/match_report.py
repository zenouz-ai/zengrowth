"""Deterministic material↔JD match and quality report (TA-13, with TA-03/TA-05).

Industry tailoring tools (Jobscan's Match Rate, Teal's Match Score) centre the
loop on one number: how much of the job description's salient vocabulary the
document actually covers, with the gap list alongside it. This module provides
that signal for every generated material — deterministically, with no LLM call
and no spend — plus two quality checks that back the TA-03 prompt rules:

- ``jd_match``: salient JD terms (named entities + requirement keywords) found
  or missing in the material text, with a coverage score.
- ``impact``: how many content lines carry a concrete figure (quantified
  metric+action+result writing converts; grounding gates elsewhere guarantee
  the figures are real).
- ``tells``: buzzword clichés that read as template/AI output ("proven track
  record", "I am writing to apply", ...). The generation prompt bans them; this
  check catches any that slip through.

Report-only by design: a low score never fails generation. The operator sees
the numbers next to the preview and decides — the truth path is untouched.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Job
from .cv_alignment import _content_words, _entity_tokens
from .latex import latex_to_plain

# Words that carry no tailoring signal in a job description: function words plus
# job-ad boilerplate that appears in almost every posting.
_JD_STOPWORDS = frozenset(
    {
        # function words
        "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
        "by", "at", "from", "as", "is", "are", "be", "this", "that", "these",
        "those", "into", "across", "using", "via", "per", "you", "your", "our",
        "their", "its", "it", "we", "i", "than", "then", "while", "will",
        "have", "has", "had", "can", "could", "should", "would", "may", "must",
        "more", "most", "other", "such", "both", "each", "all", "any", "not",
        "also", "well", "who", "what", "when", "where", "how", "which",
        # job-ad boilerplate
        "role", "job", "team", "teams", "work", "working", "works", "years",
        "year", "experience", "experienced", "strong", "excellent", "good",
        "great", "proven", "ability", "abilities", "skill", "skills",
        "knowledge", "understanding", "including", "required", "requirements",
        "requirement", "responsibilities", "responsibility", "preferred",
        "candidate", "candidates", "applicants", "applicant", "opportunity",
        "opportunities", "company", "position", "successful", "ideal",
        "looking", "join", "help", "about", "within", "world", "people",
        "environment", "benefits", "salary", "location", "hybrid", "remote",
        "office", "full", "time", "part", "plus", "equivalent", "related",
        "relevant", "demonstrated", "demonstrable", "track", "record",
    }
)

# Generic acronyms that never need covering (mirrors the grounding allowlist).
_GENERIC_ACRONYMS = frozenset(
    {
        "ceo", "cto", "cio", "coo", "cfo", "cdo", "cmo", "mba", "bsc", "msc",
        "phd", "kpi", "kpis", "okr", "okrs", "roi", "rois", "gdpr", "sla",
        "slas", "faq", "faqs",
    }
)

# Template/AI-tell clichés the TA-03 prompt bans. Checked case-insensitively as
# phrases so ordinary words ("driven demand down 30%") never false-positive.
AI_TELL_PHRASES: tuple[str, ...] = (
    "results-driven",
    "results driven",
    "proven track record",
    "passionate about",
    "seasoned professional",
    "dynamic professional",
    "team player",
    "self-starter",
    "detail-oriented",
    "fast-paced environment",
    "hit the ground running",
    "think outside the box",
    "go-getter",
    "synergy",
    "synergies",
    "leverage my skills",
    "excellent communication skills",
    "i am writing to apply",
    "i am writing to express",
    "i am excited to apply",
    "in today's rapidly evolving",
    "in the ever-evolving",
    "testament to",
)

_DIGIT_RE = re.compile(r"\d")
_LINE_SPLIT_RE = re.compile(r"(?:\n+|(?<=[.!?])\s+)")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]*")
_MAX_TERMS = 30


def _normalise(term: str) -> str:
    """Fold trailing punctuation and simple plurals for matching.

    The shared word regex keeps ``./_-+#`` inside tokens (for "CI/CD",
    "node.js"), which leaves sentence punctuation attached ("pipeline.");
    strip it, then fold plurals so "pipelines" in the JD matches "pipeline".
    """
    term = term.lower().strip("./_-+#")
    return term[:-1] if term.endswith("s") and len(term) > 4 else term


def _jd_focus_text(job: Job) -> str:
    """JD text worth matching: title + summary lists, always merged with raw JD.

    Summary bullets are the primary signal when present, but a thin LLM summary
    can omit tools that still appear in the full description — so the raw JD
    is always appended (capped) rather than suppressed once any list exists.
    """
    parts: list[str] = [job.title or ""]
    if isinstance(job.job_summary, dict):
        for key in ("requirements", "responsibilities", "skills", "tech_stack"):
            raw = job.job_summary.get(key)
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw)
            elif isinstance(raw, str):
                parts.append(raw)
    description = (job.description or "")[:4000]
    if description:
        parts.append(description)
    return " ".join(parts)


def jd_salient_terms(job: Job) -> list[str]:
    """Salient JD vocabulary: named entities first, then requirement keywords.

    Deterministic and capped at ``_MAX_TERMS`` (entities take precedence —
    a named tool or platform in the JD is the strongest tailoring signal),
    keywords ordered by frequency then alphabetically for stable output.
    """
    corpus = _jd_focus_text(job)
    entities = sorted(
        term for term in _entity_tokens(corpus) if term not in _GENERIC_ACRONYMS
    )
    entity_keys = {_normalise(entity) for entity in entities}
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for token in _TOKEN_RE.findall(corpus):
        word = token.lower().strip("./_-+#")
        # Keep letter-led tokens that embed digits (gpt-4, iso27001, llama2).
        # Pure years/percentages never match ``_TOKEN_RE`` (must start with a letter).
        if len(word) < 4 or word in _JD_STOPWORDS:
            continue
        key = _normalise(word)
        if key in entity_keys:
            continue
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, word)
    keywords = [display[key] for key in sorted(counts, key=lambda term: (-counts[term], term))]
    terms = entities + keywords
    return terms[:_MAX_TERMS]


def _material_vocabulary(text: str) -> set[str]:
    words = _content_words(text) | _entity_tokens(text)
    return {_normalise(word) for word in words}


def jd_match_report(text: str, job: Job) -> dict[str, Any]:
    """Jobscan/Teal-style coverage of the JD's salient terms by the material."""
    terms = jd_salient_terms(job)
    if not terms:
        return {"score": None, "matched": [], "missing": [], "term_count": 0}
    vocabulary = _material_vocabulary(text)
    matched = [term for term in terms if _normalise(term) in vocabulary]
    missing = [term for term in terms if _normalise(term) not in vocabulary]
    return {
        "score": round(100 * len(matched) / len(terms)),
        "matched": matched,
        "missing": missing,
        "term_count": len(terms),
    }


def impact_report(text: str) -> dict[str, Any]:
    """How much of the material is quantified: lines carrying a concrete figure."""
    lines = [line.strip() for line in _LINE_SPLIT_RE.split(text or "") if line.strip()]
    quantified = sum(1 for line in lines if _DIGIT_RE.search(line))
    return {"quantified_lines": quantified, "content_lines": len(lines)}


def find_ai_tells(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [phrase for phrase in AI_TELL_PHRASES if phrase in lowered]


def material_quality_report(text: str, job: Job) -> dict[str, Any]:
    """The combined report stored on ``draft_json['quality_report']``."""
    return {
        "jd_match": jd_match_report(text, job),
        "impact": impact_report(text),
        "tells": find_ai_tells(text),
    }


def cv_plain_text(draft_json: dict[str, Any] | None) -> str:
    """Plain prose of a CV draft's editable spans (summary, capabilities, bullets)."""
    if not draft_json:
        return ""
    parts: list[str] = []
    summary = draft_json.get("summary")
    if isinstance(summary, str):
        parts.append(summary)
    for line in draft_json.get("capabilities") or []:
        parts.append(latex_to_plain(str(line)))
    experience = draft_json.get("experience")
    if isinstance(experience, dict):
        for bullets in experience.values():
            if isinstance(bullets, list):
                parts.extend(latex_to_plain(str(bullet)) for bullet in bullets)
    return "\n".join(part for part in parts if part)
