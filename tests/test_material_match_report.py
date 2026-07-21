"""Deterministic material↔JD match & quality report (TA-13 / TA-03 / TA-05)."""

from datetime import date

from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials.match_report import (
    cv_plain_text,
    find_ai_tells,
    impact_report,
    jd_match_report,
    jd_salient_terms,
    material_quality_report,
)
from zengrowth.models import Job, JobSource


def _job(**overrides) -> Job:
    fields = dict(
        company="Acme",
        title="Head of Machine Learning",
        location="London",
        posting_date=date(2026, 6, 1),
        description="Lead the machine learning platform team.",
        source=JobSource.manual,
        dedup_hash=dedup_hash("Acme", "Head of Machine Learning", date(2026, 6, 1)),
        job_summary={
            "requirements": [
                "Production experience with PyTorch and Kubernetes",
                "Design evaluation pipelines for LLM systems",
                "Stakeholder management across engineering and product",
            ],
            "responsibilities": ["Own the roadmap for the recommendation platform"],
        },
    )
    fields.update(overrides)
    return Job(**fields)


def test_jd_salient_terms_prefers_entities_and_skips_boilerplate():
    terms = jd_salient_terms(_job())
    assert "pytorch" in terms
    assert "kubernetes" in terms
    # boilerplate like "experience" / "requirements" never counts as signal
    assert "experience" not in terms
    assert "requirements" not in terms


def test_jd_salient_terms_deterministic():
    job = _job()
    assert jd_salient_terms(job) == jd_salient_terms(job)


def test_jd_match_report_scores_coverage_and_lists_missing():
    job = _job()
    text = (
        "I built PyTorch training pipelines on Kubernetes and led evaluation "
        "of LLM systems across the platform."
    )
    report = jd_match_report(text, job)
    assert report["term_count"] > 0
    assert "pytorch" in report["matched"]
    assert "kubernetes" in report["matched"]
    assert 0 < report["score"] <= 100
    assert set(report["matched"]) | set(report["missing"]) == set(
        jd_salient_terms(job)
    )


def test_jd_match_report_plural_folding():
    job = _job(
        job_summary={"requirements": ["Build data pipelines"]},
        title="Engineer",
    )
    report = jd_match_report("I built a streaming pipeline.", job)
    # JD says "pipelines" (displayed as written); the singular in prose matches it
    assert "pipelines" in report["matched"]


def test_jd_match_report_empty_summary_falls_back_to_description():
    job = _job(job_summary=None, description="Deep expertise in Terraform required.")
    report = jd_match_report("Terraform modules everywhere.", job)
    assert "terraform" in report["matched"]


def test_jd_salient_terms_keeps_versioned_tech():
    """Digit-bearing tools (gpt-4, llama2) must remain matchable signals."""
    job = _job(
        job_summary={"requirements": ["Hands-on with GPT-4 and Llama2 serving"]},
        description="",
        title="ML Engineer",
    )
    terms = jd_salient_terms(job)
    assert "gpt-4" in terms
    assert "llama2" in terms


def test_jd_focus_merges_description_when_summary_omits_tools():
    """Thin summaries must not hide tools that only appear in the raw JD."""
    job = _job(
        job_summary={"requirements": ["Stakeholder management across product"]},
        description="Production Kubernetes and Terraform ownership required.",
    )
    terms = jd_salient_terms(job)
    assert "kubernetes" in terms
    assert "terraform" in terms
    report = jd_match_report("I run Kubernetes and Terraform in production.", job)
    assert "kubernetes" in report["matched"]
    assert "terraform" in report["matched"]


def test_impact_report_counts_quantified_lines():
    text = "Cut latency by 40%.\nLed the platform team.\nSaved £2.1M annually."
    report = impact_report(text)
    assert report["content_lines"] == 3
    assert report["quantified_lines"] == 2


def test_impact_report_empty_text():
    assert impact_report("") == {"quantified_lines": 0, "content_lines": 0}


def test_find_ai_tells_flags_cliches_only():
    text = "I have a proven track record and I am writing to apply for this role."
    tells = find_ai_tells(text)
    assert "proven track record" in tells
    assert "i am writing to apply" in tells
    assert find_ai_tells("I reduced churn 12% by rebuilding the scoring model.") == []


def test_material_quality_report_shape():
    report = material_quality_report("PyTorch work cut costs 30%.", _job())
    assert set(report) == {"jd_match", "impact", "tells"}
    assert report["tells"] == []
    assert report["impact"]["quantified_lines"] == 1


def test_cv_plain_text_joins_editable_spans_and_strips_latex():
    draft = {
        "summary": "Delivered £2.05M value.",
        "capabilities": [r"\textbf{ML:} PyTorch, Kubernetes"],
        "experience": {"0": [r"Cut costs by \pounds1M"]},
        "template_baseline": {"summary": "ignored"},
    }
    text = cv_plain_text(draft)
    assert "Delivered £2.05M value." in text
    assert "PyTorch, Kubernetes" in text
    assert "\\textbf" not in text
    assert "ignored" not in text


def test_cv_plain_text_handles_empty_draft():
    assert cv_plain_text(None) == ""
    assert cv_plain_text({}) == ""
