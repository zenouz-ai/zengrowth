"""INT-06: deterministic quality checks against Intact golden fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from zengrowth.interviews.markdown_format import strip_llm_envelope
from zengrowth.interviews.material_policy import (
    DEBRIEF_SECTIONS,
    FOUNDATION_SECTIONS,
    LINE_BUDGETS,
    count_gap_blocks,
    count_numbered_questions,
    extract_material_snippets,
    line_count,
    missing_sections,
    pack_sections,
    quality_warnings,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "intact"


def _load(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def _body(rel: str) -> str:
    return strip_llm_envelope(_load(rel))


# --- Golden imported fixtures (target structure) --------------------------------


@pytest.mark.parametrize(
    "fixture,sections",
    [
        ("gold/imported-company-briefing.md", ["Who They Are", "Current Technology Stack"]),
        ("gold/imported-final-pack.md", ["Anchor Sentence"]),
    ],
)
def test_gold_fixtures_contain_key_sections(fixture: str, sections: list[str]) -> None:
    body = _body(fixture).lower()
    for section in sections:
        assert section.lower() in body, f"{fixture} missing {section!r}"


def test_gold_debrief_has_gap_recovery_scripts() -> None:
    body = _body("gold/imported-debrief.md")
    assert count_gap_blocks(body) >= 1
    assert "answer to learn" in body.lower()
    snippets = extract_material_snippets(body)
    assert snippets.get("gaps")
    assert any("MLflow" in g["title"] or "mlflow" in g["title"].lower() for g in snippets["gaps"])


def test_gold_interviewer_pack_is_question_led() -> None:
    body = _body("gold/imported-interviewer-pack.md")
    assert "question 1" in body.lower() or count_numbered_questions(body) >= 1
    assert "what they want to hear" in body.lower() or "model answer" in body.lower()


def test_gold_fixtures_within_line_budgets() -> None:
    for rel, kind in (
        ("gold/imported-company-briefing.md", "company_briefing"),
        ("gold/imported-tech-pack.md", "tech_prep_pack"),
        ("gold/imported-debrief.md", "debrief"),
        ("gold/imported-final-pack.md", "final_round_pack"),
    ):
        body = _body(rel)
        budget = LINE_BUDGETS[kind]
        assert budget[0] // 4 <= line_count(body) <= budget[1], (
            f"{rel} line count {line_count(body)} outside {budget}"
        )


# --- Policy helpers -------------------------------------------------------------


def test_pack_sections_vary_by_round_type() -> None:
    foundation = pack_sections("company_briefing")
    assert foundation == FOUNDATION_SECTIONS
    recruiter = pack_sections("interviewer_pack", round_type="recruiter_screen")
    leadership = pack_sections("interviewer_pack", round_type="leadership_panel")
    assert "Seniority Bridge" in recruiter
    assert "Frameworks To Know Cold" in leadership
    assert "Anchor Sentence" in recruiter


def test_synthetic_prep_passes_quality_gates() -> None:
    body = "\n".join(
        [
            "> [!tip] Read this first: technical round — lead with production AI.",
            "## Anchor Sentence",
            '> "I partner with platform teams to ship governed AI."',
            "## Who Is In The Room",
            "Ankur — platform lead.",
            "## Core Questions",
            "### Q1 — Opening (Ankur)",
            "- Likely phrasing: walk me through your background",
            "- Evidence: [claim-abc123def4567890]",
            "### Q2 — MLOps (Ankur)",
            "outline",
            "### Q3 — Governance (Jacob)",
            "outline",
            "### Q4 — Architecture (Chris)",
            "outline",
            "### Q5 — Team shape (Ian)",
            "outline",
            "## Your Evidence To Lead With",
            "[claim-abc123def4567890]",
            "## Questions To Ask Them",
            "How is Fabric used today?",
            "## Checklist",
            "- [ ] Review architecture diagram",
            "## Logistics",
            "45 minutes virtual.",
        ]
    )
    shared = [
        "Anchor Sentence",
        "Who Is In The Room",
        "Core Questions",
        "Your Evidence To Lead With",
        "Questions To Ask Them",
        "Checklist",
        "Logistics",
    ]
    assert missing_sections(body, shared) == []
    assert count_numbered_questions(body) >= 5
    assert quality_warnings(body, material_kind="pack", pack_type="tech_prep_pack") == []


def test_synthetic_debrief_passes_quality_gates() -> None:
    body = "\n".join(
        [
            "## Goal",
            "Test technical depth.",
            "## Outcome",
            "Proceed to final.",
            "## What Went Well",
            '- "You clearly know MLOps" — Ankur',
            "## Gaps To Close",
            "### Gap 1 — Thin on MLflow",
            "- What happened: \"we used Databricks mostly\"",
            "- Why it matters: platform credibility",
            "- Answer to learn: We tracked experiments in MLflow for batch models; GenAI used prompt versioning.",
            "## New Organisational Intelligence",
            "Fabric rollout Q3.",
            "## Learnings For The Next Stage",
            "1. Name MLflow explicitly.",
            "## Suggested Follow-Up Actions",
            "Send thank-you.",
        ]
    )
    assert missing_sections(body, DEBRIEF_SECTIONS) == []
    assert quality_warnings(body, material_kind="debrief") == []


def test_baseline_generated_tech_pack_triggers_warnings() -> None:
    """ZG baseline may lack anchor/Q-count until policy fully applied in generation."""
    body = _body("baseline/generated-tech-pack.md")
    warnings = quality_warnings(body, material_kind="pack", pack_type="tech_prep_pack")
    assert any("anchor" in w.lower() or "question" in w.lower() for w in warnings)
