"""Evidence-grounded CV, cover letter, and answer generation."""

from __future__ import annotations

import json
import re
from collections import Counter
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
    GENERIC_ACRONYMS,
    compose_summary_from_claims,
    cv_entity_allowlist,
    cv_grounding_corpus,
    cv_grounding_profile,
    detect_alignment_gaps,
    entity_tokens,
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

# Private aliases kept for the existing call sites in this module and in
# ``knowledge.service``, which import them from here.
_GENERIC_ACRONYMS = GENERIC_ACRONYMS
_entity_tokens = entity_tokens

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
headers. Tighten the wording *inside* existing lines and remove redundant phrasing, but keep every
section, bullet, and capability line: do not delete, merge, or add lines, and do not invent content
or change employers, dates, or metrics. Keeping the line counts identical is required — the CV must
still round-trip through the structured editor. Return ONLY the full revised LaTeX document, with no commentary and no
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
            settings.material_model(),
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
            settings.material_model(),
            operation_name="cv_fit_loosen",
        )
    )
    return _valid_tex(revised, current_tex)


# Layout-only LaTeX that a typography pass may add or change without altering
# what the document says: spacing/length commands with their dimension
# arguments, and ``\\[2pt]`` line breaks.
_LAYOUT_CMD_RE = re.compile(
    r"\\(?:vspace|hspace|vskip|hskip|setlength|addtolength|linespread|fontsize|"
    r"enlargethispage|titlespacing|setlist|setstretch)\*?"
    r"(?:\s*\{[^{}]*\}|\s*\[[^\]]*\]|\s*-?[\d.]+\s*(?:pt|em|ex|mm|cm|in|bp))*"
)
_LINE_BREAK_RE = re.compile(r"\\\\(?:\s*\[[^\]]*\])?")
_BODY_RE = re.compile(r"\\begin\{document\}(.*?)(?:\\end\{document\}|\Z)", re.DOTALL)
def _strip_tex_comments(text: str) -> str:
    r"""Drop ``%`` comments, honouring escaping by *parity* of backslashes.

    A comment hides the rest of its line from the compiler, so commented-out text
    must not count as document content — otherwise a "typography" rewrite could
    comment out a bullet, leave the words in the source, and pass the
    unchanged-wording check while the bullet vanished from the PDF.

    Parity matters: ``\%`` is a literal percent sign, but ``\\%`` is a line break
    *followed by* a comment, which a simple "not preceded by a backslash" test
    reads as escaped. Count the run of backslashes instead: even means the ``%``
    starts a comment.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        backslashes = 0
        cut: int | None = None
        for index, char in enumerate(line):
            if char == "\\":
                backslashes += 1
                continue
            if char == "%" and backslashes % 2 == 0:
                cut = index
                break
            backslashes = 0
        lines.append(line if cut is None else line[:cut])
    return "\n".join(lines)
# Environment delimiters and their typography arguments carry no document words:
# ``\begin{itemize}[itemsep=2pt]``, ``\begin{spacing}{1.1}``. Dropping them lets a
# genuine typography pass restyle lists and line spacing without tripping the
# "wording changed" check, while any real word it touches still shows up. The
# braced dimension is only consumed *as an environment argument* — a bare
# ``{2024}`` elsewhere in the body is visible content and must stay comparable.
_ENV_RE = re.compile(
    r"\\(?:begin|end)\s*\{[^{}]*\}"
    r"(?:\s*\[[^\]]*\])?"
    r"(?:\s*\{\s*-?[\d.]+\s*(?:pt|em|ex|mm|cm|in|bp|\\[a-zA-Z]+)?\s*\})?"
)
_KEY_VALUE_OPT_RE = re.compile(r"\[[^\]]*=[^\]]*\]")


def _document_plain_text(tex: str) -> str:
    """Plain text of the document body with layout-only LaTeX removed.

    The preamble (geometry, fonts) is ignored so the fit gates compare what the
    CV *says*, not how it is typeset.
    """
    match = _BODY_RE.search(tex)
    body = match.group(1) if match else tex
    body = _strip_tex_comments(body)
    for pattern in (_LAYOUT_CMD_RE, _ENV_RE, _KEY_VALUE_OPT_RE, _LINE_BREAK_RE):
        body = pattern.sub(" ", body)
    return latex_to_plain(body)


def _document_tokens(tex: str) -> list[str]:
    return [tok.casefold() for tok in re.findall(r"\w+", _document_plain_text(tex))]


# Commands a page-fit pass may legitimately introduce. Everything here changes
# only typography/geometry. The point of the allowlist is that word-level
# comparison cannot see content hidden by a *construct*: ``\iffalse ... \fi``,
# ``\phantom{...}``, white text, or a `comment` environment all leave the words in
# the source while removing them from the PDF, exactly like a ``%`` comment.
_FIT_ALLOWED_NEW_COMMANDS = frozenset(
    {
        "vspace", "hspace", "vskip", "hskip", "smallskip", "medskip", "bigskip",
        "vfill", "hfill", "setlength", "addtolength", "linespread", "setstretch",
        "singlespacing", "onehalfspacing", "fontsize", "selectfont", "tiny",
        "scriptsize", "footnotesize", "small", "normalsize", "large", "Large",
        "LARGE", "geometry", "newgeometry", "setlist", "titlespacing",
        "enlargethispage", "raggedbottom", "flushbottom", "usepackage",
        "baselineskip", "parskip", "parindent", "itemsep", "topsep", "partopsep",
        "begin", "end", "item", "clearpage", "pagebreak", "needspace",
    }
)


# Environments a fit pass may introduce. Anything else is rejected: a `comment`
# environment (or any other content-swallowing environment) keeps the words in the
# source while removing them from the PDF, and ``_ENV_RE`` strips the delimiters
# before the token comparison, so source-token equality cannot see it.
_FIT_ALLOWED_NEW_ENVIRONMENTS = frozenset(
    {"spacing", "singlespace", "onehalfspace", "doublespace", "adjustwidth", "itemize", "enumerate"}
)
_BEGIN_ENV_RE = re.compile(r"\\begin\s*\{([^{}]*)\}")


_CONTENT_HIDING_COMMANDS = frozenset({"phantom", "hphantom", "vphantom", "textcolor", "color"})
_CONTENT_HIDING_ENVIRONMENTS = frozenset({"comment"})
# Longer phantom variants first so ``\hphantom`` is not split as ``\phantom``.
_HIDING_CMD_START_RE = re.compile(r"\\(hphantom|vphantom|phantom|textcolor)\b")
_COLOR_START_RE = re.compile(r"\\color\b")
_IFFALSE_START_RE = re.compile(r"\\iffalse\b")
# TeX/e-TeX conditional primitives only — macros like ``\ifthenelse`` must not
# bump depth or an enclosing ``\iffalse`` collapses to ``<unparsed>``.
_TEX_IF_PRIMITIVES = frozenset(
    {
        "if",
        "ifcat",
        "ifnum",
        "ifdim",
        "ifodd",
        "ifvmode",
        "ifhmode",
        "ifmmode",
        "ifinner",
        "ifvoid",
        "ifhbox",
        "ifvbox",
        "ifx",
        "ifeof",
        "iftrue",
        "iffalse",
        "ifcase",
        "ifdefined",
        "ifcsname",
        "iffontchar",
    }
)
_IF_DEPTH_TOKEN_RE = re.compile(r"\\(if[a-zA-Z]*|fi)\b")
_NEWIF_RE = re.compile(r"\\newif\s*\\(if[a-zA-Z]+)")


def _consume_braced_group(tex: str, start: int) -> tuple[str, int] | None:
    """Return ``({...}, end_index)`` for a brace-balanced group starting at ``start``.

    Escaped braces (``\\{`` / ``\\}``) are literal. Unescaped ``%`` starts a
    line comment whose braces are ignored through the next newline.
    """
    if start >= len(tex) or tex[start] != "{":
        return None
    depth = 0
    index = start
    while index < len(tex):
        char = tex[index]
        if char == "\\":
            index += 2 if index + 1 < len(tex) else 1
            continue
        if char == "%":
            newline = tex.find("\n", index)
            index = len(tex) if newline < 0 else newline + 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return tex[start : index + 1], index + 1
        index += 1
    return None


def _consume_bracket_group(tex: str, start: int) -> tuple[str, int] | None:
    """Return ``([...], end_index)`` for a bracket-balanced group starting at ``start``."""
    if start >= len(tex) or tex[start] != "[":
        return None
    depth = 0
    index = start
    while index < len(tex):
        char = tex[index]
        if char == "\\":
            index += 2 if index + 1 < len(tex) else 1
            continue
        if char == "%":
            newline = tex.find("\n", index)
            index = len(tex) if newline < 0 else newline + 1
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return tex[start : index + 1], index + 1
        index += 1
    return None


def _in_tex_line_comment(tex: str, index: int) -> bool:
    """True if ``index`` falls after an unescaped ``%`` on its line."""
    line_start = tex.rfind("\n", 0, index) + 1
    backslashes = 0
    pos = line_start
    while pos < index:
        char = tex[pos]
        if char == "\\":
            backslashes += 1
            pos += 1
            continue
        if char == "%" and backslashes % 2 == 0:
            return True
        backslashes = 0
        pos += 1
    return False


_DEFINECOLOR_RE = re.compile(
    r"\\definecolor\s*\{([^{}]+)\}\s*\{([^{}]+)\}\s*\{([^{}]*)\}"
)
_COLORLET_RE = re.compile(r"\\colorlet\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
_ENV_TOKEN_RE = re.compile(r"\\(begin|end)\s*\{")
_GROUP_TOKEN_RE = re.compile(r"\\(begingroup|bgroup|endgroup|egroup)\b")
# Hiding threshold: every RGB channel at or above this reads as white on paper.
_NEAR_WHITE_MIN = 0.95
_XCOLOR_NAMED_RGB: dict[str, tuple[float, float, float]] = {
    "white": (1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "cyan": (0.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "gray": (0.5, 0.5, 0.5),
    "darkgray": (0.25, 0.25, 0.25),
    "lightgray": (0.75, 0.75, 0.75),
    "brown": (0.75, 0.5, 0.25),
    "lime": (0.75, 1.0, 0.0),
    "olive": (0.5, 0.5, 0.0),
    "orange": (1.0, 0.5, 0.0),
    "pink": (1.0, 0.75, 0.75),
    "purple": (0.75, 0.0, 0.25),
    "teal": (0.0, 0.5, 0.5),
    "violet": (0.5, 0.0, 0.5),
}


def _local_color_aliases(tex: str) -> dict[str, tuple[str, str]]:
    """Map locally defined colour names to ``(model, spec)`` for white detection."""
    aliases: dict[str, tuple[str, str]] = {}
    for match in _DEFINECOLOR_RE.finditer(tex):
        if _in_tex_line_comment(tex, match.start()):
            continue
        aliases[match.group(1).strip()] = (match.group(2).strip(), match.group(3).strip())
    for match in _COLORLET_RE.finditer(tex):
        if _in_tex_line_comment(tex, match.start()):
            continue
        aliases[match.group(1).strip()] = ("named", match.group(2).strip())
    return aliases


def _resolve_color_rgb(
    optional: str,
    color_arg: str,
    *,
    aliases: dict[str, tuple[str, str]],
    seen: frozenset[str],
) -> tuple[float, float, float] | None:
    """Rendered RGB of an xcolor spec, or ``None`` when it cannot be resolved."""
    inner = color_arg.strip().strip("{}").replace(" ", "")
    if not inner:
        return None
    model_raw = optional.strip().strip("[]").strip()
    model = model_raw.casefold()
    try:
        if not model or model == "named":
            return _resolve_color_expression(inner, aliases=aliases, seen=seen)
        if model == "html":
            hex_ = inner.lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", hex_):
                return None
            red, green, blue = (int(hex_[i : i + 2], 16) / 255 for i in (0, 2, 4))
            return (red, green, blue)
        if model_raw == "rgb":
            parts = [float(p) for p in inner.split(",")]
            return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None
        if model_raw == "RGB":
            parts = [float(p) / 255 for p in inner.split(",")]
            return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None
        if model == "gray":
            level = float(inner)
            return (level, level, level)
        if model == "cmyk":
            parts = [float(p) for p in inner.split(",")]
            if len(parts) != 4:
                return None
            c, m, y, k = parts
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    except ValueError:
        return None
    return None


def _resolve_color_name(
    name: str, *, aliases: dict[str, tuple[str, str]], seen: frozenset[str]
) -> tuple[float, float, float] | None:
    """RGB for a bare colour name: xcolor base names, hex shorthands, local aliases."""
    folded = name.casefold().lstrip("#")
    if folded in _XCOLOR_NAMED_RGB:
        return _XCOLOR_NAMED_RGB[folded]
    if re.fullmatch(r"f{3}(?:f{3})?", folded):
        return (1.0, 1.0, 1.0)
    for key in (name, folded):
        if key in aliases and key not in seen:
            alias_model, alias_spec = aliases[key]
            opt = f"[{alias_model}]" if alias_model.casefold() != "named" else ""
            return _resolve_color_rgb(opt, f"{{{alias_spec}}}", aliases=aliases, seen=seen | {key})
    return None


def _resolve_color_expression(
    expr: str, *, aliases: dict[str, tuple[str, str]], seen: frozenset[str]
) -> tuple[float, float, float] | None:
    r"""Evaluate an xcolor mix such as ``black!0``, ``white!50!black``, ``-red``.

    ``c!p`` is ``p%`` of ``c`` plus ``(100-p)%`` of the next colour, which
    defaults to white when omitted; mixes chain left to right. A component that
    cannot be resolved only matters when it carries weight.
    """
    complement = False
    while expr.startswith("-"):
        complement = not complement
        expr = expr[1:]
    parts = expr.split("!")
    current = _resolve_color_name(parts[0], aliases=aliases, seen=seen)
    index = 1
    while index < len(parts):
        pct = min(max(float(parts[index]), 0.0), 100.0) / 100
        nxt_name = parts[index + 1] if index + 1 < len(parts) else "white"
        nxt = _resolve_color_name(nxt_name, aliases=aliases, seen=seen)
        if (current is None and pct > 0) or (nxt is None and pct < 1):
            return None
        if current is None:
            current = nxt
        elif nxt is not None:
            r0, g0, b0 = current
            r1, g1, b1 = nxt
            current = (
                pct * r0 + (1 - pct) * r1,
                pct * g0 + (1 - pct) * g1,
                pct * b0 + (1 - pct) * b1,
            )
        index += 2
    if current is None:
        return None
    if complement:
        current = (1 - current[0], 1 - current[1], 1 - current[2])
    return current


def _is_hiding_color(
    optional: str,
    color_arg: str,
    *,
    aliases: dict[str, tuple[str, str]] | None = None,
) -> bool:
    """True for colours that render white / near-white, incl. xcolor models and mixes."""
    rgb = _resolve_color_rgb(optional, color_arg, aliases=aliases or {}, seen=frozenset())
    return rgb is not None and min(rgb) >= _NEAR_WHITE_MIN


def _next_scoped_end(
    pattern: re.Pattern[str], openers: set[str], tex: str, pos: int
) -> int | None:
    """Offset of the closer that ends the scope containing ``pos`` (nesting-aware)."""
    depth = 0
    token = _next_control_match(pattern, tex, pos)
    while token is not None:
        if token.group(1) in openers:
            depth += 1
        elif depth == 0:
            return token.start()
        else:
            depth -= 1
        token = _next_control_match(pattern, tex, token.end())
    return None


def _preceded_by_odd_backslashes(tex: str, index: int) -> bool:
    """True when ``tex[index]`` is the second ``\\`` of a ``\\\\`` control symbol, etc."""
    count = 0
    pos = index - 1
    while pos >= 0 and tex[pos] == "\\":
        count += 1
        pos -= 1
    return count % 2 == 1


def _next_control_match(pattern: re.Pattern[str], tex: str, pos: int) -> re.Match[str] | None:
    """Search for a control-sequence match that is not commented or mid-backslash-run."""
    token = pattern.search(tex, pos)
    while token is not None:
        if _in_tex_line_comment(tex, token.start()) or _preceded_by_odd_backslashes(tex, token.start()):
            token = pattern.search(tex, token.start() + 1)
            continue
        return token
    return None




def _content_hiding_iffalse_fingerprints(tex: str) -> Counter[str]:
    """Depth-balanced ``\\iffalse ... \\fi`` blocks (nested TeX and ``\\newif`` conditionals)."""
    conditionals = set(_TEX_IF_PRIMITIVES)
    for newif in _NEWIF_RE.finditer(tex):
        if not _in_tex_line_comment(tex, newif.start()):
            conditionals.add(newif.group(1))
    counts: Counter[str] = Counter()
    pos = 0
    while True:
        match = _next_control_match(_IFFALSE_START_RE, tex, pos)
        if match is None:
            break
        start = match.start()
        scan = match.end()
        depth = 1
        end: int | None = None
        while depth > 0:
            token = _next_control_match(_IF_DEPTH_TOKEN_RE, tex, scan)
            if token is None:
                break
            name = token.group(1)
            if name == "fi":
                depth -= 1
            elif name in conditionals:
                depth += 1
            scan = token.end()
            if depth == 0:
                end = scan
                break
        if end is not None:
            counts[tex[start:end]] += 1
            pos = end
        else:
            counts[r"\iffalse<unparsed>"] += 1
            pos = match.end()
    return counts


def _color_span_plain_tokens(body: str) -> str:
    """Content-word fingerprint of a ``\\color`` span; typography edits are ignored."""
    stripped = body
    for pattern in (_LAYOUT_CMD_RE, _ENV_RE, _KEY_VALUE_OPT_RE, _LINE_BREAK_RE):
        stripped = pattern.sub(" ", stripped)
    plain = latex_to_plain(stripped)
    return " ".join(tok.casefold() for tok in re.findall(r"\w+", plain))


def _content_hiding_color_fingerprints(
    tex: str, *, aliases: dict[str, tuple[str, str]] | None = None
) -> Counter[str]:
    r"""Hiding ``\color{white/...}`` regions only (visible colours are not fingerprinted).

    Braced ``{\color{white}x}`` applies until the enclosing ``}``. Declaration form
    runs until the next ``\color`` or the ``\endgroup``/``\egroup``/``\end{...}`` that
    closes its enclosing scope (nested groups and environments are skipped), or EOF.
    Bodies use content-word tokens so allowlisted typography inside a white span is
    ignored, while moving words in still diffs. Ordinary ``\color{black}`` is left
    to the shorten/loosen word gates so legitimate edits are not blocked.
    """
    aliases = aliases if aliases is not None else _local_color_aliases(tex)
    counts: Counter[str] = Counter()
    for match in _COLOR_START_RE.finditer(tex):
        if _in_tex_line_comment(tex, match.start()) or _preceded_by_odd_backslashes(
            tex, match.start()
        ):
            continue
        pos = match.end()
        optional = ""
        ok = True
        while pos < len(tex) and tex[pos].isspace():
            pos += 1
        if pos < len(tex) and tex[pos] == "[":
            consumed_opt = _consume_bracket_group(tex, pos)
            if consumed_opt is None:
                ok = False
            else:
                optional, pos = consumed_opt
        if ok:
            while pos < len(tex) and tex[pos].isspace():
                pos += 1
            consumed = _consume_braced_group(tex, pos)
            if consumed is None:
                ok = False
            else:
                color_arg, pos = consumed
        if not ok:
            counts[r"\color<unparsed>"] += 1
            continue
        if not _is_hiding_color(optional, color_arg, aliases=aliases):
            continue
        depth = 0
        end: int | None = None
        index = pos
        while index < len(tex):
            char = tex[index]
            if char == "\\":
                index += 2 if index + 1 < len(tex) else 1
                continue
            if char == "%":
                newline = tex.find("\n", index)
                index = len(tex) if newline < 0 else newline + 1
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                if depth == 0:
                    end = index
                    break
                depth -= 1
            index += 1
        if end is None:
            next_color = _next_control_match(_COLOR_START_RE, tex, pos)
            ends = [
                e
                for e in (
                    next_color.start() if next_color is not None else None,
                    _next_scoped_end(_GROUP_TOKEN_RE, {"begingroup", "bgroup"}, tex, pos),
                    _next_scoped_end(_ENV_TOKEN_RE, {"begin"}, tex, pos),
                )
                if e is not None
            ]
            end = min(ends) if ends else len(tex)
        body = tex[pos:end]
        counts[f"\\color{optional}{color_arg}:{_color_span_plain_tokens(body)}"] += 1
    return counts


def _content_hiding_command_fingerprints(tex: str) -> Counter[str]:
    """Brace-aware fingerprints of content-hiding command invocations.

    Nested args matter: ``\\phantom{\\textbf{x}}`` must be distinct from
    ``\\phantom{\\textbf{x} Led the team.}`` — a non-nested ``[^{}]*`` matcher
    collapses both to the same ``\\phantom`` + ``\\textbf{x}`` pieces.

    ``\\textcolor`` may take an optional model (``[HTML]`` / ``[rgb]``) before its
    braced colour and body; only *hiding* colours (white / near-white, including
    model forms and local ``\\definecolor`` aliases) are fingerprinted so shortening
    inside ``\\textcolor{black}{...}`` is not blocked. ``\\hphantom`` / ``\\vphantom``,
    hiding ``\\color``, and depth-balanced ``\\iffalse`` blocks are included too.
    Unparsable invocations are still counted so the gate fails closed.
    """
    aliases = _local_color_aliases(tex)
    counts: Counter[str] = Counter()
    for match in _HIDING_CMD_START_RE.finditer(tex):
        if _in_tex_line_comment(tex, match.start()) or _preceded_by_odd_backslashes(
            tex, match.start()
        ):
            continue
        name = match.group(1)
        pos = match.end()
        optional = ""
        args: list[str] = []
        needed = 2 if name == "textcolor" else 1
        ok = True
        while pos < len(tex) and tex[pos].isspace():
            pos += 1
        if name == "textcolor" and pos < len(tex) and tex[pos] == "[":
            consumed_opt = _consume_bracket_group(tex, pos)
            if consumed_opt is None:
                ok = False
            else:
                optional, pos = consumed_opt
        if ok:
            for _ in range(needed):
                while pos < len(tex) and tex[pos].isspace():
                    pos += 1
                consumed = _consume_braced_group(tex, pos)
                if consumed is None:
                    ok = False
                    break
                arg, pos = consumed
                args.append(arg)
        if ok:
            if name == "textcolor" and not _is_hiding_color(
                optional, args[0], aliases=aliases
            ):
                continue
            counts[f"\\{name}{optional}{''.join(args)}"] += 1
        else:
            counts[f"\\{name}<unparsed>"] += 1
    counts.update(_content_hiding_color_fingerprints(tex, aliases=aliases))
    counts.update(_content_hiding_iffalse_fingerprints(tex))
    return counts


def _content_hiding_environment_fingerprints(tex: str) -> Counter[str]:
    """Fingerprint content-hiding environments, skipping commented delimiters."""
    counts: Counter[str] = Counter()
    for env in _CONTENT_HIDING_ENVIRONMENTS:
        begin_re = re.compile(rf"\\begin\s*\{{{re.escape(env)}\}}")
        end_re = re.compile(rf"\\end\s*\{{{re.escape(env)}\}}")
        pos = 0
        while True:
            begin = _next_control_match(begin_re, tex, pos)
            if begin is None:
                break
            end = _next_control_match(end_re, tex, begin.end())
            if end is None:
                counts[rf"\begin{{{env}}}<unparsed>"] += 1
                pos = begin.end()
                continue
            counts[tex[begin.start() : end.end()]] += 1
            pos = end.end()
    return counts


def _new_environment_names(current_tex: str, revised_tex: str) -> list[str]:
    """Non-typography environments added by count, or content-hiding blocks relocated."""
    before = Counter(_BEGIN_ENV_RE.findall(current_tex))
    after = Counter(_BEGIN_ENV_RE.findall(revised_tex))
    names = {
        env
        for env, count in after.items()
        if env not in _FIT_ALLOWED_NEW_ENVIRONMENTS and count > before.get(env, 0)
    }
    if _content_hiding_environment_fingerprints(current_tex) != _content_hiding_environment_fingerprints(
        revised_tex
    ):
        names.update(_CONTENT_HIDING_ENVIRONMENTS)
    return sorted(names)


def _new_command_names(current_tex: str, revised_tex: str) -> list[str]:
    """Non-typography commands newly introduced, or content-hiding args relocated."""
    # _CMD_RE is defined later in this module; looked up at call time.
    before = Counter(_CMD_RE.findall(current_tex))
    after = Counter(_CMD_RE.findall(revised_tex))
    allowed = {rf"\{name}" for name in _FIT_ALLOWED_NEW_COMMANDS}
    names = {
        cmd for cmd, count in after.items() if cmd not in allowed and count > before.get(cmd, 0)
    }
    before_fp = _content_hiding_command_fingerprints(current_tex)
    after_fp = _content_hiding_command_fingerprints(revised_tex)
    if before_fp != after_fp:
        for key in set(before_fp) | set(after_fp):
            if before_fp.get(key, 0) == after_fp.get(key, 0):
                continue
            match = re.match(r"\\([a-zA-Z]+)", key)
            names.add(rf"\{match.group(1)}" if match else key)
    return sorted(names)


_SECTION_CMD_RE = re.compile(r"\\(?:sub)?section\*?\s*\{")
_ITEM_CMD_RE = re.compile(r"\\item\b")


def _structure_counts(tex: str) -> tuple[int, tuple[int, ...], int, int]:
    r"""Structural fingerprint of a CV: template groups plus raw item/section counts.

    The raw counts are the fail-closed half: ``_parse_cv_template`` only matches
    the checked-in template's exact headings, so a promoted ``.tex`` using
    ``\section{Experience}`` (or any other layout) parses to *no* groups — making a
    group-count comparison vacuously equal while a rewrite quietly deleted
    bullets or a whole section. ``\item`` and section counts are layout-agnostic,
    so every CV keeps a structural invariant.
    """
    parsed = _parse_cv_template(tex)
    body = _strip_tex_comments(tex)
    return (
        len(parsed["capabilities"]),
        tuple(len(role) for role in parsed["experience"]),
        len(_ITEM_CMD_RE.findall(body)),
        len(_SECTION_CMD_RE.findall(body)),
    )


def _structure_count_changes(current_tex: str, revised_tex: str) -> list[str]:
    """Reject a shortening pass that adds or removes whole lines.

    The CV path is structure-preserving: ``render_cv`` only substitutes groups
    whose line counts match the active template. If a fit rewrite dropped a
    bullet, the shorter list stored in ``draft_json`` would no longer match, so a
    later structured edit would silently fall back to the template group —
    resurrecting the removed line and discarding the operator's edit. Keeping
    counts stable means a fitted CV still round-trips through the editor, and the
    fit pass stays a wording-tightening step rather than a content-removal one.
    """
    before_caps, before_roles, before_items, before_sections = _structure_counts(current_tex)
    after_caps, after_roles, after_items, after_sections = _structure_counts(revised_tex)
    problems: list[str] = []
    if before_caps != after_caps:
        problems.append(f"fit rewrite changed capability line count ({before_caps} -> {after_caps})")
    if before_roles != after_roles:
        problems.append(f"fit rewrite changed experience bullet counts ({before_roles} -> {after_roles})")
    if before_items != after_items:
        problems.append(f"fit rewrite changed bullet count ({before_items} -> {after_items})")
    if before_sections != after_sections:
        problems.append(f"fit rewrite changed section count ({before_sections} -> {after_sections})")
    return problems


def fit_rewrite_violations(
    kind: str,
    current_tex: str,
    revised_tex: str,
    *,
    evidence: list[ParsedEvidence] | None = None,
    job: Job | None = None,
) -> list[str]:
    """Why an LLM page-fit rewrite must be rejected (empty list == accept).

    ``loosen`` is a typography pass, so the document's words must be unchanged.
    ``shorten`` may drop and rephrase content, but must not add a figure or
    named entity that is absent from both the current CV and the evidence/job
    context (TP-01b), nor any content word that is absent from both (TP-05).
    Without evidence/job context, only words already in the CV are allowed.
    """
    # Either pass may only introduce typography commands: a construct such as
    # ``\iffalse``, ``\phantom``, or white text would hide content from the PDF
    # while leaving the words in the source, which a word-level check cannot see.
    if new_commands := _new_command_names(current_tex, revised_tex):
        return [f"fit rewrite introduced non-typography commands {new_commands[:8]}"]
    if new_envs := _new_environment_names(current_tex, revised_tex):
        return [f"fit rewrite introduced non-typography environments {new_envs[:8]}"]
    # Structure is checked on both passes: a typography edit that deletes an
    # ``\item`` or a section heading leaves the words untouched (so the token
    # comparison below cannot see it) while visibly restructuring the page.
    if counts := _structure_count_changes(current_tex, revised_tex):
        return counts
    if kind == "loosen":
        if _document_tokens(revised_tex) != _document_tokens(current_tex):
            return ["typography pass changed the document's wording"]
        return []
    # Custom-macro CVs may have no items or sections at all, leaving the
    # fingerprint above blind; explicit line breaks are the remaining
    # layout-agnostic signal that a whole line went missing. Only checked when
    # shortening — a typography pass legitimately adds ``\\[4pt]`` for spacing.
    before_breaks = len(_LINE_BREAK_RE.findall(_strip_tex_comments(current_tex)))
    after_breaks = len(_LINE_BREAK_RE.findall(_strip_tex_comments(revised_tex)))
    if before_breaks != after_breaks:
        return [f"fit rewrite changed explicit line-break count ({before_breaks} -> {after_breaks})"]
    current_plain = _document_plain_text(current_tex)
    revised_plain = _document_plain_text(revised_tex)
    violations: list[str] = []
    if evidence is not None and job is not None:
        try:
            assert_rewrite_grounded(current_plain, revised_plain, evidence, job)
        except ValueError as exc:
            violations.append(str(exc))
        allowed_words = _content_words(_evidence_text(evidence))
    else:
        new_nums = sorted(_num_tokens(revised_plain) - _num_tokens(current_plain))
        new_ents = sorted(_entity_tokens(revised_plain) - _entity_tokens(current_plain))
        if new_nums or new_ents:
            violations.append(f"shortened CV adds figures/references {new_nums + new_ents}")
        allowed_words = set()
    allowed_words |= _content_words(current_plain) | _GROUNDING_STOPWORDS
    new_words = sorted(_content_words(revised_plain) - allowed_words)
    if new_words:
        violations.append(f"shortened CV adds unevidenced words {new_words[:10]}")
    return violations


def compile_and_fit_cv(
    tex_path: Path,
    *,
    settings: Settings,
    client: Any,
    max_rounds: int = 3,
    evidence: list[ParsedEvidence] | None = None,
    job: Job | None = None,
) -> tuple[Path | None, str, int | None, float | None, dict[str, Any]]:
    """Compile a CV and nudge it toward a 1.85-1.98 page fit, recompiling each round.

    Overlong CVs are shortened; short CVs are only loosened *typographically*.
    There is deliberately no content-expansion path (TP-04). Every LLM rewrite
    must pass :func:`fit_rewrite_violations` before it touches the file, so a
    fit pass can never add ungrounded content; a rejected or non-compiling
    rewrite leaves the last good ``.tex`` in place and stops the loop.

    Operates in place on ``tex_path`` and returns
    ``(pdf_path, compile_status, page_count, page_fill, fit_report)``.
    """
    pdf_path, status = compile_pdf(tex_path)
    page_count, page_fill = measure_pdf_extent(pdf_path) if pdf_path else (None, None)
    report: dict[str, Any] = {"rounds": 0, "applied": [], "rejected": []}
    while (
        client is not None
        and pdf_path is not None
        and page_count is not None
        and report["rounds"] < max_rounds
    ):
        fit = classify_cv_fit("cv", page_count, page_fill)
        if fit in {"ok", "unknown"}:
            break
        current = tex_path.read_text(encoding="utf-8")
        kind = "shorten" if fit == "long" else "loosen"
        fixer = _shorten_cv_tex if kind == "shorten" else _loosen_cv_spacing
        revised = fixer(current, page_count, page_fill, settings=settings, client=client)
        report["rounds"] += 1
        if not revised or revised == current:
            break
        violations = fit_rewrite_violations(kind, current, revised, evidence=evidence, job=job)
        if violations:
            report["rejected"].append({"kind": kind, "reasons": violations})
            break
        tex_path.write_text(revised, encoding="utf-8")
        new_pdf, new_status = compile_pdf(tex_path)
        if new_pdf is None:
            # Never leave a broken rewrite on disk: restore the last good source.
            tex_path.write_text(current, encoding="utf-8")
            pdf_path, status = compile_pdf(tex_path)
            report["rejected"].append({"kind": kind, "reasons": [new_status[:200]]})
            break
        pdf_path, status = new_pdf, new_status
        page_count, page_fill = measure_pdf_extent(pdf_path)
        report["applied"].append(kind)
    return pdf_path, status, page_count, page_fill, report


def refresh_cv_draft_after_fit(
    draft_json: dict[str, Any] | None,
    final_tex: str,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Re-derive CV draft fields from the final (post-fit) LaTeX.

    The structured editor, change summary, and quality report must describe the
    document on disk — not the pre-fit render — so a fit rewrite is visible to
    the operator reviewing it.
    """
    merged = {
        key: value
        for key, value in (draft_json or {}).items()
        if key not in {"summary", "capabilities", "experience"}
    }
    merged = effective_cv_draft_json(merged, tex_content=final_tex) or merged
    tailoring = dict(merged.get("tailoring") or {})
    tailoring["change_summary"] = summarize_cv_changes(baseline, merged)
    merged["tailoring"] = tailoring
    merged["template_baseline"] = baseline
    return merged


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
# capitalisation to gate deterministically without an NER pass. The pattern and
# the generic-acronym exemptions live in ``cv_alignment`` so the CV path and the
# letter/answer path cannot drift apart.


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
                settings.material_model(),
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
        pdf_path, compile_status, page_count, page_fill, fit_report = compile_and_fit_cv(
            tex_path, settings=settings, client=client, evidence=evidence, job=job
        )
        status = "created_pdf" if pdf_path else compile_status
        tailoring_report["page_fit"] = fit_report
        draft_json = effective_cv_draft_json(tailoring.model_dump(), tex_content=rendered_tex) or {}
        draft_json["template_baseline"] = original
        draft_json["tailoring"] = tailoring_report
        final_tex = tex_path.read_text(encoding="utf-8")
        if final_tex != rendered_tex:
            # The fit loop rewrote the file: review data must describe what is on disk.
            draft_json = refresh_cv_draft_after_fit(draft_json, final_tex, original)
            tailoring_report = draft_json["tailoring"]
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
        _write_metadata(out_dir / "metadata.json", material, compile_status, settings.material_model())
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
                settings.material_model(),
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
        _write_metadata(out_dir / "metadata.json", material, compile_status, settings.material_model())
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
    pending_material: GeneratedMaterial | None = None,
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
                settings.material_model(),
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
        audit_detail = {
            "evidence_source": evidence_source,
            "evidence_count": len(evidence),
            "candidate_count": len(pool),
            "jd_match_score": quality_report["jd_match"]["score"],
            "ai_tells": quality_report["tells"],
        }
        if pending_material is not None:
            pending_material.title = draft.title
            pending_material.question = question
            pending_material.word_limit = word_limit
            pending_material.markdown_path = str(md_path)
            pending_material.evidence_ids = draft.evidence_ids
            pending_material.draft_json = draft_json
            pending_material.status = "created_markdown"
            session.add(pending_material)
            session.commit()
            session.refresh(pending_material)
            log_action(
                session,
                actor=ActorType.agent,
                action="generate_answer",
                entity_type="job",
                entity_id=job.id,
                detail={
                    "material_id": pending_material.id,
                    "status": pending_material.status,
                    "evidence_ids": draft.evidence_ids,
                    "version": pending_material.version,
                    **audit_detail,
                },
            )
            _write_metadata(
                out_dir.parent / "metadata.json",
                pending_material,
                "not_applicable",
                settings.material_model(),
            )
            return pending_material
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
            audit_detail=audit_detail,
        )
        _write_metadata(out_dir.parent / "metadata.json", material, "not_applicable", settings.material_model())
        return material


def create_pending_answer(
    session: Session,
    job: Job,
    *,
    question: str,
    word_limit: int | None = None,
) -> GeneratedMaterial:
    """Placeholder row so the API can return 202 before the LLM finishes."""
    title = (question.strip()[:80] or "Application question").rstrip()
    return _record_material(
        session,
        job,
        material_type="answer",
        title=title,
        evidence_ids=[],
        status="generating",
        question=question,
        word_limit=word_limit,
        draft_json={"body": "", "status": "generating"},
        audit_action="queue_answer",
    )


def mark_answer_failed(session: Session, material: GeneratedMaterial, error: str) -> GeneratedMaterial:
    material.status = "failed"
    material.draft_json = {
        **(material.draft_json or {}),
        "body": "",
        "error": error,
        "status": "failed",
    }
    session.add(material)
    session.commit()
    session.refresh(material)
    return material
