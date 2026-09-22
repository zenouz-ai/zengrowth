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
    tex_path.write_text(r"\documentclass{article}\begin{document}LONG SHORT\end{document}", encoding="utf-8")

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

    pdf_path, status, page_count, page_fill, report = gen.compile_and_fit_cv(
        tex_path, settings=Settings(anthropic_api_key="test"), client=FitClient()
    )

    assert page_count == 2
    assert FitClient.calls == 1
    assert report["applied"] == ["shorten"]
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
            return r"\documentclass{article}\linespread{1.1}\begin{document}\vspace{4pt}TINY\\[3pt]\end{document}"

    monkeypatch.setattr(gen, "compile_pdf", fake_compile)
    monkeypatch.setattr(gen, "measure_pdf_extent", fake_measure)

    pdf_path, status, page_count, page_fill, report = gen.compile_and_fit_cv(
        tex_path,
        settings=Settings(anthropic_api_key="test"),
        client=FitClient(),
    )

    assert page_count == 2
    assert page_fill == 0.92
    assert FitClient.calls == 1
    assert report["applied"] == ["loosen"]
    assert "linespread" in tex_path.read_text(encoding="utf-8")


def _fit_harness(monkeypatch, *, pages, fill, compile_ok=lambda text: True):
    from zengrowth.materials import generator as gen

    def fake_compile(path):
        if not compile_ok(path.read_text(encoding="utf-8")):
            return None, "pdf_compile_failed: boom"
        path.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n")
        return path.with_suffix(".pdf"), "pdf_created"

    monkeypatch.setattr(gen, "compile_pdf", fake_compile)
    monkeypatch.setattr(gen, "measure_pdf_extent", lambda pdf: (pages, fill))
    return gen


def _fit_client(revised: str):
    class Client:
        def complete_text(self, system, user, model, max_tokens=8000, **kwargs):
            return revised

    return Client()


def test_fit_shorten_rejects_ungrounded_figure_and_keeps_file(tmp_path, monkeypatch):
    """A 'shorten' rewrite that invents a metric never reaches the CV on disk."""
    gen = _fit_harness(monkeypatch, pages=3, fill=0.5)
    original = r"\documentclass{article}\begin{document}Led a data team at Contoso.\end{document}"
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(original, encoding="utf-8")
    fabricated = r"\documentclass{article}\begin{document}Led a 40-person team.\end{document}"
    job = _job()

    *_, report = gen.compile_and_fit_cv(
        tex_path,
        settings=Settings(anthropic_api_key="test"),
        client=_fit_client(fabricated),
        evidence=[generator.ParsedEvidence(id="e1", category="leadership", claim_text="Led a data team at Contoso.")],
        job=job,
    )

    assert tex_path.read_text(encoding="utf-8") == original
    assert report["applied"] == []
    assert report["rejected"][0]["kind"] == "shorten"


def test_fit_shorten_rejects_new_unevidenced_word(tmp_path, monkeypatch):
    gen = _fit_harness(monkeypatch, pages=3, fill=0.5)
    original = r"\documentclass{article}\begin{document}Built Python services.\end{document}"
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(original, encoding="utf-8")
    swapped = r"\documentclass{article}\begin{document}Built Rust services.\end{document}"

    *_, report = gen.compile_and_fit_cv(
        tex_path, settings=Settings(anthropic_api_key="test"), client=_fit_client(swapped)
    )

    assert tex_path.read_text(encoding="utf-8") == original
    assert "rust" in " ".join(report["rejected"][0]["reasons"])


def test_fit_loosen_rejects_wording_change(tmp_path, monkeypatch):
    """TP-04: the typography pass may not change a single word."""
    gen = _fit_harness(monkeypatch, pages=2, fill=0.5)
    original = r"\documentclass{article}\begin{document}Built Python services.\end{document}"
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(original, encoding="utf-8")
    expanded = r"\documentclass{article}\begin{document}Built many Python services.\end{document}"

    *_, report = gen.compile_and_fit_cv(
        tex_path, settings=Settings(anthropic_api_key="test"), client=_fit_client(expanded)
    )

    assert tex_path.read_text(encoding="utf-8") == original
    assert report["rejected"][0]["kind"] == "loosen"


def test_fit_restores_last_good_tex_when_rewrite_fails_to_compile(tmp_path, monkeypatch):
    original = r"\documentclass{article}\begin{document}Built Python services.\end{document}"
    broken = r"\documentclass{article}\begin{document}Built Python services."
    gen = _fit_harness(monkeypatch, pages=3, fill=0.5, compile_ok=lambda text: text == original)
    tex_path = tmp_path / "cv.tex"
    tex_path.write_text(original, encoding="utf-8")

    pdf_path, status, *_, report = gen.compile_and_fit_cv(
        tex_path, settings=Settings(anthropic_api_key="test"), client=_fit_client(broken)
    )

    assert tex_path.read_text(encoding="utf-8") == original
    assert pdf_path is not None and status == "pdf_created"
    assert report["rejected"][0]["reasons"][0].startswith("pdf_compile_failed")


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
    """High-fit CV gates widen to JD vocabulary (TP-16); strict CVs and cover letters do not."""
    from zengrowth.materials.evidence import ParsedEvidence

    settings = Settings(anthropic_api_key="test")
    job = _job()
    job.fit_score = 72.0  # aligned tier
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

    # Strict tier: JD-only tools/words are not something the candidate can assert.
    job.fit_score = 40.0
    assert "pharma" not in generator._cv_grounding_words(evidence, job, settings)
    assert "autogen" not in generator._cv_grounding_entity_tokens(evidence, job, settings)


def test_strict_cv_grounding_rejects_jd_only_numbers_and_tools():
    """Regression: a JD demanding 'teams of 20' and PyTorch must not ground a strict CV claim."""
    from zengrowth.materials.cv_alignment import cv_grounding_corpus

    settings = Settings(anthropic_api_key="test")
    job = _job()
    job.fit_score = 40.0
    job.description = "Lead teams of 20 engineers building PyTorch models."
    job.score_rationale = {"summary": "Mentions TensorFlow and 35 reports."}
    evidence = [
        generator.ParsedEvidence(id="e1", category="leadership", claim_text="Led a data team.")
    ]
    nums = generator._cv_grounding_number_tokens(evidence, job, settings)
    ents = generator._cv_grounding_entity_tokens(evidence, job, settings)
    assert "20" not in nums and "pytorch" not in ents

    # No tier grounds on the scorer's own rationale (model output).
    job.fit_score = 90.0
    corpus = cv_grounding_corpus(job, "priority")
    assert "TensorFlow" not in corpus and "35" not in corpus


def test_cv_priority_profile_expands_synonyms_and_company():
    from zengrowth.materials.cv_alignment import cv_grounding_profile, expand_grounding_words

    settings = Settings(anthropic_api_key="test", cv_priority_fit_threshold=85)
    job = _job()
    job.fit_score = 90.0
    job.company = "Aldermont"
    assert cv_grounding_profile(job, settings) == "priority"
    words = expand_grounding_words({"pharma", "delivery"}, "priority")
    assert "pharmaceutical" in words


def test_cv_capabilities_accept_job_context_words():
    from zengrowth.materials.evidence import ParsedEvidence

    settings = Settings(anthropic_api_key="test")
    job = _job()
    job.fit_score = 72.0  # aligned tier: JD vocabulary is allowed (TP-16)
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


def test_refresh_cv_draft_after_fit_describes_the_file_on_disk():
    """Review data (summary, change summary) must follow the post-fit LaTeX."""
    from zengrowth.materials.generator import _parse_cv_template, refresh_cv_draft_after_fit

    def cv(summary: str) -> str:
        return (
            "\\documentclass{article}\\begin{document}\n"
            "\\section*{Professional Summary}\n"
            f"{summary}\n"
            "\\section*{Core Capabilities}\n"
            "\\textbf{AI:} Python\n"
            "\\section*{Education}\nPhD\n\\end{document}\n"
        )

    baseline = _parse_cv_template(cv("Original summary about platforms."))
    draft = {"summary": "Pre-fit summary.", "tailoring": {"grounding_profile": "strict"}}

    refreshed = refresh_cv_draft_after_fit(draft, cv("Trimmed summary."), baseline)

    assert refreshed["summary"] == "Trimmed summary."
    assert refreshed["tailoring"]["grounding_profile"] == "strict"
    assert refreshed["tailoring"]["change_summary"]["lines_changed"] >= 1
    assert refreshed["template_baseline"] == baseline


_LOOSEN_BASE = (
    r"\documentclass{article}\begin{document}"
    r"\section*{Experience}\begin{itemize}\item Built Python services.\end{itemize}"
    r"\end{document}"
)


@pytest.mark.parametrize(
    "revised",
    [
        # list spacing via an optional key=value argument
        _LOOSEN_BASE.replace(r"\begin{itemize}", r"\begin{itemize}[itemsep=4pt]"),
        # a spacing environment wrapped around the same content
        _LOOSEN_BASE.replace(
            r"\begin{itemize}", r"\begin{spacing}{1.15}\begin{itemize}"
        ).replace(r"\end{itemize}", r"\end{itemize}\end{spacing}"),
        # explicit vertical space and a sized line break
        _LOOSEN_BASE.replace(r"\section*{Experience}", r"\vspace{6pt}\section*{Experience}").replace(
            r"\end{itemize}", r"\end{itemize}\\[3pt]"
        ),
        # font-size switch and preamble geometry change
        _LOOSEN_BASE.replace(
            r"\documentclass{article}",
            r"\documentclass{article}\usepackage[margin=1in]{geometry}\linespread{1.1}",
        ).replace(r"\begin{itemize}", r"\small\begin{itemize}"),
    ],
)
def test_fit_loosen_accepts_typography_only_changes(revised: str):
    """A genuine spacing/typography pass must not be rejected as a wording change.

    Each variant restyles the *same* document: the section heading and the list
    survive, because a typography pass that dropped them would be restructuring
    the page, not respacing it.
    """
    from zengrowth.materials.generator import fit_rewrite_violations

    assert fit_rewrite_violations("loosen", _LOOSEN_BASE, revised) == []


def test_fit_loosen_rejects_dropping_a_bullet_or_heading():
    r"""Deleting an \item or a section leaves the words intact, so the word-level
    comparison cannot see it — the structural check must."""
    from zengrowth.materials.generator import fit_rewrite_violations

    merged = _LOOSEN_BASE.replace(r"\begin{itemize}\item ", "")
    assert fit_rewrite_violations("loosen", _LOOSEN_BASE, merged.replace(r"\end{itemize}", ""))
    heading_gone = _LOOSEN_BASE.replace(r"\section*{Experience}", "")
    assert fit_rewrite_violations("loosen", _LOOSEN_BASE, heading_gone)


def test_fit_loosen_still_catches_a_dropped_bullet():
    from zengrowth.materials.generator import fit_rewrite_violations

    current = r"\documentclass{article}\begin{document}\item Built Python services. \item Led the platform team.\end{document}"
    trimmed = r"\documentclass{article}\begin{document}\vspace{4pt}\item Built Python services.\end{document}"
    assert fit_rewrite_violations("loosen", current, trimmed)


def test_fit_loosen_rejects_commenting_out_a_line():
    """A `%` comment removes a line from the PDF while leaving the words in source."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\begin{document}\n"
        "Built Python services.\n"
        "Led the platform team.\n"
        "\\end{document}\n"
    )
    commented = current.replace("Led the platform team.", "% Led the platform team.")
    assert fit_rewrite_violations("loosen", current, commented)
    # An escaped percent sign is literal content, not a comment.
    escaped = current.replace("Built Python services.", "Built Python services (99\\% uptime).")
    assert fit_rewrite_violations("loosen", current, escaped)


def test_fit_gate_still_sees_a_changed_braced_date():
    """`{2024}` is content, not a layout dimension: changing it must be visible."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = r"\documentclass{article}\begin{document}\cvdate{2024} Built Python services.\end{document}"
    changed = r"\documentclass{article}\begin{document}\cvdate{2025} Built Python services.\end{document}"
    assert fit_rewrite_violations("loosen", current, changed)
    assert fit_rewrite_violations("shorten", current, changed)


def test_fit_shorten_rejects_dropping_a_bullet():
    """Structure-preserving: a fitted CV must still round-trip through render_cv,
    which only substitutes groups whose line counts match the template."""
    from zengrowth.materials.generator import fit_rewrite_violations

    def cv(bullets: list[str]) -> str:
        items = "\n".join(rf"\item {b}" for b in bullets)
        return (
            "\\documentclass{article}\\begin{document}\n"
            "\\section*{Professional Summary}\nSummary line.\n"
            "\\section*{Core Capabilities}\n\\textbf{AI:} Python\n"
            "\\section*{Professional Experience}\n"
            f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}\n"
            "\\section*{Education}\nPhD\n\\end{document}\n"
        )

    current = cv(["Built Python services.", "Led the platform team."])
    trimmed = cv(["Built Python services."])
    violations = fit_rewrite_violations("shorten", current, trimmed)
    assert any("bullet counts" in v for v in violations)
    # Tightening the wording of the same number of lines is still allowed.
    tightened = cv(["Built Python services.", "Led the team."])
    assert fit_rewrite_violations("shorten", current, tightened) == []


@pytest.mark.parametrize(
    "hidden",
    [
        r"\documentclass{article}\begin{document}Built Python services.\iffalse Led the team.\fi\end{document}",
        r"\documentclass{article}\begin{document}Built Python services.\phantom{Led the team.}\end{document}",
        r"\documentclass{article}\begin{document}Built Python services.\textcolor{white}{Led the team.}\end{document}",
    ],
)
def test_fit_rejects_constructs_that_hide_content_from_the_pdf(hidden: str):
    """Words can stay in the source while vanishing from the PDF — a word-level
    diff cannot see that, so only typography commands may be introduced."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = r"\documentclass{article}\begin{document}Built Python services.Led the team.\end{document}"
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted a content-hiding construct"
        assert "non-typography" in violations[0]


def test_fit_loosen_rejects_comment_after_an_even_backslash_run():
    r"""`\\%` is a line break followed by a comment, not an escaped percent."""
    from zengrowth.materials.generator import _strip_tex_comments, fit_rewrite_violations

    current = (
        "\\documentclass{article}\\begin{document}\n"
        "Built Python services.\\\\\n"
        "Led the platform team.\n"
        "\\end{document}\n"
    )
    # The rewrite replaces the newline after the break with a comment marker.
    hidden = current.replace("services.\\\\\nLed", "services.\\\\% Led")
    assert fit_rewrite_violations("loosen", current, hidden)

    # Parity: one backslash escapes, two do not.
    assert _strip_tex_comments(r"99\% uptime") == r"99\% uptime"
    assert _strip_tex_comments("break\\\\% hidden") == "break\\\\"


def test_fit_rejects_relocating_nested_phantom_onto_content():
    """Brace-balanced args: nested macros must not defeat the fingerprint."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{\textbf{x}} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{\textbf{x} Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted a nested relocated \\phantom"
        assert "non-typography" in violations[0]


def test_fit_rejects_relocating_textcolor_with_optional_model():
    r"""``\textcolor[HTML]{...}{...}`` must fingerprint the optional model + body."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor[HTML]{FFFFFF}{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor[HTML]{FFFFFF}{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted a relocated optional-model \\textcolor"
        assert "non-typography" in violations[0]


def test_fit_rejects_relocating_into_nested_iffalse():
    r"""Depth-balanced ``\iffalse``: text must not slip between nested ``\fi`` tokens."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\iffalse x \iffalse y\fi\fi Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\iffalse x \iffalse y\fi Led the team.\fi"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved into nested \\iffalse"
        assert "non-typography" in violations[0]


def test_fit_rejects_relocating_into_scoped_color():
    r"""``{\color{white}x}`` has no braced body — growing the group must still reject."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.{\color{white}x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.{\color{white}x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved into scoped \\color"
        assert "non-typography" in violations[0]


def test_fit_iffalse_ignores_ifthenelse_inside_block():
    r"""``\ifthenelse`` is not a TeX conditional; it must not unbalance ``\iffalse``."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services."
        r"\iffalse x \ifthenelse{1}{a}{b} y\fi "
        r"Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services."
        r"\iffalse x \ifthenelse{1}{a}{b} y Led the team.\fi"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved into \\iffalse with \\ifthenelse"
        assert "non-typography" in violations[0]


def test_fit_rejects_relocating_hphantom_onto_content():
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\hphantom{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\hphantom{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted a relocated \\hphantom"
        assert "non-typography" in violations[0]


def test_fit_rejects_moving_text_across_declaration_color():
    r"""Declaration ``\color{white}...\color{black}`` must fingerprint spans between switches."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\color{white} x \color{black} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\color{white} x Led the team. \color{black}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved into declaration \\color"
        assert "non-typography" in violations[0]


def test_fit_allows_vspace_after_visible_declaration_color():
    """Typography after ``\\color{black}`` must not trip the colour fingerprint."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\color{black} Led the team."
        r"\end{document}"
    )
    loosened = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\color{black}\vspace{-1pt} Led the team."
        r"\end{document}"
    )
    assert fit_rewrite_violations("loosen", current, loosened) == []


def test_fit_rejects_phantom_with_escaped_brace_growth():
    r"""``\{`` is literal; growing ``\phantom{\{}`` must still be detected."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{\{} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{\{ Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth of \\phantom with escaped brace"
        assert "non-typography" in violations[0]


def test_fit_rejects_iffalse_when_commented_fi_is_ignored():
    r"""A ``% \fi`` inside ``\iffalse`` must not close the block for fingerprinting."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\begin{document}"
        "Built Python services.\\iffalse x % \\fi\n y\\fi Led the team."
        "\\end{document}"
    )
    hidden = (
        "\\documentclass{article}\\begin{document}"
        "Built Python services.\\iffalse x % \\fi\n y Led the team.\\fi"
        "\\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved past a commented \\fi"
        assert "non-typography" in violations[0]


def test_fit_shorten_allows_edits_inside_visible_textcolor():
    """Visible ``\\textcolor{black}{...}`` must not block legitimate shortening."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"\textcolor{black}{Built Python services. Led the team.}"
        r"\end{document}"
    )
    shortened = (
        r"\documentclass{article}\begin{document}"
        r"\textcolor{black}{Built Python services.}"
        r"\end{document}"
    )
    violations = fit_rewrite_violations("shorten", current, shortened)
    assert not any("non-typography" in v for v in violations)


def test_fit_rejects_rgb_white_textcolor_growth():
    r"""``\textcolor[rgb]{1,1,1}{...}`` is white and must be fingerprinted."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor[rgb]{1,1,1}{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor[rgb]{1,1,1}{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth of rgb-white \\textcolor"
        assert "non-typography" in violations[0]


def test_fit_rejects_phantom_with_commented_brace():
    r"""A ``% }`` inside a phantom arg must not close the group early."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\begin{document}"
        "Built Python services.\\phantom{x % }\n} Led the team."
        "\\end{document}"
    )
    hidden = (
        "\\documentclass{article}\\begin{document}"
        "Built Python services.\\phantom{x % }\n Led the team.}"
        "\\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth past a commented brace"
        assert "non-typography" in violations[0]


def test_fit_rejects_white_mix_textcolor_growth():
    r"""xcolor mix ``white!100`` must still count as a hiding colour."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor{white!100}{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor{white!100}{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth of white!100 \\textcolor"
        assert "non-typography" in violations[0]


def test_fit_rejects_moving_text_into_begingroup_white():
    r"""Declaration ``\color{white}`` must stop at ``\endgroup``."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begingroup\color{white}x\endgroup Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begingroup\color{white}x Led the team.\endgroup"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved before \\endgroup"
        assert "non-typography" in violations[0]


def test_fit_rejects_iffalse_when_double_backslash_fi_ignored():
    r"""``\\fi`` is a line break plus letters, not a conditional closer."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\iffalse x\\fi y\fi Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\iffalse x\\fi y Led the team.\fi"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved past a false \\fi after \\\\"
        assert "non-typography" in violations[0]


def test_fit_rejects_definecolor_white_alias_growth():
    r"""``\definecolor{paper}{HTML}{FFFFFF}`` aliases must resolve as hiding."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\definecolor{paper}{HTML}{FFFFFF}\begin{document}"
        r"Built Python services.\textcolor{paper}{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\definecolor{paper}{HTML}{FFFFFF}\begin{document}"
        r"Built Python services.\textcolor{paper}{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth of definecolor-white \\textcolor"
        assert "non-typography" in violations[0]


def test_fit_rejects_moving_text_into_minipage_white():
    r"""Declaration ``\color{white}`` must stop at ``\end{minipage}``."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begin{minipage}{\linewidth}\color{white}x\end{minipage} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begin{minipage}{\linewidth}\color{white}x Led the team.\end{minipage}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved before \\end{{minipage}}"
        assert "non-typography" in violations[0]


def test_fit_rejects_moving_text_between_nested_env_ends_under_white():
    r"""A white declaration spans nested environments up to its own ``\end``."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begin{minipage}{\linewidth}\color{white}"
        r"\begin{itemize}\item x\end{itemize}\end{minipage} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\begin{minipage}{\linewidth}\color{white}"
        r"\begin{itemize}\item x\end{itemize} Led the team.\end{minipage}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved inside the white minipage"
        assert "non-typography" in violations[0]


def test_fit_rejects_black_zero_mix_textcolor_growth():
    r"""``black!0`` renders white (0% black, 100% default white)."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor{black!0}{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\textcolor{black!0}{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted growth of black!0 \\textcolor"
        assert "non-typography" in violations[0]


def test_xcolor_mix_evaluation():
    from zengrowth.materials.generator import _is_hiding_color

    assert _is_hiding_color("", "{black!0}")
    assert _is_hiding_color("", "{white!100}")
    assert _is_hiding_color("", "{white!50!white}")
    assert _is_hiding_color("", "{-black}")
    assert not _is_hiding_color("", "{white!50!black}")
    assert not _is_hiding_color("", "{black!50}")
    assert not _is_hiding_color("", "{unknownshade!40}")
    assert _is_hiding_color("", "{unknownshade!0}")


def test_fit_allows_shortening_inside_gray_mix_textcolor():
    r"""A visible mix such as ``black!60`` must not block ordinary shortening."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"\textcolor{black!60}{Built Python services for the whole team.}"
        r"\end{document}"
    )
    shorter = (
        r"\documentclass{article}\begin{document}"
        r"\textcolor{black!60}{Built Python services for the team.}"
        r"\end{document}"
    )
    assert fit_rewrite_violations("shorten", current, shorter) == []


def test_fit_rejects_iffalse_when_newif_conditional_nested():
    r"""``\newif\iffoo`` makes ``\iffoo`` a real conditional inside ``\iffalse``."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\newif\iffoo\begin{document}"
        r"Built Python services.\iffalse x \iffoo y\fi\fi Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\newif\iffoo\begin{document}"
        r"Built Python services.\iffalse x \iffoo y\fi Led the team.\fi"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved inside a newif-nested \\iffalse"
        assert "non-typography" in violations[0]


def test_fit_rejects_comment_env_when_commented_end_ignored():
    r"""A ``% \end{comment}`` inside a comment block must not close it early."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services.\\begin{comment}x % \\end{comment}\n"
        "y\\end{comment} Led the team."
        "\\end{document}"
    )
    hidden = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services.\\begin{comment}x % \\end{comment}\n"
        "y Led the team.\\end{comment}"
        "\\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved past a commented \\end{{comment}}"
        assert "environments" in violations[0] or "non-typography" in violations[0]


def test_fit_rejects_relocating_an_existing_phantom_onto_content():
    """Same \\phantom count, different args — must still reject."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{x Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted a relocated \\phantom"
        assert "non-typography" in violations[0]


def test_fit_rejects_extra_phantom_when_one_already_exists():
    """Name-set diffs miss a second \\phantom wrapping more text; count them."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{x} Led the team."
        r"\end{document}"
    )
    hidden = (
        r"\documentclass{article}\begin{document}"
        r"Built Python services.\phantom{x} \phantom{Led the team.}"
        r"\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted an extra \\phantom"
        assert "non-typography" in violations[0]


def test_fit_rejects_extra_comment_env_when_one_already_exists():
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services. \\begin{comment}spacer\\end{comment} Led the team."
        "\\end{document}"
    )
    hidden = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services. \\begin{comment}spacer\\end{comment} "
        "\\begin{comment}Led the team.\\end{comment}"
        "\\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted an extra comment environment"
        assert "non-typography" in violations[0]


def test_fit_rejects_relocating_into_spaced_comment_env():
    r"""``\begin {comment}`` is valid LaTeX; fingerprints must allow the space."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services. \\begin {comment}x\\end {comment} Led the team."
        "\\end{document}"
    )
    hidden = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services. \\begin {comment}x Led the team.\\end {comment}"
        "\\end{document}"
    )
    for kind in ("loosen", "shorten"):
        violations = fit_rewrite_violations(kind, current, hidden)
        assert violations, f"{kind} accepted text moved into spaced comment env"
        assert "environments" in violations[0] or "non-typography" in violations[0]


def test_fit_rejects_a_content_swallowing_environment():
    """`\\begin{comment}` keeps the words in source but drops them from the PDF."""
    from zengrowth.materials.generator import fit_rewrite_violations

    current = r"\documentclass{article}\begin{document}Built Python services. Led the team.\end{document}"
    hidden = (
        "\\documentclass{article}\\usepackage{comment}\\begin{document}"
        "Built Python services. \\begin{comment}Led the team.\\end{comment}\\end{document}"
    )
    violations = fit_rewrite_violations("loosen", current, hidden)
    assert violations and "environments" in violations[0]


def test_fit_shorten_fails_closed_on_an_unparseable_cv():
    """A promoted .tex with non-template headings still keeps a structural invariant."""
    from zengrowth.materials.generator import _parse_cv_template, fit_rewrite_violations

    def cv(bullets: list[str]) -> str:
        items = "\n".join(rf"\item {b}" for b in bullets)
        return (
            "\\documentclass{article}\\begin{document}\n"
            "\\section{Experience}\n"  # unstarred, not matched by the template regex
            f"\\begin{{itemize}}\n{items}\n\\end{{itemize}}\n"
            "\\end{document}\n"
        )

    current = cv(["Built Python services.", "Led the platform team."])
    # Precondition: the template parser genuinely finds no groups here.
    assert _parse_cv_template(current)["capabilities"] == []
    assert _parse_cv_template(current)["experience"] == []

    dropped = cv(["Built Python services."])
    violations = fit_rewrite_violations("shorten", current, dropped)
    assert any("bullet count" in v for v in violations)

    # Deleting a whole section is caught too.
    section_dropped = "\\documentclass{article}\\begin{document}\n\\end{document}\n"
    assert fit_rewrite_violations("shorten", current, section_dropped)
