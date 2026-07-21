"""Revise, mark-final, and version helpers for generated materials."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import ActorType, GeneratedMaterial, Job
from .files import read_text_content
from .generator import (
    INSTRUCTION_SYSTEM_MD,
    INSTRUCTION_SYSTEM_TEX,
    CvTailoring,
    MaterialDraft,
    _build_client,
    _instruction_md_prompt,
    _instruction_tex_prompt,
    _letter_tex,
    _load_evidence,
    _material_dir,
    _next_version,
    _read_cv_template,
    _record_material,
    _strip_code_fence,
    _write_metadata,
    assert_rewrite_grounded,
    compile_and_fit_cv,
    effective_cv_draft_json,
    render_cv,
)
from .latex import classify_cv_fit, compile_pdf, measure_pdf_extent
from .names import material_export_basename

ReviseMode = Literal["structured", "latex"]


class MaterialDraftPatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    bullets: list[str] | None = None
    body: str | None = None
    capabilities: list[str] | None = None
    experience: dict[str, list[str]] | None = None


class MaterialReviseRequest(BaseModel):
    mode: ReviseMode = "structured"
    draft: MaterialDraftPatch | None = None
    tex: str | None = None
    markdown_body: str | None = None


class MaterialInstructionRequest(BaseModel):
    instruction: str


def _merge_draft(existing: dict[str, Any] | None, patch: MaterialDraftPatch) -> MaterialDraft:
    base = dict(existing or {})
    updates = patch.model_dump(exclude_unset=True)
    base.update(updates)
    return MaterialDraft.model_validate(base)



def _named_tex_path(
    job: Job,
    material_type: str,
    version: int,
    out_dir: Path,
    *,
    candidate: str,
) -> Path:
    basename = material_export_basename(
        candidate=candidate,
        material_type=material_type,
        company=job.company,
        version=version,
    )
    return out_dir / f"{basename}.tex"


def _compile_tex_material(
    session: Session,
    job: Job,
    *,
    source: GeneratedMaterial,
    material_type: str,
    title: str,
    evidence_ids: list[str],
    draft_json: dict[str, Any] | None,
    tex_content: str,
    edited_via: str,
    settings: Settings,
    fit_client: Any = None,
) -> GeneratedMaterial:
    version = _next_version(session, job.id or 0, material_type)
    out_dir = _material_dir(job)
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = _named_tex_path(
        job, material_type, version, out_dir, candidate=settings.materials_export_name
    )
    tex_path.write_text(tex_content, encoding="utf-8")
    if material_type == "cv" and fit_client is not None:
        pdf_path, compile_status, page_count, page_fill = compile_and_fit_cv(
            tex_path, settings=settings, client=fit_client
        )
    else:
        pdf_path, compile_status = compile_pdf(tex_path)
        page_count, page_fill = measure_pdf_extent(pdf_path) if pdf_path else (None, None)
    status = "created_pdf" if pdf_path else compile_status
    material = _record_material(
        session,
        job,
        material_type=material_type,
        title=title,
        evidence_ids=evidence_ids,
        status=status,
        tex_path=tex_path,
        pdf_path=pdf_path,
        draft_json=draft_json,
        version=version,
        supersedes_id=source.id,
        page_count=page_count,
        page_fill=page_fill,
        audit_action=f"revise_{material_type}",
        audit_detail={"edited_via": edited_via, "supersedes_id": source.id},
    )
    _write_metadata(
        out_dir / "metadata.json",
        material,
        compile_status,
        settings.scoring_model,
        edited_via=edited_via,
    )
    return material


def revise_material(
    session: Session,
    job: Job,
    source: GeneratedMaterial,
    payload: MaterialReviseRequest,
    *,
    settings: Settings | None = None,
) -> GeneratedMaterial:
    settings = settings or get_settings()
    if source.job_id != job.id:
        raise ValueError("material does not belong to job")

    if source.material_type == "answer":
        if payload.mode == "latex":
            raise ValueError("latex edit is not supported for answers")
        if not payload.markdown_body:
            raise ValueError("markdown_body is required for answer revisions")
        draft = _merge_draft(source.draft_json, MaterialDraftPatch(body=payload.markdown_body))
        out_dir = _material_dir(job) / "answers"
        out_dir.mkdir(parents=True, exist_ok=True)
        from .generator import _slug

        slug = _slug(source.question or source.title)
        md_path = out_dir / f"{slug}.md"
        question = source.question or ""
        md_path.write_text(
            f"# {draft.title}\n\n**Question:** {question}\n\n{draft.body or ''}\n\n"
            f"Evidence: {', '.join(draft.evidence_ids)}\n",
            encoding="utf-8",
        )
        version = _next_version(session, job.id or 0, "answer")
        material = _record_material(
            session,
            job,
            material_type="answer",
            title=draft.title,
            evidence_ids=draft.evidence_ids,
            status="created_markdown",
            markdown_path=md_path,
            question=source.question,
            word_limit=source.word_limit,
            draft_json=draft.model_dump(),
            version=version,
            supersedes_id=source.id,
            audit_action="revise_answer",
            audit_detail={"supersedes_id": source.id},
        )
        _write_metadata(out_dir.parent / "metadata.json", material, "not_applicable", settings.scoring_model)
        return material

    if source.material_type not in {"cv", "cover_letter"}:
        raise ValueError(f"unsupported material type: {source.material_type}")

    if payload.mode == "latex":
        if not payload.tex:
            raise ValueError("tex is required for latex revisions")
        draft_json = source.draft_json
        return _compile_tex_material(
            session,
            job,
            source=source,
            material_type=source.material_type,
            title=source.title,
            evidence_ids=list(source.evidence_ids or []),
            draft_json=draft_json,
            tex_content=payload.tex,
            edited_via="latex",
            settings=settings,
        )

    if not source.draft_json and not payload.draft:
        raise ValueError("structured edit requires draft_json; regenerate this material first")
    patch = payload.draft or MaterialDraftPatch()

    if source.material_type == "cv":
        tailoring = CvTailoring.model_validate(source.draft_json or {})
        if patch.title is not None:
            tailoring.title = patch.title
        if patch.summary is not None:
            tailoring.summary = patch.summary
        if patch.capabilities is not None:
            tailoring.capabilities = patch.capabilities
        if patch.experience is not None:
            tailoring.experience = patch.experience
        rendered_tex = render_cv(tailoring, template_text=_read_cv_template(session))
        draft_json = effective_cv_draft_json(tailoring.model_dump(), tex_content=rendered_tex) or {}
        if isinstance(source.draft_json, dict) and "tailoring" in source.draft_json:
            draft_json["tailoring"] = source.draft_json["tailoring"]
        return _compile_tex_material(
            session,
            job,
            source=source,
            material_type="cv",
            title=tailoring.title,
            evidence_ids=list(tailoring.evidence_ids or []),
            draft_json=draft_json,
            tex_content=rendered_tex,
            edited_via="structured",
            settings=settings,
        )

    draft = _merge_draft(source.draft_json, patch)
    return _compile_tex_material(
        session,
        job,
        source=source,
        material_type=source.material_type,
        title=draft.title,
        evidence_ids=draft.evidence_ids,
        draft_json=draft.model_dump(),
        tex_content=_letter_tex(job, draft, settings),
        edited_via="structured",
        settings=settings,
    )


def revise_material_with_instruction(
    session: Session,
    job: Job,
    source: GeneratedMaterial,
    instruction: str,
    *,
    settings: Settings | None = None,
    client: Any = None,
) -> GeneratedMaterial:
    """Apply a free-text operator instruction via the LLM and create a new version."""
    settings = settings or get_settings()
    if source.job_id != job.id:
        raise ValueError("material does not belong to job")
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("instruction is required")

    client = client or _build_client(settings, session=session, entity_id=job.id)
    evidence = _load_evidence(session)

    if source.material_type == "answer":
        current = read_text_content(source) or (source.draft_json or {}).get("body") or ""
        revised = _strip_code_fence(
            client.complete_text(
                INSTRUCTION_SYSTEM_MD,
                _instruction_md_prompt(instruction, current, evidence),
                settings.scoring_model,
            )
        )
        if not revised.strip():
            raise ValueError("model returned an empty answer")
        # TP-01b: an LLM rewrite must not smuggle in an ungrounded figure/entity
        # that the operator's instruction did not authorise from the evidence bank.
        assert_rewrite_grounded(current, revised, evidence, job)
        return revise_material(
            session,
            job,
            source,
            MaterialReviseRequest(mode="structured", markdown_body=revised),
            settings=settings,
        )

    if source.material_type not in {"cv", "cover_letter"}:
        raise ValueError(f"unsupported material type: {source.material_type}")

    current_tex = read_text_content(source)
    if not current_tex:
        raise ValueError("current LaTeX source is unavailable; regenerate this material first")
    revised = _strip_code_fence(
        client.complete_text(
            INSTRUCTION_SYSTEM_TEX,
            _instruction_tex_prompt(source.material_type, instruction, current_tex, evidence),
            settings.scoring_model,
        )
    )
    if "\\begin{document}" not in revised and "\\documentclass" not in revised:
        raise ValueError("model did not return a valid LaTeX document")
    # TP-01b: only figures/entities new to the rewrite are checked, so template
    # constants are ignored and an instruction can't introduce a fabricated metric.
    assert_rewrite_grounded(current_tex, revised, evidence, job)
    return _compile_tex_material(
        session,
        job,
        source=source,
        material_type=source.material_type,
        title=source.title,
        evidence_ids=list(source.evidence_ids or []),
        draft_json=source.draft_json,
        tex_content=revised,
        edited_via="instruction",
        settings=settings,
    )


def fit_material_to_two_pages(
    session: Session,
    job: Job,
    source: GeneratedMaterial,
    *,
    settings: Settings | None = None,
    client: Any = None,
) -> GeneratedMaterial:
    """Nudge a CV toward a 1.85-1.98 page fit (LLM loop) and record a new version."""
    settings = settings or get_settings()
    if source.job_id != job.id:
        raise ValueError("material does not belong to job")
    if source.material_type != "cv":
        raise ValueError("page shortening only applies to CVs")
    if classify_cv_fit("cv", source.page_count, source.page_fill) == "ok":
        raise ValueError("this CV already fits within the target page range")
    current_tex = read_text_content(source)
    if not current_tex:
        raise ValueError("current LaTeX source is unavailable; regenerate this material first")
    client = client or _build_client(settings, session=session, entity_id=job.id)
    return _compile_tex_material(
        session,
        job,
        source=source,
        material_type="cv",
        title=source.title,
        evidence_ids=list(source.evidence_ids or []),
        draft_json=source.draft_json,
        tex_content=current_tex,
        edited_via="fit_pages",
        settings=settings,
        fit_client=client,
    )


def mark_material_final(session: Session, job: Job, material: GeneratedMaterial) -> GeneratedMaterial:
    if material.job_id != job.id:
        raise ValueError("material does not belong to job")
    siblings = session.exec(
        select(GeneratedMaterial).where(
            GeneratedMaterial.job_id == job.id,
            GeneratedMaterial.material_type == material.material_type,
        )
    ).all()
    for sibling in siblings:
        if sibling.is_final and sibling.id != material.id:
            sibling.is_final = False
            session.add(sibling)
    material.is_final = True
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.human,
        action="mark_material_final",
        entity_type="job",
        entity_id=job.id,
        detail={"material_id": material.id, "material_type": material.material_type, "version": material.version},
    )
    return material


def unmark_material_final(session: Session, job: Job, material: GeneratedMaterial) -> GeneratedMaterial:
    if material.job_id != job.id:
        raise ValueError("material does not belong to job")
    material.is_final = False
    session.add(material)
    session.commit()
    session.refresh(material)
    log_action(
        session,
        actor=ActorType.human,
        action="unmark_material_final",
        entity_type="job",
        entity_id=job.id,
        detail={"material_id": material.id, "material_type": material.material_type, "version": material.version},
    )
    return material


def preview_mode_for(material: GeneratedMaterial) -> str:
    if material.draft_json:
        return "structured"
    # Everything markdown-backed (answers, interview packs, debriefs, drafts)
    # previews as markdown; only cv/cover_letter fall through to LaTeX.
    if material.material_type not in {"cv", "cover_letter"}:
        return "markdown"
    if read_text_content(material):
        return "latex_fallback"
    return "unavailable"
