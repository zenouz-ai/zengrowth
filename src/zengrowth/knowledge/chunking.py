"""Chunk parsed knowledge documents into provenance-preserving text units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextChunk:
    index: int
    text: str
    section_path: str | None
    page_start: int | None
    line_start: int | None
    token_estimate: int


def chunk_text(text: str, *, max_chars: int = 2200, overlap_chars: int = 200) -> list[TextChunk]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_len = 0
    line_cursor = 1
    start_line = 1
    section: str | None = None

    def flush() -> None:
        nonlocal current, current_len, start_line
        if not current:
            return
        chunk_text_value = "\n\n".join(current).strip()
        chunks.append(
            TextChunk(
                index=len(chunks),
                text=chunk_text_value,
                section_path=section,
                page_start=_page_hint(chunk_text_value),
                line_start=start_line,
                token_estimate=max(1, len(chunk_text_value) // 4),
            )
        )
        tail = chunk_text_value[-overlap_chars:].strip()
        current = [tail] if tail and len(chunk_text_value) > overlap_chars else []
        current_len = len(tail) if current else 0
        start_line = line_cursor

    for paragraph in paragraphs:
        if _looks_like_heading(paragraph):
            section = paragraph[:120]
        if current and current_len + len(paragraph) + 2 > max_chars:
            flush()
        if not current:
            start_line = line_cursor
        current.append(paragraph)
        current_len += len(paragraph) + 2
        line_cursor += paragraph.count("\n") + 2
    flush()
    return chunks


def _looks_like_heading(value: str) -> bool:
    if "\n" in value or len(value) > 100:
        return False
    return value.startswith("#") or value.isupper() or value.endswith(":")


def _page_hint(value: str) -> int | None:
    first_line = value.splitlines()[0] if value.splitlines() else ""
    if first_line.startswith("[page ") and first_line.endswith("]"):
        try:
            return int(first_line.removeprefix("[page ").removesuffix("]"))
        except ValueError:
            return None
    return None
