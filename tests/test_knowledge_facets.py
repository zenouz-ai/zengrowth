"""KG-02 Stage 1 — facet vocabulary, assignment, backfill, and coverage tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from zengrowth.api.main import app
from zengrowth.config import Settings
from zengrowth.db import get_session
from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.jobs.delete import delete_job
from zengrowth.knowledge.coverage import coverage_report
from zengrowth.knowledge.facets import (
    FACET_KEYS,
    assign_document_facets,
    assign_job_facets,
    backfill_facets,
    job_facet_text,
    load_facet_vocabulary,
    validate_facet_assignments,
)
from zengrowth.models import (
    AuditLog,
    ClaimFacet,
    ClaimVerificationState,
    EvidenceClaim,
    Job,
    JobFacet,
    JobSource,
    SourceDocument,
    SourceDocumentStatus,
)


class FakeAssigner:
    """Deterministic assigner: returns a canned response, counts calls."""

    def __init__(self, response_for: dict[str, dict[str, list[str]]]) -> None:
        self.response_for = response_for
        self.calls: list[list[str]] = []

    def assign(
        self,
        *,
        items: list[dict[str, str]],
        vocabulary: dict[str, list[str]],
        model: str,
    ) -> dict[str, Any]:
        self.calls.append([item["id"] for item in items])
        return {
            "assignments": [
                {"id": item["id"], "facets": self.response_for.get(item["id"], {})}
                for item in items
            ]
        }


class FailingAssigner:
    def assign(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("facet model unavailable")


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(knowledge_root=str(tmp_path / "knowledge"), **overrides)


def _make_document(session: Session, name: str = "cv") -> SourceDocument:
    doc = SourceDocument(
        filename=f"{name}.md",
        original_path=f"data/knowledge/originals/{name}.md",
        content_hash=f"hash-{name}",
        source_type="cv",
        status=SourceDocumentStatus.extracted,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _make_claim(
    session: Session,
    doc: SourceDocument,
    claim_id: str,
    text: str,
    state: ClaimVerificationState = ClaimVerificationState.verified,
) -> EvidenceClaim:
    claim = EvidenceClaim(
        id=claim_id,
        source_document_id=doc.id,
        claim_text=text,
        category="technical",
        confidence=0.9,
        verification_state=state,
        source_span=text,
    )
    session.add(claim)
    session.commit()
    return claim


def _make_job(session: Session, title: str = "Head of AI", scored: bool = True) -> Job:
    job = Job(
        company="Acme",
        title=title,
        posting_date=date(2026, 6, 1),
        source=JobSource.manual,
        dedup_hash=dedup_hash("Acme", title, date(2026, 6, 1)),
        fit_score=80.0 if scored else None,
        job_summary={
            "role_overview": "Lead the insurance AI function.",
            "company_domain": "Insurance",
            "requirements": ["MLOps platform experience", "Team leadership"],
        },
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# --- vocabulary -------------------------------------------------------------


def test_vocabulary_merges_defaults_settings_and_operator_file(tmp_path):
    settings = _settings(
        tmp_path,
        user_target_sectors=["InsurTech"],
        user_target_roles=["Head of AI"],
        user_location="London",
    )
    root = Path(settings.knowledge_root)
    root.mkdir(parents=True)
    (root / "facets.json").write_text(
        json.dumps({"capability": ["Graph  RAG"], "not_a_facet": ["ignored"]}),
        encoding="utf-8",
    )
    vocabulary = load_facet_vocabulary(settings)

    assert set(vocabulary) == set(FACET_KEYS)
    assert "insurtech" in vocabulary["industry"]  # settings sector, normalized
    assert "head of ai" in vocabulary["role_family"]  # settings role
    assert "london" in vocabulary["location"]
    assert "graph rag" in vocabulary["capability"]  # operator file, whitespace folded
    assert "not_a_facet" not in vocabulary
    assert "insurance" in vocabulary["industry"]  # checked-in default survives
    # No duplicates anywhere.
    for values in vocabulary.values():
        assert len(values) == len(set(values))


def test_vocabulary_tolerates_corrupt_operator_file(tmp_path):
    settings = _settings(tmp_path)
    root = Path(settings.knowledge_root)
    root.mkdir(parents=True)
    (root / "facets.json").write_text("{not json", encoding="utf-8")
    assert "insurance" in load_facet_vocabulary(settings)["industry"]


# --- validation: the closed vocabulary is enforced --------------------------


def test_validate_rejects_unknown_ids_facets_and_values(tmp_path):
    vocabulary = load_facet_vocabulary(_settings(tmp_path))
    raw = {
        "assignments": [
            {
                "id": "c1",
                "facets": {
                    "industry": ["Insurance", "underwater basket weaving"],
                    "made_up_facet": ["x"],
                    "capability": "not-a-list",
                },
            },
            {"id": "ghost", "facets": {"industry": ["insurance"]}},
        ]
    }
    clean, rejected = validate_facet_assignments(raw, {"c1"}, vocabulary)

    assert clean == {"c1": {"industry": ["insurance"]}}
    assert any("out-of-vocabulary industry" in r for r in rejected)
    assert any("unknown facet: 'made_up_facet'" in r for r in rejected)
    assert any("unknown item id: 'ghost'" in r for r in rejected)


# --- assignment + idempotent storage ----------------------------------------


def test_assign_document_facets_stores_and_replaces_rows(session, tmp_path):
    settings = _settings(tmp_path)
    doc = _make_document(session)
    _make_claim(session, doc, "c1", "Led insurance pricing models.")
    assigner = FakeAssigner(
        {"c1": {"industry": ["insurance"], "capability": ["team leadership"]}}
    )

    report = assign_document_facets(session, doc, assigner=assigner, settings=settings)
    assert report.items_faceted == 1
    assert report.facet_rows == 2
    rows = session.exec(select(ClaimFacet)).all()
    assert {(r.facet, r.value) for r in rows} == {
        ("industry", "insurance"),
        ("capability", "team leadership"),
    }

    # Re-assignment replaces wholesale — no duplicate rows accumulate.
    assigner.response_for = {"c1": {"industry": ["insurance"]}}
    assign_document_facets(session, doc, assigner=assigner, settings=settings)
    rows = session.exec(select(ClaimFacet)).all()
    assert {(r.facet, r.value) for r in rows} == {("industry", "insurance")}

    audit = [
        a for a in session.exec(select(AuditLog)) if a.action == "knowledge_facets_assigned"
    ]
    assert len(audit) == 2


def test_assign_job_facets_uses_summary_text(session, tmp_path):
    settings = _settings(tmp_path)
    job = _make_job(session)
    text = job_facet_text(job)
    assert "Head of AI at Acme" in text
    assert "MLOps platform experience" in text

    assigner = FakeAssigner(
        {f"job-{job.id}": {"industry": ["insurance"], "capability": ["mlops"]}}
    )
    report = assign_job_facets(session, job, assigner=assigner, settings=settings)
    assert report.facet_rows == 2
    rows = session.exec(select(JobFacet)).all()
    assert {(r.job_id, r.facet, r.value) for r in rows} == {
        (job.id, "industry", "insurance"),
        (job.id, "capability", "mlops"),
    }


# --- backfill: pragmatic cache + determinism --------------------------------


def test_backfill_facets_skips_already_faceted_unless_forced(session, tmp_path):
    settings = _settings(tmp_path)
    doc = _make_document(session)
    _make_claim(session, doc, "c1", "Led insurance pricing models.")
    job = _make_job(session)
    unscored = _make_job(session, title="Unscored role", scored=False)
    assigner = FakeAssigner(
        {
            "c1": {"industry": ["insurance"]},
            f"job-{job.id}": {"industry": ["insurance"]},
        }
    )

    first = backfill_facets(session, assigner=assigner, settings=settings)
    assert (first.documents_faceted, first.jobs_faceted) == (1, 1)
    assert first.facet_rows == 2
    # Unscored jobs are not demand — never faceted.
    assert all(f"job-{unscored.id}" not in ids for ids in assigner.calls)

    second = backfill_facets(session, assigner=assigner, settings=settings)
    assert (second.documents_faceted, second.jobs_faceted) == (0, 0)
    assert (second.documents_skipped, second.jobs_skipped) == (1, 1)
    assert len(assigner.calls) == 2  # no new LLM spend

    forced = backfill_facets(session, assigner=assigner, settings=settings, force=True)
    assert (forced.documents_faceted, forced.jobs_faceted) == (1, 1)
    # Deterministic: a forced re-run reproduces identical rows.
    rows = {(r.claim_id, r.facet, r.value) for r in session.exec(select(ClaimFacet))}
    assert rows == {("c1", "industry", "insurance")}


# --- pipeline integration: derived metadata never breaks the pipeline -------


def test_score_job_assigns_demand_facets_and_survives_facet_failure(
    session, fake_score_response, tmp_path
):
    from zengrowth.scoring.scorer import score_job

    class FakeLLM:
        def score(self, system: str, user: str, model: str) -> dict[str, Any]:
            return fake_score_response

    settings = _settings(tmp_path)
    job = _make_job(session, title="Director of AI", scored=False)
    assigner = FakeAssigner({f"job-{job.id}": {"seniority": ["director"]}})
    score_job(session, job, client=FakeLLM(), facet_assigner=assigner, settings=settings)
    rows = session.exec(select(JobFacet)).all()
    assert {(r.facet, r.value) for r in rows} == {("seniority", "director")}

    # A facet failure is logged but scoring still succeeds.
    job2 = _make_job(session, title="Head of ML", scored=False)
    scored = score_job(
        session, job2, client=FakeLLM(), facet_assigner=FailingAssigner(), settings=settings
    )
    assert scored.expected_value is not None
    failures = [a for a in session.exec(select(AuditLog)) if a.action == "job_facets_failed"]
    assert len(failures) == 1


def test_ingest_faceting_failure_does_not_fail_ingest(session, tmp_path, monkeypatch):
    from tests.test_knowledge import FakeEmbedder, FakeExtractor
    from zengrowth.knowledge.service import ingest_path

    root = tmp_path / "knowledge"
    monkeypatch.setenv("KNOWLEDGE_ROOT", str(root))
    source = tmp_path / "project.txt"
    source.write_text("GraphRAG investment agent used Neo4j.", encoding="utf-8")
    result = ingest_path(
        session,
        source,
        extractor=FakeExtractor(),
        embedder=FakeEmbedder(),
        facet_assigner=FailingAssigner(),
    )
    assert result.document.status == SourceDocumentStatus.extracted
    failures = [
        a for a in session.exec(select(AuditLog)) if a.action == "knowledge_facets_failed"
    ]
    assert len(failures) == 1


def test_ingest_assigns_facets_with_injected_assigner(session, tmp_path, monkeypatch):
    from tests.test_knowledge import FakeEmbedder, FakeExtractor
    from zengrowth.knowledge.service import ingest_path

    root = tmp_path / "knowledge"
    monkeypatch.setenv("KNOWLEDGE_ROOT", str(root))
    source = tmp_path / "project.txt"
    source.write_text("GraphRAG investment agent used Neo4j.", encoding="utf-8")

    class AnyClaimAssigner:
        def assign(self, *, items, vocabulary, model):
            return {
                "assignments": [
                    {"id": item["id"], "facets": {"project_type": ["agentic system"]}}
                    for item in items
                ]
            }

    ingest_path(
        session,
        source,
        extractor=FakeExtractor(),
        embedder=FakeEmbedder(),
        facet_assigner=AnyClaimAssigner(),
    )
    rows = session.exec(select(ClaimFacet)).all()
    assert rows
    assert {r.value for r in rows} == {"agentic system"}


# --- cleanup paths ----------------------------------------------------------


def test_delete_job_removes_job_facets(session):
    job = _make_job(session)
    session.add(JobFacet(job_id=job.id, facet="industry", value="insurance"))
    session.commit()
    delete_job(session, job)
    session.commit()
    assert session.exec(select(JobFacet)).all() == []


def test_claim_dedup_redirects_facets_to_canonical_claim(session):
    from zengrowth.knowledge.dedup import deduplicate_knowledge

    doc = _make_document(session)
    _make_claim(session, doc, "c-long", "Jordan led the insurance pricing programme.")
    _make_claim(session, doc, "c-short", "Led the insurance pricing programme.")
    session.add_all(
        [
            ClaimFacet(claim_id="c-long", facet="industry", value="insurance"),
            ClaimFacet(claim_id="c-short", facet="industry", value="insurance"),
            ClaimFacet(claim_id="c-short", facet="capability", value="strategy"),
        ]
    )
    session.commit()

    report = deduplicate_knowledge(session)
    assert report.claims_removed == 1
    rows = session.exec(select(ClaimFacet)).all()
    # The duplicate's unique facet moved to the canonical claim; the shared one
    # did not duplicate.
    assert {(r.claim_id, r.facet, r.value) for r in rows} == {
        ("c-long", "industry", "insurance"),
        ("c-long", "capability", "strategy"),
    }


# --- coverage aggregation ---------------------------------------------------


def _seed_coverage(session: Session) -> tuple[Job, Job]:
    doc = _make_document(session)
    _make_claim(session, doc, "c-ins-1", "Led insurance pricing models.")
    _make_claim(session, doc, "c-ins-2", "Shipped an insurance claims triage model.")
    _make_claim(
        session, doc, "c-draft", "Draft claim.", state=ClaimVerificationState.draft
    )
    _make_claim(
        session, doc, "c-rej", "Rejected claim.", state=ClaimVerificationState.rejected
    )
    job_ins = _make_job(session, title="Head of Insurance AI")
    job_health = _make_job(session, title="Director of Healthcare AI")
    session.add_all(
        [
            ClaimFacet(claim_id="c-ins-1", facet="industry", value="insurance"),
            ClaimFacet(claim_id="c-ins-2", facet="industry", value="insurance"),
            ClaimFacet(claim_id="c-draft", facet="industry", value="healthcare"),
            ClaimFacet(claim_id="c-rej", facet="industry", value="healthcare"),
            JobFacet(job_id=job_ins.id, facet="industry", value="insurance"),
            JobFacet(job_id=job_health.id, facet="industry", value="healthcare"),
        ]
    )
    session.commit()
    return job_ins, job_health


def test_coverage_report_counts_and_gap_flags(session, tmp_path):
    job_ins, job_health = _seed_coverage(session)
    report = coverage_report(session, settings=_settings(tmp_path))

    industry = next(f for f in report["facets"] if f["facet"] == "industry")
    by_value = {v["value"]: v for v in industry["values"]}

    insurance = by_value["insurance"]
    assert insurance["verified_claims"] == 2
    assert insurance["claim_ids"] == ["c-ins-1", "c-ins-2"]
    assert insurance["demand_jobs"] == 1
    assert insurance["job_ids"] == [job_ins.id]
    assert insurance["gap"] is False
    assert insurance["monthly"] and insurance["monthly"][0]["claims"] == 2

    # Healthcare is demanded, has only draft evidence (rejected excluded
    # entirely) — a real gap.
    healthcare = by_value["healthcare"]
    assert healthcare["verified_claims"] == 0
    assert healthcare["draft_claims"] == 1
    assert healthcare["gap"] is True
    assert healthcare["job_ids"] == [job_health.id]

    assert report["totals"]["scored_jobs"] == 2
    assert report["totals"]["faceted_jobs"] == 2
    assert report["totals"]["unfaceted_jobs"] == 0
    # c-rej is excluded from active claims and from faceted_claims — totals
    # never let faceted_claims exceed claims.
    assert report["totals"]["claims"] == 3
    assert report["totals"]["faceted_claims"] == 3
    assert report["totals"]["faceted_claims"] <= report["totals"]["claims"]
    assert {j["id"] for j in report["jobs"]} == {job_ins.id, job_health.id}

    # Deterministic: a second aggregation is identical.
    assert coverage_report(session, settings=_settings(tmp_path)) == report


# --- API --------------------------------------------------------------------


def test_coverage_endpoint_returns_facets(session, tmp_path):
    _seed_coverage(session)

    def override() -> Session:
        return session

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        response = client.get("/api/knowledge/coverage")
        assert response.status_code == 200
        data = response.json()
        assert {f["facet"] for f in data["facets"]} == set(FACET_KEYS)
        industry = next(f for f in data["facets"] if f["facet"] == "industry")
        assert any(v["value"] == "insurance" and not v["gap"] for v in industry["values"])
        assert any(v["value"] == "healthcare" and v["gap"] for v in industry["values"])
        assert data["totals"]["faceted_claims"] == 3
        assert data["totals"]["faceted_claims"] <= data["totals"]["claims"]
    finally:
        app.dependency_overrides.clear()


def test_coverage_backfill_endpoint_requires_api_key(session):
    def override() -> Session:
        return session

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        response = client.post("/api/knowledge/coverage/backfill")
        assert response.status_code == 400
        assert "Anthropic API key" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
