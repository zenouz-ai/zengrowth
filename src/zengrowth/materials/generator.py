"""Evidence-grounded CV, cover letter, and answer generation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session, func, select

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import ActorType, ClaimVerificationState, EvidenceClaim, GeneratedMaterial, Job
from ..observability.client import InstrumentedLLM, build_instrumented_llm
from ..observability.tracing import pipeline_run
from .cv_alignment import (
    compose_summary_from_claims,
    cv_entity_allowlist,
    cv_grounding_corpus,
    cv_grounding_profile,
    detect_alignment_gaps,
    expand_grounding_words,
    experience_alignment_notes,
    rank_evidence_for_job,
    select_relevant_evidence,
    split_summary_sentences,
)
from .cv_diff import summarize_cv_changes
from .evidence import ParsedEvidence, load_evidence_files
from .latex import classify_cv_fit, compile_pdf, escape_latex, latex_to_plain, measure_pdf_extent
from .match_report import cv_plain_text, material_quality_report
from .names import material_export_basename

SOURCE_OF_TRUTH = Path("docs/career/processed/source_of_truth.md")
CV_SOURCE = Path("docs/career/processed/cv_source.tex")
MATERIALS_ROOT = Path("data/materials")

SYSTEM_PROMPT = """You generate factual, evidence-grounded career materials.
Return exactly one JSON object and nothing else. Every claim must be grounded in the provided evidence IDs. Do not invent employment history, metrics, employers, dates, or qualifications."""


class _MaterialClient(Protocol):
    def generate(self, system: str, user: str, model: str, *, operation_name: str = ...) -> dict[str, Any]: ...

    def complete_text(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 8000,
        *,
        operation_name: str = ...,
    ) -> str: ...


class MaterialDraft(BaseModel):
    title: str
    summary: str | None = None
    bullets: list[str] = Field(default_factory=list)
    body: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("bullets", "evidence_ids", mode="before")
    @classmethod
    def _coerce_null_lists(cls, value: Any) -> Any:
        return [] if value is None else value


class CvTailoring(BaseModel):
    """Structure-preserving CV tailoring against ``cv_source.tex``.

    ``summary`` is rewritten plain prose; ``capabilities`` and ``experience``
    are lightly reworded / reordered copies of the template's existing lines
    (same counts), validated before they are rendered.
    """

    title: str = "Tailored CV"
    summary: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    experience: dict[str, list[str]] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class InstrumentedMaterialClient:
    def __init__(self, llm: InstrumentedLLM, *, session: Session | None = None, entity_id: int | None = None) -> None:
        self._llm = llm
        self._session = session
        self._entity_id = entity_id

    def generate(self, system: str, user: str, model: str, *, operation_name: str = "generate_material") -> dict[str, Any]:
        return self._llm.chat_json(
            system=system,
            user=user,
            model=model,
            max_tokens=2500,
            operation_name=operation_name,
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
        )

    def complete_text(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 8000,
        *,
        operation_name: str = "complete_material_text",
    ) -> str:
        return self._llm.complete_text(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            operation_name=operation_name,
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
        )


def _build_client(settings: Settings, session: Session | None = None, entity_id: int | None = None) -> _MaterialClient:
    return InstrumentedMaterialClient(build_instrumented_llm(settings), session=session, entity_id=entity_id)


INSTRUCTION_SYSTEM_TEX = """You are an expert LaTeX editor for job-application documents.
Apply the operator's revision instruction to the document below. Preserve the documentclass,
preamble, fonts, and overall house style; keep the LaTeX valid and compiling; and keep CVs within
two pages. Do not invent employers, dates, qualifications, or metrics that are not supported by the
operator's instruction or the evidence bank. Return ONLY the full revised LaTeX document, with no
commentary and no markdown code fences."""

INSTRUCTION_SYSTEM_MD = """You are an expert editor for job-application answers.
Apply the operator's revision instruction to the answer below, keeping it truthful and grounded.
Return ONLY the revised answer text in Markdown, with no commentary and no code fences."""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def _instruction_tex_prompt(
    material_type: str, instruction: str, current_tex: str, evidence: list[ParsedEvidence]
) -> str:
    return (
        f"Revision instruction:\n{instruction}\n\n"
        f"Document type: {material_type}\n\n"
        f"Current LaTeX document:\n{current_tex}\n\n"
        f"Evidence bank (use only if the instruction asks you to add grounded content):\n"
        f"{json.dumps(_evidence_payload(evidence), indent=2)}"
    )


def _instruction_md_prompt(instruction: str, current_md: str, evidence: list[ParsedEvidence]) -> str:
    return (
        f"Revision instruction:\n{instruction}\n\n"
        f"Current answer:\n{current_md}\n\n"
        f"Evidence bank (use only if the instruction asks you to add grounded content):\n"
        f"{json.dumps(_evidence_payload(evidence), indent=2)}"
    )


FIT_SYSTEM_TEX = """You are a LaTeX editor. The CV below currently runs onto too many pages.
Shorten it so it fills close to two full pages (about 1.85-1.98 pages) without overflowing onto a
third page, while preserving the documentclass, preamble, fonts, house style, and all section
headers. Tighten prose, trim the least-important wording and the weakest bullets, and remove
redundancy, but keep the strongest evidence-grounded achievements. Do not invent content or change
employers, dates, or metrics. Return ONLY the full revised LaTeX document, with no commentary and no
markdown code fences."""

LOOSEN_SYSTEM_TEX = """You are a LaTeX typographer. The CV below is slightly too short. Make it fill
close to two full pages (about 1.85-1.98 pages) without overflowing onto a third page by adjusting
ONLY typography and spacing: line spacing, paragraph spacing, list spacing, section spacing, font
size, or margins. Do NOT change, add, or remove any wording, bullets, employers, dates, or metrics.
Preserve the documentclass structure and all section headers. Return ONLY the full revised LaTeX
document, with no commentary and no markdown code fences."""


def _pages_value(page_count: int, page_fill: float | None) -> str:
    if page_fill is None:
        return f"{page_count}"
    return f"{(page_count - 1) + page_fill:.2f}"


def _shorten_prompt(current_tex: str, page_count: int, page_fill: float | None) -> str:
    return (
        f"The compiled CV is about {_pages_value(page_count, page_fill)} pages but must fill close to "
        f"two full pages (1.85-1.98) without spilling onto a third. Trim it to fit.\n\n"
        f"Current LaTeX document:\n{current_tex}"
    )


def _loosen_prompt(current_tex: str, page_count: int, page_fill: float | None) -> str:
    return (
        f"The compiled CV is only about {_pages_value(page_count, page_fill)} pages. Adjust spacing "
        f"and typography only so it fills close to two full pages (1.85-1.98) without overflowing.\n\n"
        f"Current LaTeX document:\n{current_tex}"
    )


def _valid_tex(revised: str, current_tex: str) -> str:
    if "\\begin{document}" not in revised and "\\documentclass" not in revised:
        return current_tex
    return revised


def _shorten_cv_tex(
    current_tex: str, page_count: int, page_fill: float | None, *, settings: Settings, client: Any
) -> str:
    revised = _strip_code_fence(
        client.complete_text(
            FIT_SYSTEM_TEX,
            _shorten_prompt(current_tex, page_count, page_fill),
            settings.scoring_model,
            operation_name="cv_fit_shorten",
        )
    )
    return _valid_tex(revised, current_tex)


def _loosen_cv_spacing(
    current_tex: str, page_count: int, page_fill: float | None, *, settings: Settings, client: Any
) -> str:
    revised = _strip_code_fence(
        client.complete_text(
            LOOSEN_SYSTEM_TEX,
            _loosen_prompt(current_tex, page_count, page_fill),
            settings.scoring_model,
            operation_name="cv_fit_loosen",
        )
    )
    return _valid_tex(revised, current_tex)


def compile_and_fit_cv(
    tex_path: Path,
    *,
    settings: Settings,
    client: Any,
    max_rounds: int = 3,
) -> tuple[Path | None, str, int | None, float | None]:
    """Compile a CV and nudge it toward a 1.85-1.98 page fit, recompiling each round.

    Overlong CVs are shortened (trimming wording is truth-safe). Short CVs are
    only loosened *typographically* — spacing/font/margins, never content. There
    is deliberately no content-expansion path (TP-04): a short CV is a cosmetic
    issue, and asking the model to "elaborate on achievements" to fill a page is
    a fabrication surface with no grounding gate. Operates in place on
    ``tex_path`` and returns ``(pdf_path, compile_status, page_count, page_fill)``.
    """
    pdf_path, status = compile_pdf(tex_path)
    page_count, page_fill = measure_pdf_extent(pdf_path) if pdf_path else (None, None)
    rounds = 0
    while (
        client is not None
        and pdf_path is not None
        and page_count is not None
        and rounds < max_rounds
    ):
        fit = classify_cv_fit("cv", page_count, page_fill)
        if fit in {"ok", "unknown"}:
            break
        current = tex_path.read_text(encoding="utf-8")
        if fit == "long":
            revised = _shorten_cv_tex(
                current, page_count, page_fill, settings=settings, client=client
            )
        else:  # short: typography only, never invent content to fill the page
            revised = _loosen_cv_spacing(
                current, page_count, page_fill, settings=settings, client=client
            )
        if not revised or revised == current:
            break
        tex_path.write_text(revised, encoding="utf-8")
        pdf_path, status = compile_pdf(tex_path)
        page_count, page_fill = measure_pdf_extent(pdf_path) if pdf_path else (None, None)
        rounds += 1
    return pdf_path, status, page_count, page_fill


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "material"


# Word-boundary matched so "base"/"pay"/"package" don't fire on unrelated
# questions (TP-03): substring matching classified "Describe your database
# platform" or "a package rollout" as a salary question, which silently disabled
# the evidence-grounding gate (require_evidence=False) and injected pay-negotiation
# instructions into a non-compensation answer. "base" is dropped entirely — "base
# salary" / "base pay" already match on "salary" / "pay".
_COMPENSATION_RE = re.compile(
    r"\b(?:salary|compensation|remuneration|pay|package|bonus|incentive)\b",
    re.IGNORECASE,
)


def _is_compensation_question(question: str) -> bool:
    return _COMPENSATION_RE.search(question) is not None


def _compensation_answer_instructions(question: str, settings: Settings) -> str:
    lowered = question.lower()
    if any(token in lowered for token in ("variable", "bonus", "incentive")):
        return (
            "State a specific GBP variable pay / bonus expectation or narrow range, "
            "aligned with total compensation near candidate_profile targets and this "
            "role's seniority. Keep the answer short and direct. Return evidence_ids "
            "as an empty list — compensation answers do not cite the evidence bank."
        )
    return (
        "State a specific GBP base salary figure or narrow range aligned with "
        f"candidate_profile compensation targets (£{settings.user_comp_min_gbp:,}–"
        f"£{settings.user_comp_target_gbp:,}) and this role's seniority. "
        "Keep the answer short and direct. Return evidence_ids as an empty list when "
        "no career claims are cited."
    )


def _material_dir(job: Job) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    return MATERIALS_ROOT / str(job.id) / f"{stamp}-{_slug(job.company)}-{_slug(job.title)}"


def _job_context(job: Job) -> dict[str, Any]:
    return {
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "hybrid_policy": job.hybrid_policy,
        "compensation": job.compensation,
        "application_url": job.application_url,
        "job_summary": job.job_summary,
        "raw_description_excerpt": (job.description or "")[:4000],
        "score_rationale": job.score_rationale,
    }


def _load_evidence_with_source(
    session: Session | None = None, limit: int = 40
) -> tuple[list[ParsedEvidence], str]:
    """Return verified evidence plus its provenance: ``db`` / ``markdown`` / ``empty``.

    Verified ``EvidenceClaim`` rows are canonical; the hand-authored
    ``source_of_truth.md`` is a legacy fallback used only when the database has no
    verified claims. The source label is surfaced in the material audit detail so
    a reviewer can see whether a document was grounded on the reviewed claim bank
    or the un-reviewed markdown fallback (TP-06).
    """
    if session is not None:
        stmt = (
            select(EvidenceClaim)
            .where(EvidenceClaim.verification_state == ClaimVerificationState.verified)
            .order_by(EvidenceClaim.confidence.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        claims = list(session.exec(stmt))
        if claims:
            return [
                ParsedEvidence(
                    id=claim.id,
                    category=claim.category,
                    claim_text=claim.claim_text,
                    source_role=claim.source_span,
                    verified=True,
                    tags=claim.tags,
                )
                for claim in claims
            ], "db"
    items = [item for item in load_evidence_files(SOURCE_OF_TRUTH) if item.verified][:limit]
    return items, ("markdown" if items else "empty")


def _load_evidence(session: Session | None = None, limit: int = 40) -> list[ParsedEvidence]:
    return _load_evidence_with_source(session, limit)[0]


def _require_evidence_bank(evidence: list[ParsedEvidence]) -> None:
    """Fail loud, before any LLM call, when there is nothing to ground against (TP-06).

    An empty bank otherwise surfaces as a confusing "no valid evidence_ids"
    failure after a paid generation; this states the actual problem instead.
    """
    if not evidence:
        raise ValueError(
            "evidence bank is empty: add and verify at least one claim (or populate "
            "source_of_truth.md) before generating grounded materials"
        )


def _evidence_payload(items: list[ParsedEvidence]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "category": item.category,
            "tags": item.tags,
            "claim": item.claim_text,
        }
        for item in items
    ]


def _validate_evidence_ids(ids: list[str], evidence: list[ParsedEvidence]) -> list[str]:
    known = {item.id for item in evidence}
    return [evidence_id for evidence_id in ids if evidence_id in known]


# TA-03: quantified-impact, authentic-voice rules shared by letter/answer prompts.
# Grounding is enforced downstream (_parse_draft rejects ungrounded figures and
# entities), so asking for metrics here cannot introduce fabricated numbers.
VOICE_RULES = (
    "Voice and impact rules:\n"
    "- Lead with concrete, measurable outcomes: where the evidence provides a figure, "
    "state it as metric + action + result. Never invent or alter a number.\n"
    "- Prefer specific systems, domains, and outcomes over abstract buzzwords; name the "
    "thing that was built or changed, not the competency it demonstrates.\n"
    "- Write like a person: plain, direct, first person, varied sentence length. No filler.\n"
    "- Never use these cliches or close variants: 'results-driven', 'proven track record', "
    "'passionate about', 'seasoned professional', 'team player', 'self-starter', "
    "'detail-oriented', 'fast-paced environment', 'hit the ground running', 'synergy', "
    "'I am writing to apply', 'I am excited to apply'.\n"
)

# TA-05: role/company-specific opening hook instead of a mail-merge opener.
COVER_LETTER_HOOK_RULES = (
    "Opening hook: start the letter with one or two sentences specific to THIS company and "
    "role, drawn from the JOB context (its mission, product, or the priorities stated in "
    "job_summary), and connect that detail to your single strongest matching piece of "
    "evidence. Never open with a generic template line such as naming the role and where "
    "you saw it advertised.\n"
)


def _prompt(kind: str, job: Job, evidence: list[ParsedEvidence], extra: dict[str, Any]) -> str:
    schema = {
        "title": "short material title",
        "summary": "optional tailored positioning paragraph",
        "bullets": "optional list of CV bullets; use [] when not needed",
        "body": "cover letter or application answer body",
        "evidence_ids": "evidence IDs used from the provided evidence bank",
    }
    guidance = VOICE_RULES
    if kind == "cover letter":
        guidance += COVER_LETTER_HOOK_RULES
    return (
        f"Generate a {kind} for this job. Use the evidence bank only.\n"
        "Keep prose concise, direct, and suitable for senior AI leadership applications.\n"
        f"{guidance}"
        "Avoid em dashes. Return JSON only.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"JOB:\n{json.dumps(_job_context(job), indent=2, default=str)}\n\n"
        f"EVIDENCE:\n{json.dumps(_evidence_payload(evidence), indent=2)}\n\n"
        f"EXTRA:\n{json.dumps(extra, indent=2)}"
    )


def _parse_draft(
    parsed: dict[str, Any],
    evidence: list[ParsedEvidence],
    *,
    require_evidence: bool = True,
    grounding_numbers: set[str] | None = None,
    grounding_entities: set[str] | None = None,
    skip_grounding: bool = False,
) -> MaterialDraft:
    try:
        draft = MaterialDraft.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"material response invalid: {exc}") from exc
    draft.evidence_ids = _validate_evidence_ids(draft.evidence_ids, evidence)
    if require_evidence and not draft.evidence_ids:
        raise ValueError("material response invalid: no valid evidence_ids returned")
    # TP-01 / TP-01b: the cited evidence_ids prove a citation exists, not that the
    # prose is grounded. Reject a body that asserts a figure or a named entity
    # (employer/tool) found neither in the evidence bank nor the job context — a
    # fabricated claim must never reach a document.
    if grounding_numbers is not None and not skip_grounding:
        ungrounded = _ungrounded_numbers(draft.body, grounding_numbers)
        if ungrounded:
            raise ValueError(
                "material response invalid: ungrounded figures "
                f"{ungrounded} not found in evidence or job context"
            )
        if grounding_entities is not None:
            ungrounded_ents = _ungrounded_entities(draft.body, grounding_entities)
            if ungrounded_ents:
                raise ValueError(
                    "material response invalid: ungrounded references "
                    f"{ungrounded_ents} not found in evidence or job context"
                )
    return draft


# --- structure-preserving CV rendering -------------------------------------
#
# The CV must remain byte-identical to ``cv_source.tex`` except for lightly
# aligned content: a rewritten Professional Summary plus optional reordered /
# reworded (but never fabricated) Core Capabilities and experience bullets.

_SUMMARY_RE = re.compile(
    r"(\\section\*\{Professional Summary\}\s*\n)(.*?)(\n\s*\\section\*\{)", re.DOTALL
)
_CAPS_RE = re.compile(
    r"(\\section\*\{Core Capabilities\}\s*\n)(.*?)(\n\s*\\section\*\{)", re.DOTALL
)
_EXP_RE = re.compile(
    r"(\\section\*\{Professional Experience\}\s*\n)(.*?)"
    r"(\n\s*\\section\*\{)",
    re.DOTALL,
)
_ITEMIZE_RE = re.compile(r"(\\begin\{itemize\}\s*\n)(.*?)(\n?\s*\\end\{itemize\})", re.DOTALL)
_NUM_RE = re.compile(r"\d[\d,.]*")
_CMD_RE = re.compile(r"\\[a-zA-Z]+")
# Core Capabilities lines are separated by a manual line break with optional
# vertical spacing, e.g. ``\\[2pt]`` or ``\\[1pt]``. Detect the actual separator
# used by the active template rather than assuming a fixed amount.
_DEFAULT_CAP_SEP = r"\\[2pt]"
_CAP_SEP_RE = re.compile(r"\\\\\[[^\]]*\]")


def _read_cv_template(session: Session | None = None) -> str:
    """Return the active CV template text.

    Prefers a promoted ``template_role='cv_style'`` knowledge document when a
    session is provided, falling back to the checked-in ``cv_source.tex``.
    """
    if session is not None:
        from ..knowledge.service import active_cv_template_text

        active = active_cv_template_text(session)
        if active:
            return active
    return CV_SOURCE.read_text(encoding="utf-8")


def _detect_cap_sep(body: str) -> str:
    """Return the line separator used between Core Capabilities lines."""
    match = _CAP_SEP_RE.search(body)
    return match.group(0) if match else _DEFAULT_CAP_SEP


def _split_caps(body: str) -> list[str]:
    sep = _detect_cap_sep(body)
    return [part.strip() for part in body.split(sep) if part.strip()]


def _join_caps(lines: list[str], sep: str = _DEFAULT_CAP_SEP) -> str:
    return (sep + "\n").join(lines)


def _split_items(body: str) -> list[str]:
    return [part.strip() for part in re.split(r"\\item\b", body) if part.strip()]


def _join_items(items: list[str]) -> str:
    return "\n".join(rf"\item {item}" for item in items)


def _num_tokens(text: str) -> set[str]:
    return {tok.strip(".,") for tok in _NUM_RE.findall(text)}


def _cmd_names(text: str) -> set[str]:
    return set(_CMD_RE.findall(text))


def _union(values: list[str], fn) -> set[str]:  # noqa: ANN001
    out: set[str] = set()
    for value in values:
        out |= fn(value)
    return out


# --- grounding primitives (TP-01 / TP-05 / TP-14) --------------------------
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./_-]*")
# Unescaped LaTeX specials that break a compile if introduced into a reworded
# line (TP-14). ``(?<!\\)`` ignores already-escaped forms like ``\&``.
_BARE_SPECIAL_RE = re.compile(r"(?<!\\)[&%#$_]")
# Function words carry no factual content, so they are always allowed in a
# rewording (TP-05) without needing an evidence match.
_GROUNDING_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
        "by", "at", "from", "as", "is", "are", "be", "this", "that", "these",
        "those", "into", "across", "using", "via", "per", "you", "your", "our",
        "their", "its", "it", "we", "i", "than", "then", "while", "including",
    }
)


def _content_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


def _bare_special_count(text: str) -> int:
    return len(_BARE_SPECIAL_RE.findall(text))


def _evidence_text(evidence: list[ParsedEvidence]) -> str:
    return " ".join(f"{e.claim_text} {e.source_role or ''}" for e in evidence)


def _cv_grounding_number_tokens(
    evidence: list[ParsedEvidence], job: Job, settings: Settings
) -> set[str]:
    profile = cv_grounding_profile(job, settings)
    corpus = _evidence_text(evidence) + " " + cv_grounding_corpus(job, profile)
    return _num_tokens(corpus)


def _cv_grounding_entity_tokens(
    evidence: list[ParsedEvidence], job: Job, settings: Settings
) -> set[str]:
    profile = cv_grounding_profile(job, settings)
    corpus = _evidence_text(evidence) + " " + cv_grounding_corpus(job, profile)
    return cv_entity_allowlist(corpus, job, profile)


def _cv_grounding_words(evidence: list[ParsedEvidence], job: Job, settings: Settings) -> set[str]:
    profile = cv_grounding_profile(job, settings)
    words = _content_words(_evidence_text(evidence) + " " + cv_grounding_corpus(job, profile))
    return expand_grounding_words(words, profile)


def _merge_lines(
    candidate: list[str],
    original: list[str],
    grounding_words: set[str],
) -> tuple[list[str], int]:
    """Per-line accept: use tailored line when it passes gates, else keep original."""
    if len(candidate) != len(original):
        return list(original), 0
    merged: list[str] = []
    applied = 0
    for cand, orig in zip(candidate, original, strict=False):
        if _group_ok([cand], [orig]) and _group_grounded([cand], [orig], grounding_words):
            merged.append(cand)
            applied += 1
        else:
            merged.append(orig)
    return merged, applied


def _apply_summary_sentences(
    text: str,
    grounding_numbers: set[str],
    grounding_entities: set[str],
) -> tuple[str | None, dict[str, Any]]:
    kept: list[str] = []
    dropped: list[dict[str, Any]] = []
    for sentence in split_summary_sentences(text):
        if bad_nums := _ungrounded_numbers(sentence, grounding_numbers):
            dropped.append(
                {"sentence": sentence[:160], "reason": "ungrounded_numbers", "detail": bad_nums}
            )
        elif bad_ents := _ungrounded_entities(sentence, grounding_entities):
            dropped.append(
                {"sentence": sentence[:160], "reason": "ungrounded_entities", "detail": bad_ents}
            )
        else:
            kept.append(sentence)
    if not kept:
        return None, {
            "status": "template_fallback",
            "reason": "all_sentences_dropped",
            "dropped": dropped,
        }
    report: dict[str, Any] = {
        "status": "partial" if dropped else "applied",
        "reason": None,
        "sentences_kept": len(kept),
        "sentences_dropped": len(dropped),
    }
    if dropped:
        report["dropped"] = dropped
    return " ".join(kept), report


def _grounding_number_tokens(evidence: list[ParsedEvidence], job: Job) -> set[str]:
    """Numeric tokens that a generated document is allowed to assert.

    A number is grounded if it appears anywhere in the evidence bank or in the
    job's own context (e.g. the role's stated compensation). Anything else in
    generated prose is a fabricated figure (TP-01).
    """
    corpus = _evidence_text(evidence)
    corpus += (
        f" {job.company or ''} {job.title or ''} {job.location or ''}"
        f" {job.hybrid_policy or ''} {job.compensation or ''}"
    )
    return _num_tokens(corpus)


def _ungrounded_numbers(text: str | None, allowed: set[str]) -> list[str]:
    if not text:
        return []
    return sorted(_num_tokens(text) - allowed)


# Named-entity tokens (TP-01b): CamelCase names (PyTorch, OpenAI, GitHub) or
# all-caps acronyms of 3+ chars (AWS, GCP, NHS). Single Capitalised words
# ("Google") are intentionally not flagged — too close to ordinary sentence
# capitalisation to gate deterministically without an NER pass.
_ENTITY_RE = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{3,})\b")
# Generic business / credential acronyms that are not specific named entities and
# so never need an evidence match.
_GENERIC_ACRONYMS = frozenset(
    {
        "CEO", "CTO", "CIO", "COO", "CFO", "CDO", "CMO", "MBA", "BSC", "MSC",
        "PHD", "KPI", "KPIS", "OKR", "OKRS", "ROI", "ROIS", "GDPR", "SLA",
        "SLAS", "FAQ", "FAQS",
    }
)


def _entity_tokens(text: str) -> set[str]:
    return {m.lower() for m in _ENTITY_RE.findall(text)}


def _grounding_entity_tokens(evidence: list[ParsedEvidence], job: Job) -> set[str]:
    """Named entities a generated document is allowed to assert (TP-01b).

    An employer, tool, or credential is grounded if it appears in the evidence
    bank or the job context; generic role/credential acronyms are always allowed.
    """
    corpus = _evidence_text(evidence) + (
        f" {job.company or ''} {job.title or ''} {job.location or ''} {job.hybrid_policy or ''}"
    )
    return _entity_tokens(corpus) | {a.lower() for a in _GENERIC_ACRONYMS}


def _ungrounded_entities(text: str | None, allowed: set[str]) -> list[str]:
    if not text:
        return []
    return sorted(_entity_tokens(text) - allowed)


def assert_rewrite_grounded(
    original_text: str | None,
    revised_text: str,
    evidence: list[ParsedEvidence],
    job: Job,
) -> None:
    """Reject an LLM rewrite that introduces ungrounded figures/references (TP-01b).

    Only tokens *new* to the revised text (absent from the original document) are
    checked, so template/preamble constants — font sizes, the phone number — and
    any already-present content never trip the gate; only what the rewrite added
    must trace to the evidence bank or job context.
    """
    allowed_nums = _grounding_number_tokens(evidence, job) | _num_tokens(original_text or "")
    new_nums = sorted(_num_tokens(revised_text) - allowed_nums)
    if new_nums:
        raise ValueError(
            f"revised document adds ungrounded figures {new_nums} not found in the "
            "evidence bank or job context; add them to the evidence bank first"
        )
    allowed_ents = _grounding_entity_tokens(evidence, job) | _entity_tokens(original_text or "")
    new_ents = sorted(_entity_tokens(revised_text) - allowed_ents)
    if new_ents:
        raise ValueError(
            f"revised document adds ungrounded references {new_ents} not found in the "
            "evidence bank or job context; add them to the evidence bank first"
        )


def _group_ok(returned: list[str], original: list[str]) -> bool:
    """Reject fabricated/structure-breaking edits to a group of LaTeX lines.

    Same line count, balanced braces, no numeric or LaTeX-command tokens beyond
    those already present in the original group, and no newly-introduced
    unescaped LaTeX special character (``& % # $ _``) that would break the
    compile (TP-14).
    """
    if not returned or len(returned) != len(original):
        return False
    joined = "\n".join(returned)
    if joined.count("{") != joined.count("}"):
        return False
    if _num_tokens(joined) - _union(original, _num_tokens):
        return False
    if _cmd_names(joined) - _union(original, _cmd_names):
        return False
    return _bare_special_count(joined) <= _bare_special_count("\n".join(original))


def _group_grounded(returned: list[str], original: list[str], evidence_words: set[str]) -> bool:
    """Reject reworded lines that introduce ungrounded content words (TP-05).

    ``_group_ok`` guards numbers, commands, braces, and escaping but not bare
    words, so "Python" → "Rust" or "supported" → "founded" slip through. A
    reworded line may only use words already in the original line, words present
    somewhere in the evidence bank, or function words — never a skill, tool, or
    employer the candidate cannot evidence.
    """
    allowed = evidence_words | _content_words("\n".join(original)) | _GROUNDING_STOPWORDS
    return not (_content_words("\n".join(returned)) - allowed)


def _parse_cv_template(text: str) -> dict[str, Any]:
    summary = ""
    match = _SUMMARY_RE.search(text)
    if match:
        summary = match.group(2).strip()
    caps: list[str] = []
    caps_match = _CAPS_RE.search(text)
    if caps_match:
        caps = _split_caps(caps_match.group(2))
    roles: list[list[str]] = []
    exp_match = _EXP_RE.search(text)
    if exp_match:
        for itemize in _ITEMIZE_RE.finditer(exp_match.group(2)):
            roles.append(_split_items(itemize.group(2)))
    return {"summary": summary, "capabilities": caps, "experience": roles}


def effective_cv_draft_json(
    draft_json: dict[str, Any] | None,
    *,
    tex_content: str | None = None,
) -> dict[str, Any] | None:
    """Fill missing CV draft fields from rendered tex for structured editing.

    When tailoring falls back to the template, ``render_cv`` keeps the template
    spans but ``draft_json`` may store ``summary: null`` or ``capabilities: []``.
    The structured editor needs the effective tex content, not the sparse draft.
    """
    if not draft_json and not tex_content:
        return None
    merged = dict(draft_json or {})
    if not tex_content:
        return merged
    parsed = _parse_cv_template(tex_content)
    if not (merged.get("summary") or "").strip():
        summary = (parsed.get("summary") or "").strip()
        if summary:
            merged["summary"] = latex_to_plain(summary)
    if not merged.get("capabilities"):
        merged["capabilities"] = list(parsed.get("capabilities") or [])
    if not merged.get("experience"):
        merged["experience"] = {
            str(i): items for i, items in enumerate(parsed.get("experience") or [])
        }
    return merged


def render_cv(tailoring: CvTailoring, *, template_text: str | None = None) -> str:
    """Render a CV by replacing only the editable spans of the active template."""
    text = template_text if template_text is not None else _read_cv_template()
    original = _parse_cv_template(text)

    if tailoring.summary and tailoring.summary.strip():
        escaped = escape_latex(tailoring.summary.strip())

        def _summary_repl(match: re.Match[str]) -> str:
            return match.group(1) + escaped + match.group(3)

        text = _SUMMARY_RE.sub(_summary_repl, text, count=1)

    caps = tailoring.capabilities
    if caps and len(caps) == len(original["capabilities"]):

        def _caps_repl(match: re.Match[str]) -> str:
            sep = _detect_cap_sep(match.group(2))
            return match.group(1) + _join_caps(caps, sep) + match.group(3)

        text = _CAPS_RE.sub(_caps_repl, text, count=1)

    if tailoring.experience:
        exp_match = _EXP_RE.search(text)
        if exp_match:
            counter = {"i": 0}

            def _itemize_repl(match: re.Match[str]) -> str:
                index = counter["i"]
                counter["i"] += 1
                returned = tailoring.experience.get(str(index))
                source = original["experience"][index] if index < len(original["experience"]) else []
                if returned and len(returned) == len(source):
                    return match.group(1) + _join_items(returned) + match.group(3)
                return match.group(0)

            new_body = _ITEMIZE_RE.sub(_itemize_repl, exp_match.group(2))
            text = text[: exp_match.start(2)] + new_body + text[exp_match.end(2) :]

    return text


def _cv_prompt(
    job: Job,
    evidence: list[ParsedEvidence],
    original: dict[str, Any],
    *,
    ranked_evidence: list[dict[str, Any]],
) -> str:
    summary_words = len((original["summary"] or "").split())
    schema = {
        "title": "short CV title",
        "summary": "rewritten Professional Summary paragraph: plain prose only, no LaTeX commands; "
        f"keep it close to the original length (about {summary_words} words, ±15%) so the CV stays two pages",
        "capabilities": "the SAME number of Core Capabilities lines, lightly reworded and/or reordered; "
        "keep each line's leading \\textbf{Label:} and all LaTeX intact; never invent skills",
        "experience": 'object mapping role index ("0","1",...) to that role\'s bullets, SAME count per '
        "role, lightly reworded and/or reordered; keep all LaTeX (\\textbf, \\href) intact; never "
        "change employers, dates, or numbers",
        "evidence_ids": "evidence IDs used from the provided evidence bank",
    }
    editable = {
        "summary": original["summary"],
        "capabilities": original["capabilities"],
        "experience": {str(i): items for i, items in enumerate(original["experience"])},
    }
    return (
        "Tailor this CV to the job. Keep the document structure IDENTICAL: do not add or remove sections, "
        "bullets, employers, dates, or metrics. Only lightly align wording and ordering of EXISTING content.\n"
        "The source CV is a finished two-page document; preserving the structure and the summary length "
        "keeps the tailored CV at the same two-page extent.\n"
        "Rewrite the Professional Summary to target the role, grounded strictly in the evidence bank, and "
        f"keep it close to its original length (about {summary_words} words).\n"
        "Lead the summary with the most quantified, role-relevant achievements the evidence supports "
        "(metric + action + result); prefer specific systems and outcomes over abstract buzzwords, and "
        "never use cliches like 'results-driven', 'proven track record', or 'passionate about'.\n"
        "You may lightly reword and reorder existing Core Capabilities lines and experience bullets, but "
        "never invent facts, numbers, or technologies, and preserve all LaTeX commands.\n"
        "Prefer evidence rows with higher jd_match scores when aligning wording.\n"
        "Avoid em dashes. Return JSON only.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"JOB:\n{json.dumps(_job_context(job), indent=2, default=str)}\n\n"
        f"EVIDENCE (ranked by JD relevance — prefer top matches):\n"
        f"{json.dumps(ranked_evidence[:30], indent=2)}\n\n"
        f"CURRENT CV CONTENT (edit in place, preserve counts and LaTeX):\n"
        f"{json.dumps(editable, indent=2)}"
    )


def _parse_cv_tailoring(
    parsed: dict[str, Any],
    evidence: list[ParsedEvidence],
    original: dict[str, Any],
    job: Job,
    settings: Settings,
    *,
    ranked_evidence: list[dict[str, Any]],
) -> tuple[CvTailoring, dict[str, Any]]:
    title = str(parsed.get("title") or "Tailored CV")
    profile = cv_grounding_profile(job, settings)
    grounding_numbers = _cv_grounding_number_tokens(evidence, job, settings)
    grounding_entities = _cv_grounding_entity_tokens(evidence, job, settings)
    grounding_words = _cv_grounding_words(evidence, job, settings)
    summary_word_target = len((original.get("summary") or "").split()) or 150

    summary_raw = parsed.get("summary")
    summary = latex_to_plain(str(summary_raw).strip()) if summary_raw else None
    if summary:
        summary, summary_report = _apply_summary_sentences(
            summary, grounding_numbers, grounding_entities
        )
    else:
        summary_report = {"status": "template_fallback", "reason": "missing"}

    if not summary:
        composed = compose_summary_from_claims(
            ranked_evidence,
            evidence,
            max_words=summary_word_target,
        )
        if composed and not (
            _ungrounded_numbers(composed, grounding_numbers)
            or _ungrounded_entities(composed, grounding_entities)
        ):
            summary = composed
            summary_report = {
                "status": "evidence_compose",
                "reason": summary_report.get("reason"),
                "source": "verified_claims",
            }

    caps_raw = parsed.get("capabilities")
    caps: list[str] = list(original["capabilities"])
    caps_lines_applied = 0
    caps_reason: str | None = None
    if not isinstance(caps_raw, list):
        caps_reason = "missing"
    else:
        candidate = [str(line) for line in caps_raw]
        if len(candidate) != len(original["capabilities"]):
            caps_reason = "group_ok"
        else:
            caps, caps_lines_applied = _merge_lines(candidate, original["capabilities"], grounding_words)
            if caps_lines_applied == len(original["capabilities"]):
                caps_reason = None
            elif caps_lines_applied > 0:
                caps_reason = "partial"
            else:
                caps_reason = "group_grounded"
    if caps_lines_applied == len(original["capabilities"]):
        caps_status = "applied"
    elif caps_lines_applied > 0:
        caps_status = "partial"
    else:
        caps_status = "template_fallback"
    caps_report: dict[str, Any] = {
        "requested": len(original["capabilities"]),
        "applied": caps_lines_applied,
        "status": caps_status,
        "reason": caps_reason,
    }

    experience: dict[str, list[str]] = {}
    roles_total = len(original["experience"])
    roles_touched = 0
    bullets_applied = 0
    bullets_total = 0
    exp_raw = parsed.get("experience")
    if isinstance(exp_raw, dict):
        for index, source in enumerate(original["experience"]):
            bullets_total += len(source)
            returned = exp_raw.get(str(index))
            if isinstance(returned, list):
                candidate = [str(item) for item in returned]
                merged, applied = _merge_lines(candidate, source, grounding_words)
                experience[str(index)] = merged
                bullets_applied += applied
                if applied > 0:
                    roles_touched += 1
    if roles_touched == 0:
        exp_status = "template_fallback"
    elif roles_touched == roles_total:
        exp_status = "applied"
    else:
        exp_status = "partial"
    experience_report: dict[str, Any] = {
        "roles_total": roles_total,
        "roles_applied": roles_touched,
        "bullets_applied": bullets_applied,
        "bullets_total": bullets_total,
        "status": exp_status,
    }

    evidence_ids = _validate_evidence_ids(
        [str(e) for e in (parsed.get("evidence_ids") or [])], evidence
    )
    if not evidence_ids:
        raise ValueError("material response invalid: no valid evidence_ids returned")

    gaps = detect_alignment_gaps(evidence, job, profile)
    exp_notes = experience_alignment_notes(job, evidence, original, experience, gaps)
    tailored_dump = {
        "summary": summary,
        "capabilities": caps,
        "experience": experience,
    }
    tailoring_report: dict[str, Any] = {
        "grounding_profile": profile,
        "summary": summary_report,
        "capabilities": caps_report,
        "experience": experience_report,
        "alignment_gaps": gaps,
        "experience_alignment": exp_notes,
        "change_summary": summarize_cv_changes(original, tailored_dump),
    }
    return (
        CvTailoring(
            title=title,
            summary=summary,
            capabilities=caps,
            experience=experience,
            evidence_ids=evidence_ids,
        ),
        tailoring_report,
    )


def _letter_tex(job: Job, draft: MaterialDraft, settings: Settings) -> str:
    body = "\n\n".join(escape_latex(p.strip()) for p in (draft.body or "").split("\n\n") if p.strip())
    name = escape_latex(settings.user_full_name)
    contact_parts = [
        f"Email: {escape_latex(settings.user_email)}" if settings.user_email else "",
        f"Phone: {escape_latex(settings.user_phone)}" if settings.user_phone else "",
        escape_latex(settings.user_location) if settings.user_location else "",
    ]
    contact = r" \quad ".join(part for part in contact_parts if part)
    return rf"""\documentclass[11pt,a4paper]{{extarticle}}
\usepackage[top=0.65in,bottom=0.65in,left=0.75in,right=0.75in]{{geometry}}
\usepackage[colorlinks=true,urlcolor=blue!50!black]{{hyperref}}
\pagenumbering{{gobble}}
\begin{{document}}
\begin{{center}}
{{\Large \textbf{{{name}}}}}\\[2pt]
{contact}
\end{{center}}

\vspace{{8pt}}
\textbf{{Re: {escape_latex(job.title)} at {escape_latex(job.company)}}}

\vspace{{8pt}}
{body}

\vspace{{10pt}}
Sincerely,\\
{name}
\end{{document}}
"""


def _next_version(session: Session, job_id: int, material_type: str) -> int:
    current = session.exec(
        select(func.max(GeneratedMaterial.version)).where(
            GeneratedMaterial.job_id == job_id,
            GeneratedMaterial.material_type == material_type,
        )
    ).one()
    return int(current or 0) + 1


def _write_metadata(
    path: Path,
    material: GeneratedMaterial,
    compile_status: str,
    model: str,
    *,
    edited_via: str | None = None,
) -> None:
    metadata = {
        "material_id": material.id,
        "job_id": material.job_id,
        "material_type": material.material_type,
        "title": material.title,
        "evidence_ids": material.evidence_ids,
        "draft_json": material.draft_json,
        "version": material.version,
        "is_final": material.is_final,
        "supersedes_id": material.supersedes_id,
        "status": material.status,
        "model": model,
        "compile_status": compile_status,
        "source_files": [str(SOURCE_OF_TRUTH), str(CV_SOURCE)],
        "created_at": material.created_at.isoformat(),
    }
    if edited_via:
        metadata["edited_via"] = edited_via
    path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")


def _record_material(
    session: Session,
    job: Job,
    *,
    material_type: str,
    title: str,
    evidence_ids: list[str],
    status: str,
    tex_path: Path | None = None,
    pdf_path: Path | None = None,
    markdown_path: Path | None = None,
    question: str | None = None,
    word_limit: int | None = None,
    draft_json: dict[str, Any] | None = None,
    version: int | None = None,
    is_final: bool = False,
    supersedes_id: int | None = None,
    page_count: int | None = None,
    page_fill: float | None = None,
    audit_action: str | None = None,
    audit_detail: dict[str, Any] | None = None,
) -> GeneratedMaterial:
    resolved_version = version if version is not None else _next_version(session, job.id or 0, material_type)
    material = GeneratedMaterial(
        job_id=job.id or 0,
        material_type=material_type,
        title=title,
        question=question,
        word_limit=word_limit,
        tex_path=str(tex_path) if tex_path else None,
        pdf_path=str(pdf_path) if pdf_path else None,
        markdown_path=str(markdown_path) if markdown_path else None,
        evidence_ids=evidence_ids,
        draft_json=draft_json,
        version=resolved_version,
        is_final=is_final,
        supersedes_id=supersedes_id,
        page_count=page_count,
        page_fill=page_fill,
        status=status,
    )
    session.add(material)
    session.commit()
    session.refresh(material)
    detail = {"material_id": material.id, "status": status, "evidence_ids": evidence_ids, "version": material.version}
    if audit_detail:
        detail.update(audit_detail)
    log_action(
        session,
        actor=ActorType.agent,
        action=audit_action or f"generate_{material_type}",
        entity_type="job",
        entity_id=job.id,
        detail=detail,
    )
    return material


def generate_cv(
    session: Session,
    job: Job,
    *,
    client: _MaterialClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    settings = settings or get_settings()
    with pipeline_run(session, pipeline_type="materials", entity_type="job", entity_id=job.id, detail={"type": "cv"}):
        client = client or _build_client(settings, session=session, entity_id=job.id)
        pool, evidence_source = _load_evidence_with_source(
            session, limit=settings.evidence_candidate_pool
        )
        _require_evidence_bank(pool)
        # RET-01: relevance-select before the cap so a relevant lower-confidence
        # claim is not truncated out of the pool before ranking.
        evidence = select_relevant_evidence(pool, job, limit=settings.evidence_prompt_limit)
        template_text = _read_cv_template(session)
        original = _parse_cv_template(template_text)
        ranked = rank_evidence_for_job(evidence, job)
        tailoring, tailoring_report = _parse_cv_tailoring(
            client.generate(
                SYSTEM_PROMPT,
                _cv_prompt(job, evidence, original, ranked_evidence=ranked),
                settings.scoring_model,
                operation_name="generate_cv",
            ),
            evidence,
            original,
            job,
            settings,
            ranked_evidence=ranked,
        )
        out_dir = _material_dir(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        version = _next_version(session, job.id or 0, "cv")
        basename = material_export_basename(
            candidate=settings.materials_export_name,
            material_type="cv",
            company=job.company,
            version=version,
        )
        tex_path = out_dir / f"{basename}.tex"
        rendered_tex = render_cv(tailoring, template_text=template_text)
        tex_path.write_text(rendered_tex, encoding="utf-8")
        pdf_path, compile_status, page_count, page_fill = compile_and_fit_cv(
            tex_path, settings=settings, client=client
        )
        status = "created_pdf" if pdf_path else compile_status
        draft_json = effective_cv_draft_json(tailoring.model_dump(), tex_content=rendered_tex) or {}
        draft_json["template_baseline"] = original
        draft_json["tailoring"] = tailoring_report
        quality_report = material_quality_report(cv_plain_text(draft_json), job)
        draft_json["quality_report"] = quality_report
        material = _record_material(
            session,
            job,
            material_type="cv",
            title=tailoring.title,
            evidence_ids=tailoring.evidence_ids,
            status=status,
            tex_path=tex_path,
            pdf_path=pdf_path,
            draft_json=draft_json,
            version=version,
            page_count=page_count,
            page_fill=page_fill,
            audit_detail={
                "evidence_source": evidence_source,
                "evidence_count": len(evidence),
                "candidate_count": len(pool),
                "tailoring": tailoring_report,
                "jd_match_score": quality_report["jd_match"]["score"],
                "ai_tells": quality_report["tells"],
            },
        )
        _write_metadata(out_dir / "metadata.json", material, compile_status, settings.scoring_model)
        return material


def generate_cover_letter(
    session: Session,
    job: Job,
    *,
    client: _MaterialClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="materials",
        entity_type="job",
        entity_id=job.id,
        detail={"type": "cover_letter"},
    ):
        client = client or _build_client(settings, session=session, entity_id=job.id)
        pool, evidence_source = _load_evidence_with_source(
            session, limit=settings.evidence_candidate_pool
        )
        _require_evidence_bank(pool)
        # RET-01: relevance-select before the cap (see generate_cv).
        evidence = select_relevant_evidence(pool, job, limit=settings.evidence_prompt_limit)
        draft = _parse_draft(
            client.generate(
                SYSTEM_PROMPT,
                _prompt("cover letter", job, evidence, {}),
                settings.scoring_model,
                operation_name="generate_cover_letter",
            ),
            evidence,
            grounding_numbers=_grounding_number_tokens(evidence, job),
            grounding_entities=_grounding_entity_tokens(evidence, job),
        )
        out_dir = _material_dir(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        version = _next_version(session, job.id or 0, "cover_letter")
        basename = material_export_basename(
            candidate=settings.materials_export_name,
            material_type="cover_letter",
            company=job.company,
            version=version,
        )
        tex_path = out_dir / f"{basename}.tex"
        tex_path.write_text(_letter_tex(job, draft, settings), encoding="utf-8")
        pdf_path, compile_status = compile_pdf(tex_path)
        status = "created_pdf" if pdf_path else compile_status
        page_count, page_fill = measure_pdf_extent(pdf_path) if pdf_path else (None, None)
        quality_report = material_quality_report(draft.body or "", job)
        draft_json = draft.model_dump()
        draft_json["quality_report"] = quality_report
        material = _record_material(
            session,
            job,
            material_type="cover_letter",
            title=draft.title,
            evidence_ids=draft.evidence_ids,
            status=status,
            tex_path=tex_path,
            pdf_path=pdf_path,
            version=version,
            draft_json=draft_json,
            page_count=page_count,
            page_fill=page_fill,
            audit_detail={
                "evidence_source": evidence_source,
                "evidence_count": len(evidence),
                "candidate_count": len(pool),
                "jd_match_score": quality_report["jd_match"]["score"],
                "ai_tells": quality_report["tells"],
            },
        )
        _write_metadata(out_dir / "metadata.json", material, compile_status, settings.scoring_model)
        return material


def generate_answer(
    session: Session,
    job: Job,
    *,
    question: str,
    word_limit: int | None = None,
    instructions: str | None = None,
    client: _MaterialClient | None = None,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    settings = settings or get_settings()
    with pipeline_run(
        session,
        pipeline_type="materials",
        entity_type="job",
        entity_id=job.id,
        detail={"type": "answer"},
    ):
        client = client or _build_client(settings, session=session, entity_id=job.id)
        pool, evidence_source = _load_evidence_with_source(
            session, limit=settings.evidence_candidate_pool
        )
        compensation = _is_compensation_question(question)
        # Compensation answers draw their figure from settings, not the bank, so an
        # empty bank is acceptable there; every other answer must be groundable (TP-06).
        if not compensation:
            _require_evidence_bank(pool)
        # RET-01: relevance-select before the cap (see generate_cv).
        evidence = select_relevant_evidence(pool, job, limit=settings.evidence_prompt_limit)
        extra_instructions = instructions
        if compensation:
            hint = _compensation_answer_instructions(question, settings)
            extra_instructions = f"{hint} {instructions}".strip() if instructions else hint
        draft = _parse_draft(
            client.generate(
                SYSTEM_PROMPT,
                _prompt(
                    "application question answer",
                    job,
                    evidence,
                    {
                        "question": question,
                        "word_limit": word_limit,
                        "instructions": extra_instructions,
                        "candidate_profile": {
                            "compensation_min_gbp": settings.user_comp_min_gbp,
                            "compensation_target_gbp": settings.user_comp_target_gbp,
                        },
                    },
                ),
                settings.scoring_model,
                operation_name="generate_answer",
            ),
            evidence,
            require_evidence=not compensation,
            grounding_numbers=_grounding_number_tokens(evidence, job),
            grounding_entities=_grounding_entity_tokens(evidence, job),
            # Compensation answers state a target from settings, not the evidence
            # bank, so the numeric gate would false-positive on the salary figure.
            skip_grounding=compensation,
        )
        out_dir = _material_dir(job) / "answers"
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{_slug(question)}.md"
        body = draft.body or ""
        evidence_note = (
            f"\n\nEvidence: {', '.join(draft.evidence_ids)}\n" if draft.evidence_ids else "\n"
        )
        md_path.write_text(
            f"# {draft.title}\n\n**Question:** {question}\n\n{body}{evidence_note}",
            encoding="utf-8",
        )
        quality_report = material_quality_report(body, job)
        draft_json = draft.model_dump()
        draft_json["quality_report"] = quality_report
        material = _record_material(
            session,
            job,
            material_type="answer",
            title=draft.title,
            evidence_ids=draft.evidence_ids,
            status="created_markdown",
            markdown_path=md_path,
            question=question,
            word_limit=word_limit,
            draft_json=draft_json,
            audit_detail={
                "evidence_source": evidence_source,
                "evidence_count": len(evidence),
                "candidate_count": len(pool),
                "jd_match_score": quality_report["jd_match"]["score"],
                "ai_tells": quality_report["tells"],
            },
        )
        _write_metadata(out_dir.parent / "metadata.json", material, "not_applicable", settings.scoring_model)
        return material
