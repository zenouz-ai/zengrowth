"""Tests for Obsidian-style internal markdown formatting."""

from __future__ import annotations

from pathlib import Path

from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.interviews.markdown_format import (
    build_frontmatter,
    strip_llm_envelope,
    wrap_obsidian_pack,
)
from zengrowth.models import Job


def _job() -> Job:
    return Job(
        company="Intact",
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash("Intact", "Director of AI", None),
    )


def test_build_frontmatter_matches_obsidian_shape():
    fm = build_frontmatter("Company briefing — Intact", _job(), material_type="company_briefing")
    assert fm.startswith("---\n")
    assert 'title: "Company briefing — Intact"' in fm
    assert "type: reference" in fm
    assert "tags:" in fm
    assert "updated:" in fm


def test_wrap_obsidian_pack_envelope():
    body = (
        "> [!tip] Key takeaway for this round.\n\n"
        "## Who They Are\nGlobal insurer.\n\n"
        "## Your Evidence to Lead With\nLed a team [claim-abc123def4567890]."
    )
    doc = wrap_obsidian_pack(
        body,
        title="Company briefing — Intact",
        job=_job(),
        pack_type="company_briefing",
        web_search_used=True,
        citations=[{"url": "https://example.com", "title": "Example"}],
    )
    assert doc.startswith("---\n")
    assert "# Company briefing — Intact\n" in doc
    assert "> [!warning]" in doc
    assert "unverified web research" in doc
    assert "> [!tip]" in doc
    assert "## Who They Are" in doc
    assert "## Sources" in doc
    assert "https://example.com" in doc


def test_strip_llm_envelope_removes_duplicate_frontmatter():
    raw = "---\ntitle: x\n---\n\n# Title\n\n## Section\nBody."
    assert "## Section" in strip_llm_envelope(raw)
    assert "---" not in strip_llm_envelope(raw).split("\n")[0]


def test_fixture_snippet_shape():
    snippet = Path(__file__).parent / "fixtures" / "intact-research-pack-snippet.md"
    text = snippet.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "# Intact Research" in text
    assert "> [!tip]" in text
    assert "## Who They Are" in text
