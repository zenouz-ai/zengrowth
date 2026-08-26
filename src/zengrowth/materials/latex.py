"""LaTeX helpers for generated application materials."""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from pathlib import Path

_WS_RE = re.compile(r"\s+")
# Macros whose braced argument becomes plain text (order matters for nested unwrap).
_UNWRAP_MACROS = ("textbf", "emph", "textit", "textrm", "textsf", "texttt")

# A finished CV must run to two pages, with the second page filled close to the
# bottom margin but not overflowing onto a third page. These bounds describe the
# acceptable fill of the final page (a 0..1 proxy from ``measure_pdf_extent``),
# i.e. a target of roughly 1.85-1.98 rendered pages.
CV_TARGET_FILL_MIN = 0.85
CV_TARGET_FILL_MAX = 0.98


def classify_cv_fit(
    material_type: str, page_count: int | None, page_fill: float | None
) -> str:
    """Classify a CV's page fit as ``ok``/``long``/``short``/``unknown``.

    CVs should land on exactly two pages with the final page filled between
    ``CV_TARGET_FILL_MIN`` and ``CV_TARGET_FILL_MAX``. Non-CV materials and
    materials with unknown extent return ``unknown``.
    """
    if material_type != "cv" or page_count is None:
        return "unknown"
    if page_count > 2:
        return "long"
    if page_count < 2:
        return "short"
    if page_fill is None:
        return "unknown"
    if page_fill > CV_TARGET_FILL_MAX:
        return "long"
    if page_fill < CV_TARGET_FILL_MIN:
        return "short"
    return "ok"


def latex_to_plain(text: str | None) -> str:
    """Convert LaTeX CV summary text to plain prose for structured editing.

    ``render_cv`` always escapes the summary as plain text; template backfill and
    LLM copy-paste can leave ``\\pounds``, ``\\textbf{}``, etc. in ``draft_json``.
    """
    if not text:
        return ""
    value = text.strip()
    for _ in range(8):
        before = value
        for macro in _UNWRAP_MACROS:
            value = re.sub(rf"\\{macro}\{{([^{{}}]*)\}}", r"\1", value)
        value = re.sub(r"\\pounds\s*\{\s*\}", "£", value)
        value = re.sub(r"\\pounds(?![a-zA-Z])", "£", value)
        value = value.replace(r"\&", "&")
        value = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", value)
        value = re.sub(r"\\[a-zA-Z]+", " ", value)
        if value == before:
            break
    value = value.replace("$", " ").replace("{", " ").replace("}", " ")
    return _WS_RE.sub(" ", value).strip()


def escape_latex(text: str | None) -> str:
    if not text:
        return ""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "£": r"\pounds{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def compile_pdf(tex_path: Path) -> tuple[Path | None, str]:
    compiler = shutil.which("latexmk") or shutil.which("pdflatex")
    if compiler is None:
        return None, "pdf_unavailable_no_latex_compiler"
    cmd = (
        [compiler, "-pdf", "-interaction=nonstopmode", tex_path.name]
        if Path(compiler).name == "latexmk"
        else [compiler, "-interaction=nonstopmode", tex_path.name]
    )
    proc = subprocess.run(
        cmd,
        cwd=tex_path.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    pdf_path = tex_path.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf_path.exists():
        return None, f"pdf_compile_failed: {(proc.stderr or proc.stdout)[-500:]}"
    return pdf_path, "pdf_created"


def measure_pdf_extent(pdf_path: Path) -> tuple[int | None, float | None]:
    """Return ``(page_count, last_page_fill)`` for a PDF.

    ``last_page_fill`` is a 0..1 proxy for how far down the last page content
    reaches (1.0 == content runs to the bottom margin), derived from the lowest
    text baseline. Returns ``(None, None)`` when the file cannot be read and a
    ``None`` fill when text positions cannot be extracted.
    """
    try:
        from pypdf import PdfReader
    except Exception:  # pragma: no cover - pypdf is a hard dependency
        return None, None
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        if page_count == 0:
            return 0, None
        last = reader.pages[-1]
        height = float(last.mediabox.height)
        ys: list[float] = []

        def _visit(text, cm, tm, font_dict, font_size):  # noqa: ANN001
            if text and text.strip():
                with contextlib.suppress(Exception):
                    ys.append(float(tm[5]))

        try:
            last.extract_text(visitor_text=_visit)
        except Exception:
            return page_count, None
        if not ys or height <= 0:
            return page_count, None
        fill = 1.0 - (min(ys) / height)
        return page_count, round(max(0.0, min(1.0, fill)), 3)
    except Exception:
        return None, None
