"""Filesystem helpers for generated materials (serve, preview, purge)."""

from __future__ import annotations

from pathlib import Path

from ..models import GeneratedMaterial

FileKind = str  # pdf | tex | md


def _materials_root() -> Path:
    from .generator import MATERIALS_ROOT

    root = MATERIALS_ROOT
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    return root.resolve()


def material_storage_dir(material: GeneratedMaterial) -> Path | None:
    if material.tex_path:
        return Path(material.tex_path).parent
    if material.markdown_path:
        path = Path(material.markdown_path)
        if path.parent.name == "answers":
            return path.parent.parent
        return path.parent
    return None


def _safe_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    root = _materials_root()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("material path outside storage root") from exc
    return candidate


def resolve_material_file(material: GeneratedMaterial, kind: FileKind) -> Path:
    if kind == "pdf":
        if material.material_type == "answer":
            raise ValueError("answers do not have pdf files")
        path = _safe_path(material.pdf_path)
        if path is None or not path.exists():
            raise FileNotFoundError("pdf not available")
        return path
    if kind == "tex":
        if material.material_type not in {"cv", "cover_letter"}:
            raise ValueError("tex is only available for cv and cover letter materials")
        path = _safe_path(material.tex_path)
        if path is None or not path.exists():
            raise FileNotFoundError("tex not available")
        return path
    if kind == "md":
        # Answers and internal interview artifacts (packs, debriefs, drafts)
        # are markdown-backed; CV/cover-letter stay tex/pdf-only.
        if material.material_type in {"cv", "cover_letter"}:
            raise ValueError("markdown is not available for cv and cover letter materials")
        path = _safe_path(material.markdown_path)
        if path is None or not path.exists():
            raise FileNotFoundError("markdown not available")
        return path
    raise ValueError(f"unsupported file kind: {kind}")


def file_available(material: GeneratedMaterial, kind: FileKind) -> bool:
    try:
        resolve_material_file(material, kind)
        return True
    except (ValueError, FileNotFoundError):
        return False


def read_text_content(material: GeneratedMaterial) -> str | None:
    if material.material_type not in {"cv", "cover_letter"}:
        try:
            return resolve_material_file(material, "md").read_text(encoding="utf-8")
        except (ValueError, FileNotFoundError):
            return None
    try:
        return resolve_material_file(material, "tex").read_text(encoding="utf-8")
    except (ValueError, FileNotFoundError):
        return None


def delete_material_files(material: GeneratedMaterial) -> None:
    storage_dir = material_storage_dir(material)
    if storage_dir is None or not storage_dir.exists():
        return
    safe_dir = _safe_path(str(storage_dir))
    if safe_dir is None:
        return
    for child in sorted(safe_dir.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink(missing_ok=True)
    for child in sorted(safe_dir.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    safe_dir.rmdir()
