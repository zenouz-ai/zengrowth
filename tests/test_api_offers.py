"""Offer stage (OFF-01): record, evaluate, respond, outcome sync."""

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from zengrowth.api.main import app
from zengrowth.db import get_session
from zengrowth.interviews.offers import (
    OFFER_EVALUATION_SECTIONS,
    generate_offer_evaluation,
    generate_offer_response,
)
from zengrowth.materials import generator
from zengrowth.models import Job, JobOffer, OfferStatus


def _client(session: Session) -> TestClient:
    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def _job(session: Session, dedup_hash: str = "offer-1") -> Job:
    job = Job(
        company="Northwind",
        title="Director of AI",
        source="manual",
        dedup_hash=dedup_hash,
        location="London",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _offer(session: Session, job: Job, **kwargs) -> JobOffer:
    kwargs.setdefault("base_salary", 140000)
    kwargs.setdefault("currency", "GBP")
    offer = JobOffer(job_id=job.id or 0, **kwargs)
    session.add(offer)
    session.commit()
    session.refresh(offer)
    return offer


class FakeOfferClient:
    """Returns a canned document; records prompts for assertions."""

    def __init__(self, markdown: str):
        self.markdown = markdown
        self.prompts: list[str] = []
        self.web_calls: list[bool] = []

    def generate_document(
        self, system, user, model, max_tokens, *, operation_name, allow_web=True
    ):  # noqa: ANN001
        self.prompts.append(user)
        self.web_calls.append(allow_web)
        return self.markdown, [{"url": "https://example.com/salary", "title": "Salary survey"}], allow_web


def _evaluation_markdown() -> str:
    return "\n\n".join(f"## {section}\nContent for {section.lower()}." for section in OFFER_EVALUATION_SECTIONS)


# --- CRUD + outcome sync -------------------------------------------------------


def test_create_offer_syncs_outcome_to_offer_stage(session: Session):
    job = _job(session)
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/offers",
            json={
                "base_salary": 140000,
                "currency": "GBP",
                "holiday_days": 28,
                "pension": "6% employer match",
                "deadline_at": "2026-07-20T12:00:00Z",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "received"
        assert data["base_salary"] == 140000

        session.refresh(job)
        assert job.outcome_stage == "offer"
        assert job.outcome_result == "offer"
        assert job.lifecycle_state == "offer"
        assert job.applied_at is not None
    finally:
        app.dependency_overrides.clear()


def test_create_offer_without_sync_leaves_outcome(session: Session):
    job = _job(session, "offer-2")
    client = _client(session)
    try:
        resp = client.post(f"/api/jobs/{job.id}/offers", json={"sync_outcome": False})
        assert resp.status_code == 201
        session.refresh(job)
        assert job.outcome_stage is None
        assert job.lifecycle_state == "discovered"
    finally:
        app.dependency_overrides.clear()


def test_accept_offer_sets_terminal_result(session: Session):
    job = _job(session, "offer-3")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.patch(
            f"/api/jobs/{job.id}/offers/{offer.id}", json={"status": "accepted"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"
        session.refresh(job)
        assert job.outcome_result == "accepted"
        assert job.outcome_stage == "offer"
        assert job.lifecycle_state == "offer"
    finally:
        app.dependency_overrides.clear()


def test_decline_offer_sets_declined_result(session: Session):
    job = _job(session, "offer-4")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.patch(
            f"/api/jobs/{job.id}/offers/{offer.id}", json={"status": "declined"}
        )
        assert resp.status_code == 200
        session.refresh(job)
        assert job.outcome_result == "declined"
    finally:
        app.dependency_overrides.clear()


def test_patch_terms_without_status_change_skips_sync(session: Session):
    job = _job(session, "offer-5")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.patch(
            f"/api/jobs/{job.id}/offers/{offer.id}",
            json={"bonus": "15% target", "sync_outcome": True},
        )
        assert resp.status_code == 200
        assert resp.json()["bonus"] == "15% target"
        session.refresh(job)
        assert job.outcome_stage is None  # terms edit alone never moves the funnel
    finally:
        app.dependency_overrides.clear()


def test_list_and_delete_offers(session: Session):
    job = _job(session, "offer-6")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.get(f"/api/jobs/{job.id}/offers")
        assert resp.status_code == 200
        assert [row["id"] for row in resp.json()] == [offer.id]

        resp = client.delete(f"/api/jobs/{job.id}/offers/{offer.id}")
        assert resp.status_code == 204
        assert client.get(f"/api/jobs/{job.id}/offers").json() == []
    finally:
        app.dependency_overrides.clear()


def test_offer_endpoints_404_on_wrong_job(session: Session):
    job = _job(session, "offer-7")
    other = _job(session, "offer-8")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.patch(
            f"/api/jobs/{other.id}/offers/{offer.id}", json={"status": "accepted"}
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# --- evaluation ----------------------------------------------------------------


def test_generate_offer_evaluation(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-9")
    offer = _offer(session, job, holiday_days=25, pension="4% match", offer_text="Dear candidate…")
    client = FakeOfferClient(_evaluation_markdown())

    material = generate_offer_evaluation(session, job, offer, client=client)

    assert material.material_type == "offer_evaluation"
    assert material.audience == "internal"
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert document.startswith("---\n")
    assert "# Offer evaluation — Northwind" in document
    assert "> [!warning]" in document
    assert "## Market Benchmark" in document
    assert "## Sources" in document
    assert "https://example.com/salary" in document

    # The prompt carries the offer terms, letter text, and operator expectations.
    prompt = client.prompts[0]
    assert '"base_salary": 140000' in prompt
    assert "Dear candidate" in prompt
    assert "candidate_expectations" in prompt

    # Evaluating a freshly received offer moves it to "evaluating".
    session.refresh(offer)
    assert offer.status == OfferStatus.evaluating


def test_generate_offer_evaluation_empty_document_raises(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-10")
    offer = _offer(session, job)
    client = FakeOfferClient("   ")
    try:
        generate_offer_evaluation(session, job, offer, client=client)
    except ValueError as exc:
        assert "empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# --- response drafts ------------------------------------------------------------


def test_generate_counter_response_uses_evaluation_and_sets_negotiating(
    session: Session, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-11")
    offer = _offer(session, job)
    # Seed a prior evaluation so the counter draft can ground its asks.
    generate_offer_evaluation(session, job, offer, client=FakeOfferClient(_evaluation_markdown()))

    client = FakeOfferClient("## Subject\nRe: Offer\n\n## Body\nThank you — may we discuss base?")
    material = generate_offer_response(
        session, job, offer, response_type="counter", client=client
    )

    assert material.material_type == "offer_response"
    assert material.audience == "internal"
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert "nothing is sent by ZenGrowth" in document
    assert "## Subject" in document

    prompt = client.prompts[0]
    assert '"response_type": "counter"' in prompt
    assert "market_evaluation" in prompt
    assert "Negotiation Levers" in prompt  # evaluation body fed into the draft
    assert "[!warning]" not in prompt  # provenance callout stripped, not fed to the LLM
    assert client.web_calls == [False]  # drafts never spend on web search

    session.refresh(offer)
    assert offer.status == OfferStatus.negotiating


def test_generate_accept_response_keeps_status(session: Session, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-12")
    offer = _offer(session, job)
    generate_offer_evaluation(session, job, offer, client=FakeOfferClient(_evaluation_markdown()))
    client = FakeOfferClient("## Subject\nAccepting\n\n## Body\nDelighted to accept.")
    generate_offer_response(session, job, offer, response_type="accept", client=client)
    session.refresh(offer)
    # Accept draft alone is not a decision, and it doesn't ship the ~6k-char
    # market evaluation into the prompt — only counter drafts ground in it.
    assert offer.status == OfferStatus.evaluating
    assert '"market_evaluation": null' in client.prompts[0]


def test_response_draft_endpoint_rejects_unknown_type(session: Session):
    job = _job(session, "offer-13")
    offer = _offer(session, job)
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/offers/{offer.id}/response-draft",
            json={"response_type": "ghost"},
        )
        # Literal["accept","counter","clarify"] rejects at request parse time.
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


# --- extraction (OFF-04) ---------------------------------------------------------


class FakeExtractClient:
    """Echoes canned extraction JSON; records prompts."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def extract(self, system, user, model):  # noqa: ANN001
        self.prompts.append(user)
        return dict(self.payload)


def test_extract_offer_fields_maps_dates_and_preserves_text():
    from zengrowth.interviews.offer_extractor import extract_offer_fields

    client = FakeExtractClient(
        {
            "base_salary": 140000,
            "currency": "GBP",
            "pension": "6% employer match",
            "holiday_days": 28,
            "received_date": "2026-07-10",
            "deadline_date": "2026-07-20",
            "missing_fields": ["equity"],
            "confidence_notes": "No equity mentioned.",
        }
    )
    raw = "Dear candidate, we are delighted to offer you £140,000..."
    extracted = extract_offer_fields(raw_text=raw, client=client)

    assert extracted.base_salary == 140000
    assert extracted.currency == "GBP"
    assert extracted.holiday_days == 28
    assert extracted.received_at is not None and extracted.received_at.day == 10
    assert extracted.deadline_at is not None and extracted.deadline_at.day == 20
    assert extracted.offer_text == raw
    assert extracted.missing_fields == ["equity"]
    # The prompt carries the raw text for conservative extraction.
    assert "delighted to offer" in client.prompts[0]


def test_extract_offer_fields_rejects_empty_text():
    from zengrowth.interviews.offer_extractor import extract_offer_fields

    try:
        extract_offer_fields(raw_text="   ", client=FakeExtractClient({}))
    except ValueError as exc:
        assert "nothing to extract" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_extract_offer_endpoint_returns_prefill(session: Session, monkeypatch):
    from zengrowth.api.routers import offers as offers_router
    from zengrowth.interviews.offer_extractor import ExtractedOfferFields

    job = _job(session, "offer-14")

    def fake_extract(*, raw_text, session=None, entity_id=None):  # noqa: ANN001, ARG001
        return ExtractedOfferFields(
            base_salary=140000, currency="GBP", offer_text=raw_text, missing_fields=["equity"]
        )

    monkeypatch.setattr(offers_router, "extract_offer_fields", fake_extract)
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/offers/extract",
            json={"raw_text": "We are pleased to offer £140,000."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["base_salary"] == 140000
        assert data["offer_text"] == "We are pleased to offer £140,000."
        assert data["missing_fields"] == ["equity"]
        # Nothing is saved until the operator submits the reviewed form.
        assert client.get(f"/api/jobs/{job.id}/offers").json() == []
    finally:
        app.dependency_overrides.clear()


def test_extract_offer_file_endpoint_parses_document(session: Session, monkeypatch):
    from zengrowth.api.routers import offers as offers_router
    from zengrowth.interviews.offer_extractor import ExtractedOfferFields

    job = _job(session, "offer-15")
    captured: dict = {}

    def fake_extract(*, raw_text, session=None, entity_id=None):  # noqa: ANN001, ARG001
        captured["raw_text"] = raw_text
        return ExtractedOfferFields(base_salary=150000, offer_text=raw_text)

    monkeypatch.setattr(offers_router, "extract_offer_fields", fake_extract)
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/offers/extract-file",
            files={"file": ("offer.txt", b"Base salary: GBP 150,000 per annum.", "text/plain")},
        )
        assert resp.status_code == 200
        assert resp.json()["base_salary"] == 150000
        assert "150,000" in captured["raw_text"]
    finally:
        app.dependency_overrides.clear()


def test_extract_offer_file_rejects_unsupported_type(session: Session):
    job = _job(session, "offer-16")
    client = _client(session)
    try:
        resp = client.post(
            f"/api/jobs/{job.id}/offers/extract-file",
            files={"file": ("offer.exe", b"MZ", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "unsupported offer document type" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# --- onboarding pack (OFF-03) ----------------------------------------------------


def _onboarding_markdown() -> str:
    from zengrowth.interviews.offers import ONBOARDING_SECTIONS

    body = "\n\n".join(f"## {s}\nContent for {s.lower()}." for s in ONBOARDING_SECTIONS)
    return body + "\n\nYour evidence: [claim-abc123def4567890]."


def test_generate_onboarding_pack_carries_process_context(
    session: Session, tmp_path: Path, monkeypatch
):
    from zengrowth.ingestion.dedup import dedup_hash as _dedup
    from zengrowth.interviews.offers import generate_onboarding_pack
    from zengrowth.models import (
        ClaimVerificationState,
        EvidenceClaim,
        Interview,
        SourceDocument,
    )

    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = Job(
        company="Northwind",
        title="Director of AI",
        source="manual",
        dedup_hash=_dedup("Northwind Onboarding", "Director of AI", None),
        location="London",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    _offer(session, job, status=OfferStatus.accepted, pension="6% match")
    session.add(
        Interview(
            job_id=job.id or 0,
            participants=[{"name": "Indhira Mani", "role": "CDO"}],
            notes="Panel focused on AI governance.",
        )
    )
    document = SourceDocument(
        filename="cv.md", original_path="/tmp/cv.md", content_hash="onboarding-claim-doc"
    )
    session.add(document)
    session.commit()
    session.add(
        EvidenceClaim(
            id="claim-abc123def4567890",
            source_document_id=document.id or 0,
            claim_text="Led a 12-person AI team delivering GBP 3m efficiency gains.",
            category="leadership",
            confidence=0.9,
            verification_state=ClaimVerificationState.verified,
        )
    )
    session.commit()

    client = FakeOfferClient(_onboarding_markdown())
    material = generate_onboarding_pack(session, job, client=client)

    assert material.material_type == "onboarding_pack"
    assert material.audience == "internal"
    assert material.evidence_ids == ["claim-abc123def4567890"]

    doc = Path(material.markdown_path).read_text(encoding="utf-8")
    assert doc.startswith("---\n")
    assert "# Onboarding pack — Northwind" in doc
    assert "## Stakeholder Map" in doc
    assert "## First 30 Days — Learn And Listen" in doc
    assert "## Sources" in doc

    prompt = client.prompts[0]
    assert "Indhira Mani" in prompt  # interview participants feed the stakeholder map
    assert '"6% match"' in prompt  # accepted offer terms included
    assert '"status": "accepted"' in prompt


def test_onboarding_pack_endpoint_without_key_fails_closed(session: Session):
    job = _job(session, "offer-17")
    _offer(session, job, status=OfferStatus.accepted)
    client = _client(session)
    try:
        resp = client.post(f"/api/jobs/{job.id}/materials/onboarding-pack")
        assert resp.status_code in (502, 503)
    finally:
        app.dependency_overrides.clear()


# --- departure pack (OFF-05) -----------------------------------------------------


def _departure_markdown() -> str:
    from zengrowth.interviews.departure import DEPARTURE_SECTIONS

    return "\n\n".join(f"## {s}\nContent for {s.lower()}." for s in DEPARTURE_SECTIONS)


def test_generate_departure_pack_uses_offer_dates_and_context(
    session: Session, tmp_path: Path, monkeypatch
):
    from datetime import date

    from zengrowth.interviews.departure import generate_departure_pack

    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-18")
    _offer(session, job, status=OfferStatus.accepted, start_date=date(2026, 10, 1))
    client = FakeOfferClient(_departure_markdown())

    material = generate_departure_pack(
        session,
        job,
        current_company="Contoso",
        current_role="Head of Data",
        manager_name="Alex Kim",
        notice_period="3 months",
        achievements="Delivered the ML platform saving GBP 2m/yr.",
        client=client,
    )

    assert material.material_type == "departure_pack"
    assert material.audience == "internal"
    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert document.startswith("---\n")
    assert "# Departure pack — leaving Contoso" in document
    assert "## Resignation Letter" in document
    assert "## Leaving Checklist" in document
    assert "check every date and obligation" in document.lower()

    prompt = client.prompts[0]
    assert '"current_company": "Contoso"' in prompt
    assert '"manager_name": "Alex Kim"' in prompt
    assert '"contractual_notice_period": "3 months"' in prompt
    assert '"start_date": "2026-10-01"' in prompt  # accepted offer feeds the arithmetic
    assert "ML platform" in prompt


def test_departure_pack_endpoint_without_key_fails_closed(session: Session):
    job = _job(session, "offer-19")
    _offer(session, job, status=OfferStatus.accepted)
    client = _client(session)
    try:
        resp = client.post(f"/api/jobs/{job.id}/materials/departure-pack", json={})
        assert resp.status_code in (502, 503)
    finally:
        app.dependency_overrides.clear()


def test_revised_offer_evaluation_carries_negotiation_history(
    session: Session, tmp_path: Path, monkeypatch
):
    """OFF-01 follow-up: evaluating a revised offer compares against the prior
    offer and the counter the candidate actually sent."""
    from zengrowth.interviews.offers import NEGOTIATION_SECTION, evaluation_sections
    from zengrowth.interviews.service import import_internal_material

    monkeypatch.setattr(generator, "MATERIALS_ROOT", tmp_path / "materials")
    job = _job(session, "offer-20")
    _offer(session, job, status=OfferStatus.negotiating)  # 140k opener
    import_internal_material(
        session,
        job,
        material_type="offer_response",
        title="Counter-offer email — sent to Ray",
        content="## Subject\nRe: Offer\n\n## Body\nThank you Ray - I would like to ask for a 150000 base and 30 days holiday.",
    )
    revised = _offer(session, job, base_salary=148000, holiday_days=30)

    markdown = "\n\n".join(
        f"## {s}\nContent for {s.lower()}." for s in evaluation_sections(negotiating=True)
    )
    client = FakeOfferClient(markdown)
    material = generate_offer_evaluation(session, job, revised, client=client)

    document = Path(material.markdown_path).read_text(encoding="utf-8")
    assert f"## {NEGOTIATION_SECTION}" in document

    prompt = client.prompts[0]
    assert "negotiation_history" in prompt
    assert '"base_salary": 140000' in prompt  # the prior offer's terms
    assert '"base_salary": 148000' in prompt  # the revised offer under evaluation
    assert "ask for a 150000 base" in prompt  # the sent counter grounds the comparison
    assert NEGOTIATION_SECTION in prompt  # required section requested from the model
    # First offers stay unchanged: no movement section when there is no history.
    assert NEGOTIATION_SECTION not in evaluation_sections(negotiating=False)
