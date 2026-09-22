"""Tests for CV template vs tailored diff."""

from zengrowth.materials.cv_diff import normalize_cv_line, summarize_cv_changes


def test_normalize_cv_line_strips_latex_noise():
    a = r"\textbf{Python} $|$ FastAPI"
    b = "Python | FastAPI"
    assert normalize_cv_line(a) == normalize_cv_line(b)


def test_summarize_cv_changes_counts_sections():
    original = {
        "summary": "Lead AI delivery.",
        "capabilities": ["Cap A", "Cap B"],
        "experience": [["Bullet 1", "Bullet 2"], ["Bullet 3"]],
    }
    tailored = {
        "summary": "Lead AI delivery for regulated clients.",
        "capabilities": ["Cap A", "Cap B tailored"],
        "experience": {"0": ["Bullet 1", "Bullet 2 new"], "1": ["Bullet 3"]},
    }
    report = summarize_cv_changes(original, tailored)
    assert report["lines_total"] == 6
    assert report["lines_changed"] == 3
    assert report["change_rate"] == 0.5
    assert report["summary_changed"] is True
    assert report["capabilities_changed"] == 1
    assert report["bullets_changed"] == 1
    assert len(report["changes"]) == 3


def test_change_summary_reports_removed_and_added_lines():
    """zip() hid trailing deletions, so a removed bullet looked like "no change"."""
    original = {
        "summary": "Original summary.",
        "capabilities": [r"\textbf{AI:} Python", r"\textbf{Data:} SQL"],
        "experience": [["Built services.", "Led the team."]],
    }
    tailored = {
        "summary": "Original summary.",
        "capabilities": [r"\textbf{AI:} Python"],
        "experience": {"0": ["Built services."]},
    }
    report = summarize_cv_changes(original, tailored)
    kinds = [c.get("kind") for c in report["changes"]]
    assert kinds.count("removed") == 2
    assert report["lines_changed"] == 2
    assert report["lines_total"] == 5
