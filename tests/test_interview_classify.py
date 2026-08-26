"""Import-type hints and close-out learning extraction (Intact / iwoca replay)."""

from __future__ import annotations

from zengrowth.interviews.classify import (
    apply_import_type_suggestion,
    extract_closeout_learnings,
    suggest_internal_material_type,
)

_CULTURE = """## Goal
Compare cultures.

## Headline Comparison Table
| Company | Pace |
|---|---|
| Acme | Fast |

## Target Company Culture
Acme ships weekly and expects owners.

## Comparator Companies
Peer set of two lenders.

## Your Narrative Fit
Match the builder-operator story.

## Interview Framing
Lead with platform ROI.

## Decision Criteria If Offers Come
Prefer scope over title.

## Sources And Caveats
Public careers pages only.
"""

_SESSION = """## Session Goal
Finish a timed modelling exercise.

## Reviewer Or Interviewer Lens
They want working code, not slides.

## Runnable Prompt
You are a staff data scientist reviewing a take-home.

## Repo Or Workspace Structure
Keep notebooks out of the root.

## Timed Plan
Ninety minutes, ship a baseline first.

## Evaluation Criteria
Correctness, clarity, recovery.

## What Good Looks Like
A documented baseline plus one stretch.

## Recovery If Stuck
Simplify the feature set and rerun.
"""

_REFLECTION = """## Process Summary
Three rounds then a no.

## Feedback Received
They wanted deeper credit-risk ownership on the last round.

## What Went Well
Clear stories on platform build-out.

## Gaps Versus The Bar
- Credit-risk modelling depth was thinner than the bar for this seat.
- Live-coding recovery was slower than the exercise allowed.

## Skills And Knowledge To Deepen
- Practiced calibrated credit-risk modelling with gradient boosting on imbalanced labels.
- Refresh production feature-store patterns used in underwriting stacks.

## Evidence To Add To Library
- Write a Library note on the underwriting feature pipeline and monitoring.

## Posture For The Next Similar Role
- Lead with a 90-day credit-risk discovery plan instead of a generic AI CoE story.
"""

_SUMMARY = """## Organisation And Role
Lender, head of applied science.

## Timeline Of Rounds
Screen, technical, leadership.

## Conversations And Themes
Risk, platform, leadership.

## Materials Used
Briefing, packs, debriefs.

## Outcome And Feedback
Rejected after leadership.

## What Worked
Grounded stories.

## What Needs To Improve
- Tighten the recovery script for timed modelling exercises under pressure.

## Key Takeaways
- Keep the 90-day plan specific to the domain they actually hire for.

## Reusable Learnings
- Process: Confirm the live-coding environment the day before the round.
- Skill: Calibrated probability outputs matter more than raw AUC in credit.
"""


def test_suggest_culture_comparison_from_title():
    assert (
        suggest_internal_material_type("Acme vs Peer culture comparison", "")
        == "culture_comparison"
    )


def test_suggest_session_prep_from_claude_code_title():
    assert (
        suggest_internal_material_type("Claude Code practice brief — modelling", "")
        == "session_prep"
    )


def test_suggest_rejection_from_headings():
    assert suggest_internal_material_type("Close-out notes", _REFLECTION) == "rejection_reflection"


def test_suggest_none_for_generic_briefing():
    assert suggest_internal_material_type("Intact research pack", "# Intact\n\nBusiness overview...") is None


def test_title_rules_do_not_scan_body():
    body = (
        "# Intact briefing\n\nThe process includes a take-home after the hiring-manager round."
    )
    assert suggest_internal_material_type("Intact research pack", body) is None


def test_auto_reclassify_dump_types_only():
    applied, suggested = apply_import_type_suggestion(
        "company_briefing", "Culture comparison vs current employer", _CULTURE
    )
    assert suggested == "culture_comparison"
    assert applied == "culture_comparison"

    applied, _ = apply_import_type_suggestion(
        "tech_prep_pack", "Claude Code practice brief", _SESSION
    )
    assert applied == "session_prep"

    # Explicit interviewer pack is left alone even if the title mentions Claude Code.
    applied, suggested = apply_import_type_suggestion(
        "interviewer_pack", "Claude Code practice brief", _SESSION
    )
    assert applied == "interviewer_pack"
    assert suggested == "session_prep"


def test_extract_closeout_learnings_maps_sections():
    items = extract_closeout_learnings(_REFLECTION)
    categories = {text: cat for cat, text in items}
    assert not any("thinner than the bar" in text.lower() for text in categories)
    assert not any("library note" in text.lower() for text in categories)
    assert (
        categories[
            "Practiced calibrated credit-risk modelling with gradient boosting on imbalanced labels."
        ]
        == "process_skill"
    )
    assert (
        categories[
            "Lead with a 90-day credit-risk discovery plan instead of a generic AI CoE story."
        ]
        == "interview_learning"
    )
    skill_texts = [text for text, cat in categories.items() if cat == "process_skill"]
    learning_texts = [text for text, cat in categories.items() if cat == "interview_learning"]
    assert items[0][0] == "process_skill"
    assert skill_texts
    assert learning_texts

    summary = {text: cat for cat, text in extract_closeout_learnings(_SUMMARY)}
    assert not any("recovery script" in text.lower() for text in summary)
    assert not any("90-day plan specific" in text.lower() for text in summary)
    assert summary["Calibrated probability outputs matter more than raw AUC in credit."] == "process_skill"
    assert (
        summary["Confirm the live-coding environment the day before the round."]
        == "interview_learning"
    )


def test_extract_closeout_learnings_from_imported_playbook_heading():
    body = """## Part 3: The Three Gaps, Rebuilt Properly
- Credit-risk modelling depth was thinner than the bar for this seat.

## Part 5: The Durable Playbook For Next Senior Interview
- **End Head-of answers with I decided X because Y**, then the consequence I owned.
"""
    items = extract_closeout_learnings(body)
    assert len(items) == 1
    assert items[0][0] == "interview_learning"
    assert "I decided X because Y" in items[0][1]
