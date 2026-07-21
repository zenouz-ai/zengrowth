"""Load evidence claims from a hand-authored Markdown file into ``ParsedEvidence``.

This is the legacy fallback evidence source (``source_of_truth.md``), used when no
verified ``EvidenceClaim`` rows exist in the database.

Format (one item per `## evidence_id` heading):

    ## evi-led-001
    - category: leadership
    - source_role: Head of DS, Example Co
    - verified: true
    - tags: leadership, hiring
    - claim: |
        Multi-line claim text...

The parser is intentionally simple — strict Markdown, easy to author by hand
in Obsidian. A richer schema (YAML frontmatter, references between items) is
# TODO(phase-2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING_RE = re.compile(r"^##\s+(\S+)\s*$")
_FIELD_RE = re.compile(r"^-\s*([\w_]+)\s*:\s*(.*)$")


@dataclass
class ParsedEvidence:
    id: str
    category: str
    claim_text: str
    source_role: str | None = None
    verified: bool = False
    tags: list[str] | None = None


def _coerce(field: str, raw: str) -> object:
    raw = raw.strip()
    if field == "verified":
        return raw.lower() in ("true", "yes", "1")
    if field == "tags":
        return [t.strip() for t in raw.split(",") if t.strip()]
    return raw


def parse_evidence_markdown(text: str) -> list[ParsedEvidence]:
    items: list[ParsedEvidence] = []
    current: dict | None = None
    claim_buffer: list[str] | None = None

    def _flush() -> None:
        nonlocal current, claim_buffer
        if current is None:
            return
        if claim_buffer is not None:
            current["claim_text"] = "\n".join(claim_buffer).strip()
            claim_buffer = None
        if "category" in current and "claim_text" in current:
            items.append(
                ParsedEvidence(
                    id=current["id"],
                    category=current["category"],
                    claim_text=current["claim_text"],
                    source_role=current.get("source_role"),
                    verified=bool(current.get("verified", False)),
                    tags=current.get("tags"),
                )
            )
        current = None

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            _flush()
            current = {"id": heading.group(1)}
            continue
        if current is None:
            continue
        if claim_buffer is not None:
            if line.startswith("    ") or line.startswith("\t"):
                claim_buffer.append(line.lstrip())
                continue
            current["claim_text"] = "\n".join(claim_buffer).strip()
            claim_buffer = None
        field = _FIELD_RE.match(line)
        if not field:
            continue
        name = field.group(1).lower()
        value = field.group(2)
        if name == "claim" and value.strip() in ("", "|"):
            claim_buffer = []
            continue
        current[name if name != "claim" else "claim_text"] = _coerce(name, value)
    _flush()
    return items


def load_evidence_files(*paths: str | Path) -> list[ParsedEvidence]:
    items: list[ParsedEvidence] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        items.extend(parse_evidence_markdown(path.read_text(encoding="utf-8")))
    return items
