"""CV alignment: fit-tier grounding, evidence ranking, gap detection, summary compose."""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import Settings
from ..models import Job
from .evidence import ParsedEvidence

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]*")
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{3,})\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Shared with ``generator`` (imported as ``GENERIC_ACRONYMS``) so the CV gates
# and the cover-letter/answer gates use one definition.
GENERIC_ACRONYMS = frozenset(
    {
        "CEO", "CTO", "CIO", "COO", "CFO", "CDO", "CMO", "MBA", "BSC", "MSC",
        "PHD", "KPI", "KPIS", "OKR", "OKRS", "ROI", "ROIS", "GDPR", "SLA",
        "SLAS", "FAQ", "FAQS",
    }
)

# Priority-tier domain synonyms — alignment vocabulary only, not employers/metrics.
_CV_SYNONYMS: dict[str, frozenset[str]] = {
    "pharma": frozenset({"pharmaceutical", "pharmaceuticals"}),
    "pharmaceutical": frozenset({"pharma"}),
    "pharmaceuticals": frozenset({"pharma"}),
    "healthcare": frozenset({"health", "medical"}),
    "health": frozenset({"healthcare", "medical"}),
    "medical": frozenset({"healthcare", "health"}),
    "medtech": frozenset({"healthcare", "health", "medical"}),
}


def _content_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def entity_tokens(text: str) -> set[str]:
    """Named-entity tokens: CamelCase names and 3+-char acronyms (TP-01b)."""
    return {m.lower() for m in _ENTITY_RE.findall(text)}


_entity_tokens = entity_tokens


def cv_grounding_profile(job: Job, settings: Settings) -> str:
    score = job.fit_score or 0
    if score >= settings.cv_priority_fit_threshold:
        return "priority"
    if score >= settings.cv_aligned_fit_threshold:
        return "aligned"
    return "strict"


def _job_header(job: Job) -> list[str]:
    return [
        job.company or "",
        job.title or "",
        job.location or "",
        job.hybrid_policy or "",
        str(job.compensation or ""),
    ]


def job_relevance_corpus(job: Job, *, include_rationale: bool = False) -> str:
    """Everything the JD says, for *relevance* (ranking, gap detection) only.

    Never use this as a grounding allowlist: JD text describes what the employer
    wants, not what the candidate has done.
    """
    parts = [*_job_header(job), (job.description or "")[:4000]]
    if job.job_summary:
        parts.append(json.dumps(job.job_summary, default=str))
    if include_rationale and job.score_rationale:
        parts.append(json.dumps(job.score_rationale, default=str))
    return " ".join(parts)


def cv_grounding_corpus(job: Job, profile: str) -> str:
    """Job-side text a tailored CV may echo, by fit tier (TP-16).

    ``strict`` allows only the job header (company, title, location, hybrid
    policy, stated compensation) — the same job context cover letters get.
    ``aligned`` / ``priority`` additionally allow the JD text and summary so a
    high-fit CV can mirror the posting's vocabulary; this is a deliberate,
    documented widening, and the operator reviews the result. The scorer's
    rationale is never included: it is model output, and model output must not
    ground model output.
    """
    parts = _job_header(job)
    if profile in {"aligned", "priority"}:
        parts.append((job.description or "")[:4000])
        if job.job_summary:
            parts.append(json.dumps(job.job_summary, default=str))
    return " ".join(parts)


def expand_grounding_words(words: set[str], profile: str) -> set[str]:
    if profile != "priority":
        return words
    expanded = set(words)
    for word in words:
        expanded.update(_CV_SYNONYMS.get(word, ()))
    return expanded


def cv_entity_allowlist(corpus: str, job: Job, profile: str) -> set[str]:
    allowed = _entity_tokens(corpus) | {a.lower() for a in GENERIC_ACRONYMS}
    if profile == "priority" and job.company:
        allowed |= _entity_tokens(job.company)
        allowed |= {w.lower() for w in job.company.split() if len(w) >= 3}
    return allowed


def split_summary_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]


def rank_evidence_for_job(evidence: list[ParsedEvidence], job: Job) -> list[dict[str, Any]]:
    """Rank verified claims by token overlap with the JD (deterministic, no LLM)."""
    jd_words = {
        w for w in _content_words(job_relevance_corpus(job, include_rationale=True)) if len(w) >= 3
    }
    ranked: list[dict[str, Any]] = []
    for item in evidence:
        claim_corpus = f"{item.claim_text} {item.source_role or ''} {' '.join(item.tags)}"
        claim_words = _content_words(claim_corpus)
        matched = sorted(jd_words & claim_words)
        ranked.append(
            {
                "id": item.id,
                "category": item.category,
                "claim": item.claim_text,
                "jd_match": matched,
                "score": len(matched),
            }
        )
    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    return ranked


def select_relevant_evidence(
    evidence: list[ParsedEvidence], job: Job, *, limit: int
) -> list[ParsedEvidence]:
    """Relevance-rank the verified-claim pool against the JD, then cap to ``limit``.

    RET-01 fix. Previously the bank was truncated to the top-N *by confidence*
    before relevance was considered (`_load_evidence_with_source`), so a
    highly-relevant but lower-confidence claim ranked beyond the cap was dropped
    before ranking — invisible to the generator and to the grounding gate. We now
    rank the full pool by JD overlap and keep the top ``limit``. Ties (and
    zero-overlap fillers) fall back to the deterministic claim-id order already
    used by :func:`rank_evidence_for_job`, so selection stays stable across runs.

    The returned set is used as *both* the prompt content and the grounding
    corpus, so the safety gate stays exactly as tight as before (``limit``
    claims) — only relevance-chosen instead of confidence-chosen.
    """
    if limit <= 0 or len(evidence) <= limit:
        return evidence
    ranked = rank_evidence_for_job(evidence, job)
    by_id = {item.id: item for item in evidence}
    selected = [by_id[row["id"]] for row in ranked[:limit] if row["id"] in by_id]
    return selected


def detect_alignment_gaps(
    evidence: list[ParsedEvidence], job: Job, profile: str = "strict"
) -> list[dict[str, Any]]:
    """JD terms with weak or no verified-claim support.

    Gap detection always reads the whole JD (it is a relevance question, not a
    grounding one), so ``profile`` is accepted for call-site compatibility and
    deliberately unused.
    """
    jd_corpus = job_relevance_corpus(job)
    ev_corpus = " ".join(f"{e.claim_text} {e.source_role or ''}" for e in evidence)
    ev_words = _content_words(ev_corpus)
    ev_entities = _entity_tokens(ev_corpus)
    ranked = rank_evidence_for_job(evidence, job)
    closest_id = ranked[0]["id"] if ranked else None
    closest_claim = ranked[0]["claim"] if ranked else None

    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()

    for ent in sorted(_entity_tokens(jd_corpus) - ev_entities):
        if ent.upper() in GENERIC_ACRONYMS or ent in seen:
            continue
        seen.add(ent)
        gaps.append(
            {
                "term": ent,
                "kind": "entity",
                "status": "missing",
                "closest_claim_id": closest_id,
                "closest_claim_text": closest_claim,
                "suggestion": (
                    f"Add a verified claim that mentions {ent} if that reflects your experience."
                ),
            }
        )

    req_terms: list[str] = []
    if isinstance(job.job_summary, dict):
        for key in ("requirements", "responsibilities"):
            raw = job.job_summary.get(key)
            if isinstance(raw, list):
                req_terms.extend(str(item) for item in raw[:8])

    for req in req_terms:
        for word in sorted(w for w in _content_words(req) if len(w) >= 5):
            if word in ev_words or word in seen:
                continue
            seen.add(word)
            gaps.append(
                {
                    "term": word,
                    "kind": "requirement",
                    "status": "weak",
                    "closest_claim_id": closest_id,
                    "closest_claim_text": closest_claim,
                    "suggestion": (
                        f"The JD emphasises “{word}”; widen your evidence bank with a verified "
                        "claim if you can support it."
                    ),
                }
            )
            if len(gaps) >= 12:
                return gaps
    return gaps


def compose_summary_from_claims(
    ranked: list[dict[str, Any]],
    evidence: list[ParsedEvidence],
    *,
    max_words: int = 150,
) -> str:
    """Build a plain summary from verified claim text only (no LLM)."""
    by_id = {item.id: item for item in evidence}
    parts: list[str] = []
    word_count = 0
    for row in ranked:
        if row["score"] <= 0 and parts:
            break
        claim = by_id.get(row["id"])
        if claim is None:
            continue
        text = claim.claim_text.strip()
        if not text:
            continue
        words = len(text.split())
        if word_count + words > max_words:
            break
        parts.append(text if text.endswith((".", "!", "?")) else f"{text}.")
        word_count += words
    return " ".join(parts)


def experience_alignment_notes(
    job: Job,
    evidence: list[ParsedEvidence],
    original: dict[str, Any],
    experience: dict[str, list[str]],
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Notes when experience bullets were reordered or JD gaps suggest approximate fit."""
    ranked = rank_evidence_for_job(evidence, job)
    top = ranked[0] if ranked else None
    notes: list[dict[str, Any]] = []
    gap_hint = (
        f" JD terms without verified evidence: {', '.join(g['term'] for g in gaps[:3])}."
        if gaps
        else ""
    )
    for role_key, bullets in experience.items():
        try:
            role_index = int(role_key)
        except ValueError:
            continue
        if role_index >= len(original.get("experience", [])):
            continue
        source = original["experience"][role_index]
        if bullets != source:
            notes.append(
                {
                    "role_index": role_index,
                    "alignment": "approximate" if gaps else "reordered",
                    "note": (
                        "Bullets reordered toward JD priorities using verified template content."
                        + gap_hint
                    ).strip(),
                    "closest_claim_id": top["id"] if top else None,
                }
            )
    return notes
