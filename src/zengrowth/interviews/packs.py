"""Interview prep-pack generation with web research (INT-02)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlmodel import Session

from ..config import Settings, get_settings
from ..models import GeneratedMaterial, Interview, Job, MaterialAudience
from ..observability.client import InstrumentedLLM, build_instrumented_llm
from ..observability.tracing import pipeline_run
from .markdown_format import slugify, strip_llm_envelope, wrap_obsidian_pack
from .material_policy import (
    ENHANCE_SYSTEM_APPEND,
    PACK_SYSTEM_PROMPT,
    PACK_TYPES,
    find_enhance_source,
    load_prior_debriefs,
    load_prior_prep_materials,
    missing_sections,
    pack_sections,
    quality_warnings,
    resolve_round_type,
)

__all__ = [
    "PACK_TYPES",
    "InstrumentedPackClient",
    "generate_pack",
    "load_prior_debriefs",
    "_build_pack_client",
]


def _should_fallback_from_web_search(exc: Exception) -> bool:
    """True when web search failed but a plain completion may still succeed."""
    name = type(exc).__name__
    if "Authentication" in name or "RateLimit" in name:
        return False
    if "BadRequest" in name or "PermissionDenied" in name:
        return True
    if "APITimeout" in name or name == "TimeoutError":
        return True
    status = getattr(exc, "status_code", None)
    return status in (400, 404, 422)

_PACK_TITLES: dict[str, str] = {
    "company_briefing": "Company briefing",
    "interviewer_pack": "Interviewer pack",
    "tech_prep_pack": "Technical prep pack",
    "final_round_pack": "Final-round pack",
}

_CLAIM_ID_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")


class PackClient(Protocol):
    def generate_document(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        *,
        operation_name: str,
        allow_web: bool = True,
    ) -> tuple[str, list[dict[str, str]], bool]:
        """Return ``(markdown, citations, web_search_used)``."""
        ...


class InstrumentedPackClient:
    """Web-search generation with a stored-context-only fallback."""

    def __init__(
        self,
        llm: InstrumentedLLM,
        *,
        session: Session | None = None,
        entity_id: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self._session = session
        self._entity_id = entity_id
        self._settings = settings or get_settings()

    def generate_document(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
        *,
        operation_name: str,
        allow_web: bool = True,
    ) -> tuple[str, list[dict[str, str]], bool]:
        if allow_web and self._settings.interview_research_web_search:
            try:
                text, citations = self._llm.chat_with_web_search(
                    system=system,
                    user=user,
                    model=model,
                    max_tokens=max_tokens,
                    max_searches=self._settings.interview_research_max_searches,
                    operation_name=operation_name,
                    session=self._session,
                    entity_type="job",
                    entity_id=self._entity_id,
                )
                return text, citations, True
            except Exception as exc:
                if not _should_fallback_from_web_search(exc):
                    raise
        text = self._llm.complete_text(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            operation_name=operation_name,
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
        )
        return text, [], False


def _build_pack_client(
    settings: Settings, session: Session | None = None, entity_id: int | None = None
) -> PackClient:
    return InstrumentedPackClient(
        build_instrumented_llm(settings), session=session, entity_id=entity_id, settings=settings
    )


def _read_material_text(material: GeneratedMaterial) -> str | None:
    from ..materials.files import read_text_content

    return read_text_content(material)


def _profile_context(settings: Settings) -> dict[str, Any]:
    return {
        "target_roles": settings.user_target_roles,
        "location": settings.user_location,
        "hybrid_max_office_days": settings.user_hybrid_max_office_days,
        "compensation_min_gbp": settings.user_comp_min_gbp or None,
        "compensation_target_gbp": settings.user_comp_target_gbp or None,
    }


def _interview_context(interview: Interview | None) -> dict[str, Any] | None:
    if interview is None:
        return None
    return {
        "round_type": interview.round_type.value,
        "title": interview.title,
        "format": interview.format.value,
        "scheduled_at": interview.scheduled_at.isoformat() if interview.scheduled_at else None,
        "participants": interview.participants,
        "notes": interview.notes,
    }


def _pack_prompt(
    pack_type: str,
    job: Job,
    *,
    interview: Interview | None,
    evidence_payload: list[dict[str, Any]],
    prior_debriefs: list[dict[str, Any]],
    prior_prep: list[dict[str, Any]],
    cross_job_learnings: list[str],
    settings: Settings,
    enhance_skeleton: str | None = None,
) -> str:
    from ..materials.generator import _job_context

    round_type = resolve_round_type(interview)
    sections = pack_sections(pack_type, round_type=round_type)
    payload: dict[str, Any] = {
        "pack_type": pack_type,
        "round_type": round_type,
        "required_sections": sections,
        "job": _job_context(job),
        "interview": _interview_context(interview),
        "candidate_profile": _profile_context(settings),
        "evidence_bank": evidence_payload,
        "prior_round_debriefs": prior_debriefs or None,
        "prior_round_prep_packs": prior_prep or None,
        "learnings_from_past_interview_processes": cross_job_learnings or None,
        "today": datetime.now(UTC).date().isoformat(),
    }
    if enhance_skeleton:
        payload["enhance_skeleton"] = enhance_skeleton[:12000]
    intro = (
        f"Prepare a {_PACK_TITLES[pack_type]} for the interview described below.\n"
        f"Use `##` headings exactly matching required_sections, in order.\n"
        f"Under Core Questions use ### Q1 … ### Q5+ with answer outlines.\n"
        f"Return body only (no YAML frontmatter, no `#` title).\n\n"
    )
    if enhance_skeleton:
        intro = (
            "Enhance the operator's existing prep pack skeleton below.\n"
            "Keep structure and questions; add evidence citations and net-new facts only.\n\n"
        )
    return intro + json.dumps(payload, indent=2, default=str)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def _cited_claim_ids(markdown: str, known_ids: set[str]) -> list[str]:
    found: list[str] = []
    for token in _CLAIM_ID_RE.findall(markdown):
        if token in known_ids and token not in found:
            found.append(token)
    return found


def generate_pack(
    session: Session,
    job: Job,
    *,
    pack_type: str,
    interview: Interview | None = None,
    client: PackClient | None = None,
    settings: Settings | None = None,
    enhance: bool = False,
    source_material_id: int | None = None,
) -> GeneratedMaterial:
    """Generate an internal prep pack and record it as a versioned material."""
    if pack_type not in PACK_TYPES:
        raise ValueError(f"unsupported pack type: {pack_type!r} (expected one of {PACK_TYPES})")
    settings = settings or get_settings()
    round_type = resolve_round_type(interview)
    with pipeline_run(
        session,
        pipeline_type="interview_pack",
        entity_type="job",
        entity_id=job.id,
        detail={
            "type": pack_type,
            "interview_id": interview.id if interview else None,
            "enhance": enhance,
        },
    ):
        client = client or _build_pack_client(settings, session=session, entity_id=job.id)
        from ..materials.cv_alignment import select_relevant_evidence
        from ..materials.generator import (
            MATERIALS_ROOT,
            _evidence_payload,
            _load_evidence_with_source,
            _next_version,
        )

        pool, evidence_source = _load_evidence_with_source(
            session, limit=settings.evidence_candidate_pool
        )
        evidence = select_relevant_evidence(pool, job, limit=settings.evidence_prompt_limit)
        prior_debriefs = load_prior_debriefs(session, job.id or 0)
        prior_prep = load_prior_prep_materials(session, job.id or 0)
        from .service import load_cross_job_learnings

        cross_job = load_cross_job_learnings(session, exclude_job_id=job.id)

        enhance_skeleton: str | None = None
        if enhance:
            source = None
            if source_material_id is not None:
                source = session.get(GeneratedMaterial, source_material_id)
            if source is None:
                source = find_enhance_source(
                    session,
                    job.id or 0,
                    pack_type=pack_type,
                    interview_id=interview.id if interview else None,
                )
            if source is not None:
                raw = _read_material_text(source)
                if raw:
                    enhance_skeleton = strip_llm_envelope(raw)

        system = PACK_SYSTEM_PROMPT + (ENHANCE_SYSTEM_APPEND if enhance_skeleton else "")
        markdown, citations, web_used = client.generate_document(
            system,
            _pack_prompt(
                pack_type,
                job,
                interview=interview,
                evidence_payload=_evidence_payload(evidence),
                prior_debriefs=prior_debriefs,
                prior_prep=prior_prep,
                cross_job_learnings=cross_job,
                settings=settings,
                enhance_skeleton=enhance_skeleton,
            ),
            settings.scoring_model,
            settings.interview_pack_max_tokens,
            operation_name=f"generate_{pack_type}",
        )
        markdown = _strip_code_fence(markdown)
        if not markdown.strip():
            raise ValueError("pack generation returned an empty document")

        sections = pack_sections(pack_type, round_type=round_type)
        missing = missing_sections(markdown, sections)
        warnings = quality_warnings(
            markdown, material_kind="pack", pack_type=pack_type, round_type=round_type
        )
        cited_ids = _cited_claim_ids(markdown, {item.id for item in evidence})

        display_title = f"{_PACK_TITLES[pack_type]} — {job.company}"
        document = wrap_obsidian_pack(
            markdown,
            title=display_title,
            job=job,
            pack_type=pack_type,
            web_search_used=web_used,
            citations=citations,
        )

        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        out_dir = MATERIALS_ROOT / str(job.id) / f"{stamp}-{pack_type.replace('_', '-')}"
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{slugify(display_title)}.md"
        md_path.write_text(document, encoding="utf-8")

        version = _next_version(session, job.id or 0, pack_type)
        material = GeneratedMaterial(
            job_id=job.id or 0,
            interview_id=interview.id if interview else None,
            material_type=pack_type,
            audience=MaterialAudience.internal,
            title=display_title,
            markdown_path=str(md_path),
            evidence_ids=cited_ids,
            version=version,
            status="created_markdown",
            draft_json=None,
        )
        session.add(material)
        session.commit()
        session.refresh(material)
        from ..audit import log_action
        from ..models import ActorType

        log_action(
            session,
            actor=ActorType.agent,
            action=f"generate_{pack_type}",
            entity_type="job",
            entity_id=job.id,
            detail={
                "material_id": material.id,
                "interview_id": interview.id if interview else None,
                "web_search_used": web_used,
                "citation_count": len(citations),
                "evidence_source": evidence_source,
                "evidence_cited": cited_ids,
                "prior_debriefs": len(prior_debriefs),
                "prior_prep_packs": len(prior_prep),
                "missing_sections": missing,
                "quality_warnings": warnings,
                "enhance": bool(enhance_skeleton),
                "version": version,
            },
        )
        return material
