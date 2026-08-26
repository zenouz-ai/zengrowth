from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import select

from zengrowth.config import Settings
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials import generator
from zengrowth.materials.generator import (
    CvTailoring,
    generate_answer,
    generate_cover_letter,
    generate_cv,
    render_cv,
)
from zengrowth.materials.latex import compile_pdf, escape_latex, latex_to_plain
from zengrowth.models import Job, JobSource


class FakeMaterialClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def generate(self, system: str, user: str, model: str, **kwargs: Any) -> dict[str, Any]:
        return self.response


def _job() -> Job:
    return Job(
        company="Acme & Co",
        title="Director_AI 100%",
        location="London",
        posting_date=date(2026, 5, 20),
        description="Lead AI strategy.",
        source=JobSource.manual,
        dedup_hash=dedup_hash("Acme & Co", "Director_AI 100%", date(2026, 5, 20)),
        job_summary={"role_overview": "Lead AI strategy."},
    )


def test_escape_latex_handles_common_special_chars():
    assert escape_latex("Acme & Co_100% £") == r"Acme \& Co\_100\% \pounds{}"


def test_latex_to_plain_converts_pounds_and_unwraps_textbf():
    raw = r"\textbf{PhD AI leader} delivering \pounds2.05M at Legal \& General."
    plain = latex_to_plain(raw)
    assert "£2.05M" in plain
    assert "PhD AI leader" in plain
    assert "&" in plain
    assert "\\" not in plain
    assert "{" not in plain


def test_render_cv_plain_summary_escapes_pounds_not_backslash():
    from zengrowth.materials.generator import _read_cv_template

    tailoring = CvTailoring(
        title="Role CV",
        summary="Delivered £2.05M commercial value.",
        capabilities=[],
        experience={},
        evidence_ids=["evi-1"],
    )
    tex = render_cv(tailoring, template_text=_read_cv_template())
    assert r"\pounds{}" in tex or r"\pounds" in tex
    assert r"\textbackslash{}" not in tex


def test_effective_cv_draft_json_backfill_plainifies_latex_summary():
    from zengrowth.materials.generator import effective_cv_draft_json

    tex = (
        r"\section*{Professional Summary}"
        "\nDelivering \\pounds2.05M value.\n"
        r"\section*{Core Capabilities}"
        "\n\\textbf{AI:} models\n"
        r"\section*{Education}"
        "\n"
    )
    enriched = effective_cv_draft_json({"summary": None}, tex_content=tex)
    assert enriched is not None
    assert enriched.get("summary")
    assert "£2.05M" in enriched["summary"]
    assert "\\pounds" not in enriched["summary"]


def test_compile_pdf_reports_created_when_compiler_outputs_pdf(tmp_path, monkeypatch):
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}OK\end{document}", encoding="utf-8")

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, cwd, check, capture_output, text, timeout):
        assert cmd[:2] == ["/usr/bin/latexmk", "-pdf"]
        assert cwd == tmp_path
        tex_path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return FakeProc()

    monkeypatch.setattr("zengrowth.materials.latex.shutil.which", lambda name: "/usr/bin/latexmk" if name == "latexmk" else None)
    monkeypatch.setattr("zengrowth.materials.latex.subprocess.run", fake_run)

    pdf_path, status = compile_pdf(tex_path)

    assert pdf_path == tex_path.with_suffix(".pdf")
    assert status == "pdf_created"


def test_generate_cv_creates_tex_and_material_metadata(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))
    client = FakeMaterialClient(
        {
            "title": "Tailored CV",
            "summary": "Strong match for AI strategy.",
            "bullets": ["Led enterprise AI delivery."],
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_cv(
        session,
        job,
        client=client,
        settings=Settings(anthropic_api_key="test", scoring_model="claude-test"),
    )

    assert material.material_type == "cv"
    assert material.tex_path is not None
    assert Path(material.tex_path).exists()
    assert Path(material.tex_path).name == "Jordan_Avery_CV_Acme_Co_v1.tex"
    assert material.pdf_path is None
    assert material.status == "pdf_unavailable_no_latex_compiler"
    assert Path(material.tex_path).with_name("metadata.json").exists()


def test_generate_cover_letter_creates_tex(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))
    client = FakeMaterialClient(
        {
            "title": "Cover letter",
            "body": "Dear hiring team,\n\nI am interested.",
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_cover_letter(
        session,
        job,
        client=client,
        settings=Settings(anthropic_api_key="test"),
    )

    assert material.material_type == "cover_letter"
    assert material.tex_path is not None
    assert Path(material.tex_path).exists()
    assert Path(material.tex_path).name == "Jordan_Avery_CL_Acme_Co_v1.tex"
    # TA-13: every generated material carries the deterministic quality report
    report = (material.draft_json or {}).get("quality_report")
    assert report is not None
    assert set(report) == {"jd_match", "impact", "tells"}


def test_generate_answer_saves_markdown_with_question(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Why us",
            "body": "Your role matches my AI strategy experience.",
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_answer(
        session,
        job,
        question="Why did you choose us?",
        word_limit=200,
        client=client,
        settings=Settings(anthropic_api_key="test"),
    )

    assert material.material_type == "answer"
    assert material.word_limit == 200
    assert material.markdown_path is not None
    assert "Why did you choose us?" in Path(material.markdown_path).read_text(encoding="utf-8")


def test_generate_answer_accepts_null_bullets(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Salary expectation",
            "bullets": None,
            "body": "My base salary expectation is £150,000.",
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_answer(
        session,
        job,
        question="Base Salary Expectation",
        client=client,
        settings=Settings(anthropic_api_key="test"),
    )

    assert material.material_type == "answer"
    assert "£150,000" in Path(material.markdown_path).read_text(encoding="utf-8")


def test_generate_answer_allows_empty_evidence_for_compensation(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Variable pay expectation",
            "body": "My variable pay expectation is £30,000–£40,000.",
            "evidence_ids": [],
        }
    )

    material = generate_answer(
        session,
        job,
        question="Variable Pay Expectation",
        client=client,
        settings=Settings(anthropic_api_key="test"),
    )

    assert material.material_type == "answer"
    assert material.evidence_ids == []
    assert "£30,000" in Path(material.markdown_path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "question, is_comp",
    [
        ("Base Salary Expectation", True),
        ("Variable Pay Expectation", True),
        ("What total package are you looking for?", True),
        # TP-03: substring matching used to misclassify these as compensation
        # ("base" in database, "pay" in payment), disabling the evidence gate.
        ("Describe your experience building a database platform.", False),
        ("How did you lead a payment rollout?", False),
    ],
)
def test_compensation_classifier_is_word_bounded(question, is_comp):
    assert generator._is_compensation_question(question) is is_comp


def test_non_comp_question_requires_evidence(session, tmp_path, monkeypatch):
    """A question that merely contains 'base' must still be evidence-grounded."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Database experience",
            "body": "Ungrounded prose.",
            "evidence_ids": [],
        }
    )
    with pytest.raises(ValueError, match="no valid evidence_ids"):
        generate_answer(
            session,
            job,
            question="Describe your database platform experience.",
            client=client,
            settings=Settings(anthropic_api_key="test"),
        )


def test_generate_cv_rejects_ungrounded_response(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Ungrounded CV",
            "summary": "Looks good.",
            "bullets": ["Unsupported claim."],
            "evidence_ids": [],
        }
    )

    with pytest.raises(ValueError, match="no valid evidence_ids"):
        generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))


def test_cover_letter_rejects_ungrounded_figure(session, tmp_path, monkeypatch):
    """TP-01: a cited evidence_id does not license an invented number in the body."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Cover letter",
            "body": "I personally delivered 999 enterprise launches last year.",
            "evidence_ids": ["evi-profile-001"],
        }
    )
    with pytest.raises(ValueError, match="ungrounded figures"):
        generate_cover_letter(session, job, client=client, settings=Settings(anthropic_api_key="test"))


def test_answer_rejects_ungrounded_figure(session, tmp_path, monkeypatch):
    """TP-01: non-compensation answers are held to the same numeric grounding bar."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Why us",
            "body": "I have led 777 AI teams to production.",
            "evidence_ids": ["evi-profile-001"],
        }
    )
    with pytest.raises(ValueError, match="ungrounded figures"):
        generate_answer(
            session,
            job,
            question="Why did you choose us?",
            client=client,
            settings=Settings(anthropic_api_key="test"),
        )


def test_generate_cv_drops_ungrounded_summary_to_template(session, tmp_path, monkeypatch):
    """TP-01: a summary asserting an invented figure is dropped (template summary kept)."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))
    client = FakeMaterialClient(
        {
            "title": "Tailored CV",
            "summary": "An AI leader with 888 years of delivery.",
            "evidence_ids": ["evi-profile-001"],
        }
    )
    material = generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))
    # Ungrounded summary sentence is dropped; composed summary may replace it from claims.
    assert material.draft_json["summary"] is None or "888" not in (material.draft_json["summary"] or "")
    assert "888" not in Path(material.tex_path).read_text(encoding="utf-8")


def test_group_grounded_blocks_unevidenced_technology_swap():
    """TP-05: rewording that introduces an unevidenced tool/skill is rejected."""
    original = [r"\textbf{Languages:} Python and SQL"]
    evidence_words = generator._content_words("Python SQL data pipelines leadership")
    reorder = [r"\textbf{Languages:} SQL and Python"]
    swap = [r"\textbf{Languages:} Rust and SQL"]
    assert generator._group_grounded(reorder, original, evidence_words) is True
    assert generator._group_grounded(swap, original, evidence_words) is False


def test_group_ok_blocks_new_unescaped_latex_special():
    """TP-14: a reworded line introducing a bare & (etc.) is rejected to protect the compile."""
    original = [r"\textbf{Focus:} research and delivery"]
    new_bare_special = [r"\textbf{Focus:} research & delivery"]
    escaped = [r"\textbf{Focus:} research \& delivery"]
    assert generator._group_ok(new_bare_special, original) is False
    assert generator._group_ok(escaped, original) is True


def test_cover_letter_rejects_ungrounded_entity(session, tmp_path, monkeypatch):
    """TP-01b: an invented employer/tool (named entity) in the body is rejected."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    client = FakeMaterialClient(
        {
            "title": "Cover letter",
            "body": "I previously led applied research at ZephyrLabs.",
            "evidence_ids": ["evi-profile-001"],
        }
    )
    with pytest.raises(ValueError, match="ungrounded references"):
        generate_cover_letter(session, job, client=client, settings=Settings(anthropic_api_key="test"))


def _evidence_for_rewrite():
    from zengrowth.materials.evidence import ParsedEvidence

    return [
        ParsedEvidence(
            id="e1",
            category="delivery",
            claim_text="Led an AI platform team and delivered models to production.",
            source_role="Data Science Manager",
            verified=True,
            tags=[],
        )
    ]


def test_assert_rewrite_grounded_blocks_new_figure():
    """TP-01b: an LLM rewrite that introduces an unevidenced number is rejected."""
    job = _job()
    evidence = _evidence_for_rewrite()
    original = "Led an AI platform team to production."
    revised = "Led an AI platform team that grew revenue by 4242 percent."
    with pytest.raises(ValueError, match="ungrounded figures"):
        generator.assert_rewrite_grounded(original, revised, evidence, job)


def test_assert_rewrite_grounded_blocks_new_entity():
    """TP-01b: an LLM rewrite that introduces an unevidenced named entity is rejected."""
    job = _job()
    evidence = _evidence_for_rewrite()
    original = "Led an AI platform team to production."
    revised = "Led an AI platform team to production, previously at ZephyrLabs."
    with pytest.raises(ValueError, match="ungrounded references"):
        generator.assert_rewrite_grounded(original, revised, evidence, job)


def test_assert_rewrite_grounded_allows_rephrase_of_existing_content():
    """TP-01b: rephrasing without new figures/entities passes; only additions are gated."""
    job = _job()
    evidence = _evidence_for_rewrite()
    original = "Led an AI platform team to production."
    revised = "Led the AI platform team, taking models to production."
    generator.assert_rewrite_grounded(original, revised, evidence, job)  # no raise


def test_generate_cv_fails_loud_on_empty_evidence_bank(session, tmp_path, monkeypatch):
    """TP-06: an empty bank is a clear, pre-LLM error, not a confusing downstream failure."""
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "_load_evidence_with_source", lambda s, limit=None: ([], "empty"))

    class _ShouldNotCall(FakeMaterialClient):
        def generate(self, *a, **k):
            raise AssertionError("LLM must not be called when the evidence bank is empty")

    with pytest.raises(ValueError, match="evidence bank is empty"):
        generate_cv(session, job, client=_ShouldNotCall({}), settings=Settings(anthropic_api_key="test"))


def test_generate_cv_records_evidence_provenance(session, tmp_path, monkeypatch):
    """TP-06: the material audit detail records which evidence source grounded it."""
    from zengrowth.models import AuditLog

    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))
    monkeypatch.setattr(
        generator,
        "_load_evidence_with_source",
        lambda s, limit=None: (
            [
                generator.ParsedEvidence(
                    id="evi-1", category="impact", claim_text="Shipped models.", verified=True, tags=[]
                )
            ],
            "markdown",
        ),
    )
    client = FakeMaterialClient(
        {"title": "Tailored CV", "summary": "Strong AI leader.", "evidence_ids": ["evi-1"]}
    )
    generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))
    row = session.exec(
        select(AuditLog).where(AuditLog.action == "generate_cv")
    ).first()
    assert row.detail["evidence_source"] == "markdown"
    assert row.detail["evidence_count"] == 1


def _section_titles(text: str) -> list[str]:
    import re

    return re.findall(r"\\section\*\{[^}]*\}", text)


def test_generate_cv_preserves_template_structure(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))

    original = generator._parse_cv_template(generator._read_cv_template())
    caps = list(reversed(original["capabilities"]))
    exp = {str(i): list(reversed(items)) for i, items in enumerate(original["experience"])}
    client = FakeMaterialClient(
        {
            "title": "Tailored CV",
            "summary": "Targeted summary for the role.",
            "capabilities": caps,
            "experience": exp,
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))
    tex = Path(material.tex_path).read_text(encoding="utf-8")

    # No new/removed sections; identical section titles in identical order.
    assert "Target Role Alignment" not in tex
    assert _section_titles(tex) == _section_titles(generator._read_cv_template())
    # Summary rewritten.
    assert "Targeted summary for the role." in tex
    # Capabilities: same count and set; Phase 3+4 merges per index (reorder alone is not applied).
    parsed = generator._parse_cv_template(tex)
    assert len(parsed["capabilities"]) == len(original["capabilities"])
    assert set(parsed["capabilities"]) == set(original["capabilities"])
    assert [len(items) for items in parsed["experience"]] == [
        len(items) for items in original["experience"]
    ]


def test_generate_cv_fabricated_metrics_fall_back_to_template(session, tmp_path, monkeypatch):
    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))

    original = generator._parse_cv_template(generator._read_cv_template())
    bad_caps = list(original["capabilities"])
    bad_caps[0] = bad_caps[0] + " delivering 777 extra wins"
    client = FakeMaterialClient(
        {
            "title": "Tailored CV",
            "summary": "Targeted summary.",
            "capabilities": bad_caps,
            "evidence_ids": ["evi-profile-001"],
        }
    )

    material = generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))
    tex = Path(material.tex_path).read_text(encoding="utf-8")

    # Fabricated metric is rejected; capabilities revert to the template verbatim.
    assert "777" not in tex
    parsed = generator._parse_cv_template(tex)
    assert parsed["capabilities"] == original["capabilities"]
    # Summary still tailored.
    assert "Targeted summary." in tex


def test_parse_cv_template_handles_alternate_structure():
    # A template whose capabilities use \\[1pt] (not 2pt), whose experience is
    # followed by "Selected Technical Projects" (plural), and that carries extra
    # trailing sections must still parse into per-line caps and per-role bullets.
    tmpl = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section*{Professional Summary}\nA grounded summary.\n"
        "\\section*{Core Capabilities}\n"
        "\\textbf{One:} alpha $|$ beta\\\\[1pt]\n"
        "\\textbf{Two:} gamma $|$ delta\\\\[1pt]\n"
        "\\textbf{Three:} epsilon\\\\[1pt]\n"
        "\\section*{Professional Experience}\n"
        "\\textbf{Lead, \\href{https://x}{X}} \\hfill 2025\\\\\n"
        "\\begin{itemize}\n\\item First bullet\n\\item Second bullet\n\\end{itemize}\n"
        "\\textbf{Engineer, \\href{https://y}{Y}} \\hfill 2023\\\\\n"
        "\\begin{itemize}\n\\item Only bullet\n\\end{itemize}\n"
        "\\section*{Selected Technical Projects}\nProject text.\n"
        "\\section*{Education}\nDegree.\n"
        "\\end{document}\n"
    )
    parsed = generator._parse_cv_template(tmpl)
    assert parsed["summary"] == "A grounded summary."
    assert len(parsed["capabilities"]) == 3
    assert parsed["capabilities"][0].startswith("\\textbf{One:}")
    assert [len(items) for items in parsed["experience"]] == [2, 1]

    # Round-trip: a structure-preserving tailoring keeps the \\[1pt] separator.
    tailoring = CvTailoring(
        title="t",
        summary="New summary.",
        capabilities=list(reversed(parsed["capabilities"])),
        evidence_ids=["e1"],
    )
    rendered = render_cv(tailoring, template_text=tmpl)
    assert "\\\\[1pt]" in rendered
    assert "\\\\[2pt]" not in rendered
    reparsed = generator._parse_cv_template(rendered)
    assert len(reparsed["capabilities"]) == 3
    assert reparsed["summary"] == "New summary."


def test_compile_and_fit_cv_shortens_when_too_long(tmp_path, monkeypatch):
    from zengrowth.materials import generator as gen

    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}LONG\end{document}", encoding="utf-8")

    pages = {"n": 3}

    def fake_compile(path):
        path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return path.with_suffix(".pdf"), "pdf_created"

    def fake_measure(pdf):
        return pages["n"], 0.9

    class FitClient:
        calls = 0

        def complete_text(self, system, user, model, max_tokens=8000, **kwargs):
            FitClient.calls += 1
            pages["n"] = 2  # shortened enough on first attempt
            return r"\documentclass{article}\begin{document}SHORT\end{document}"

    monkeypatch.setattr(gen, "compile_pdf", fake_compile)
    monkeypatch.setattr(gen, "measure_pdf_extent", fake_measure)

    pdf_path, status, page_count, page_fill = gen.compile_and_fit_cv(
        tex_path, settings=Settings(anthropic_api_key="test"), client=FitClient()
    )

    assert page_count == 2
    assert FitClient.calls == 1
    assert "SHORT" in tex_path.read_text(encoding="utf-8")


def test_compile_and_fit_cv_loosens_short_cv_without_inventing_content(tmp_path, monkeypatch):
    """TP-04: a short CV is fixed by typography only — never content expansion."""
    from zengrowth.materials import generator as gen

    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(r"\documentclass{article}\begin{document}TINY\end{document}", encoding="utf-8")

    # Starts as a too-short two-page CV (fill below the 0.85 target).
    state = {"fill": 0.6}

    def fake_compile(path):
        path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return path.with_suffix(".pdf"), "pdf_created"

    def fake_measure(pdf):
        return 2, state["fill"]

    class FitClient:
        calls = 0

        def complete_text(self, system, user, model, max_tokens=8000, **kwargs):
            FitClient.calls += 1
            # The short-CV path must drive a spacing/typography edit, not an
            # evidence-grounded content expansion.
            assert kwargs.get("operation_name") == "cv_fit_loosen"
            assert "evidence bank" not in user.lower()
            assert "spacing" in user.lower() or "typography" in system.lower()
            state["fill"] = 0.92  # loosened into the target window
            return r"\documentclass{article}\begin{document}LOOSENED\end{document}"

    monkeypatch.setattr(gen, "compile_pdf", fake_compile)
    monkeypatch.setattr(gen, "measure_pdf_extent", fake_measure)

    pdf_path, status, page_count, page_fill = gen.compile_and_fit_cv(
        tex_path,
        settings=Settings(anthropic_api_key="test"),
        client=FitClient(),
    )

    assert page_count == 2
    assert page_fill == 0.92
    assert FitClient.calls == 1
    assert "LOOSENED" in tex_path.read_text(encoding="utf-8")


def test_measure_pdf_extent_counts_pages(tmp_path):
    from pypdf import PdfWriter

    from zengrowth.materials.latex import measure_pdf_extent

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    pdf_path = tmp_path / "doc.pdf"
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    pages, fill = measure_pdf_extent(pdf_path)
    assert pages == 2
    assert fill is None  # blank pages carry no text positions


def test_page_fit_status_rules():
    from zengrowth.api.schemas import page_fit_status

    assert page_fit_status("cv", 2, 0.9) == "ok"
    assert page_fit_status("cv", 2, 0.8) == "short"
    assert page_fit_status("cv", 2, 0.5) == "short"
    assert page_fit_status("cv", 2, 0.99) == "long"
    assert page_fit_status("cv", 1, 0.95) == "short"
    assert page_fit_status("cv", 3, 0.9) == "long"
    assert page_fit_status("cv", 2, None) == "unknown"
    assert page_fit_status("cv", None, None) == "unknown"
    assert page_fit_status("cover_letter", 1, 0.9) == "unknown"


def test_cv_grounding_includes_job_summary_vocabulary():
    """CV gates widen to job posting vocabulary; cover-letter gates stay bank-only."""
    from zengrowth.materials.evidence import ParsedEvidence

    settings = Settings(anthropic_api_key="test")
    job = _job()
    job.job_summary = {
        "company_domain": "pharma and healthcare drug development",
        "requirements": ["LangGraph multi-agent", "AutoGen", "CrewAI"],
    }
    evidence = [
        ParsedEvidence(
            id="evi-1",
            category="delivery",
            claim_text="Led AI platform delivery.",
            verified=True,
            tags=[],
        )
    ]
    words = generator._cv_grounding_words(evidence, job, settings)
    assert "pharma" in words
    assert "healthcare" in words
    ents = generator._cv_grounding_entity_tokens(evidence, job, settings)
    assert "autogen" in ents
    assert "crewai" in ents
    assert "pharma" not in generator._grounding_entity_tokens(evidence, job)


def test_cv_priority_profile_expands_synonyms_and_company():
    from zengrowth.materials.cv_alignment import cv_grounding_profile, expand_grounding_words

    settings = Settings(anthropic_api_key="test", cv_priority_fit_threshold=85)
    job = _job()
    job.fit_score = 90.0
    job.company = "Novartis"
    assert cv_grounding_profile(job, settings) == "priority"
    words = expand_grounding_words({"pharma", "delivery"}, "priority")
    assert "pharmaceutical" in words


def test_cv_capabilities_accept_job_context_words():
    from zengrowth.materials.evidence import ParsedEvidence

    settings = Settings(anthropic_api_key="test")
    job = _job()
    job.job_summary = {"company_domain": "pharma drug development and healthcare"}
    evidence = [
        ParsedEvidence(
            id="evi-1",
            category="delivery",
            claim_text="Led AI teams.",
            verified=True,
            tags=[],
        )
    ]
    original = [r"\textbf{Enterprise AI:} operating model design"]
    reworded = [r"\textbf{Enterprise AI:} pharma operating model design for healthcare"]
    job_words = generator._cv_grounding_words(evidence, job, settings)
    evidence_only = generator._content_words("Led AI teams.")
    assert generator._group_grounded(reworded, original, job_words)
    assert not generator._group_grounded(reworded, original, evidence_only)


def test_apply_summary_sentences_keeps_grounded_only():
    nums = {"5", "10"}
    ents = {"langgraph"}
    text = "Led agentic AI delivery for 5 teams. Invented 999 new platforms at ZephyrLabs."
    summary, report = generator._apply_summary_sentences(text, nums, ents)
    assert summary is not None
    assert "5 teams" in summary
    assert "999" not in summary
    assert report["status"] == "partial"
    assert report["sentences_dropped"] == 1


def test_compose_summary_from_claims_uses_ranked_claims():
    from zengrowth.materials.cv_alignment import compose_summary_from_claims
    from zengrowth.materials.evidence import ParsedEvidence

    evidence = [
        ParsedEvidence(
            id="a",
            category="x",
            claim_text="Built multi-agent platforms.",
            verified=True,
            tags=[],
        ),
        ParsedEvidence(
            id="b",
            category="y",
            claim_text="Led enterprise AI operating model.",
            verified=True,
            tags=[],
        ),
    ]
    ranked = [
        {"id": "a", "score": 2, "claim": evidence[0].claim_text},
        {"id": "b", "score": 0, "claim": evidence[1].claim_text},
    ]
    text = compose_summary_from_claims(ranked, evidence, max_words=20)
    assert "multi-agent" in text
    assert "operating model" not in text


def test_generate_cv_records_tailoring_report(session, tmp_path, monkeypatch):
    from zengrowth.materials.evidence import ParsedEvidence
    from zengrowth.models import AuditLog

    job = _job()
    session.add(job)
    session.commit()
    session.refresh(job)
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path)
    monkeypatch.setattr(generator, "compile_pdf", lambda path: (None, "pdf_unavailable_no_latex_compiler"))
    monkeypatch.setattr(
        generator,
        "_load_evidence_with_source",
        lambda s, limit=None: (
            [
                ParsedEvidence(
                    id="evi-1",
                    category="impact",
                    claim_text="Shipped models.",
                    verified=True,
                    tags=[],
                )
            ],
            "db",
        ),
    )
    original = generator._parse_cv_template(generator._read_cv_template())
    bad_caps = list(original["capabilities"])
    bad_caps[0] = bad_caps[0] + " delivering 777 extra wins"
    client = FakeMaterialClient(
        {
            "title": "Tailored CV",
            "summary": "An AI leader with 888 years of delivery.",
            "capabilities": bad_caps,
            "evidence_ids": ["evi-1"],
        }
    )
    material = generate_cv(session, job, client=client, settings=Settings(anthropic_api_key="test"))
    tailoring = material.draft_json["tailoring"]
    assert tailoring["summary"]["status"] in {"template_fallback", "partial", "evidence_compose"}
    assert "888" not in Path(material.tex_path).read_text(encoding="utf-8")
    assert tailoring["capabilities"]["status"] in {"partial", "template_fallback"}
    assert tailoring["capabilities"]["reason"] in {"group_ok", "partial", "group_grounded", None}
    audit = session.exec(
        select(AuditLog).where(AuditLog.action == "generate_cv")
    ).first()
    assert audit.detail["tailoring"]["summary"]["reason"] in {
        "ungrounded_numbers",
        "all_sentences_dropped",
    }


def test_effective_cv_draft_json_backfills_from_rendered_tex():
    from zengrowth.materials.generator import (
        _parse_cv_template,
        _read_cv_template,
        effective_cv_draft_json,
        render_cv,
    )

    template = _read_cv_template()
    original = _parse_cv_template(template)
    sparse = {
        "title": "Role CV",
        "summary": None,
        "capabilities": [],
        "experience": {"0": original["experience"][0][:1]},
        "evidence_ids": ["evi-1"],
    }
    tex = render_cv(
        generator.CvTailoring(
            title="Role CV",
            summary=None,
            capabilities=[],
            experience=sparse["experience"],
            evidence_ids=["evi-1"],
        ),
        template_text=template,
    )
    enriched = effective_cv_draft_json(sparse, tex_content=tex)
    assert enriched is not None
    assert enriched["summary"]
    assert len(enriched["capabilities"]) == len(original["capabilities"])
    assert enriched["experience"] == sparse["experience"]
