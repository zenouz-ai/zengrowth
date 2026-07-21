"""KG-02 Stage 1 — controlled-vocabulary facet assignment for the coverage map.

Facets turn the evidence bank into aggregable coverage data: every claim (and
every scored JD summary) is tagged against a **closed** vocabulary — industry,
role family, project type, capability, location, seniority — so counts roll up
instead of fragmenting into free text. Deliberately *not* topic modelling: at
single-operator corpus size clustering is unstable, and a light structured pass
assigns cleanly and auditable (see ``docs/EVIDENCE-COVERAGE-PLAN.md``).

The vocabulary is the checked-in ``facet_vocabulary.json`` merged with the
operator's settings (target sectors → industry, target roles → role family,
location) and an optional per-deployment ``<knowledge_root>/facets.json``.
Assignment is one small strict-JSON LLM call per document (all its claims in
one batch) or per job, at temperature 0 through ``InstrumentedLLM`` so spend is
visible and budget-capped. Values outside the vocabulary are **rejected, not
invented** — they are dropped and reported in the audit detail.

Facets are derived metadata: assignment failures never fail ingest or scoring,
rows are replaced wholesale on re-assignment (idempotent), and the truth path
(claim extraction / verification) is untouched. All claims are faceted at
assignment time — draft ones too — so later verification needs no re-tagging;
coverage surfaces count verified and draft depth separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import Session, select

from ..audit import log_action_safe
from ..config import Settings, get_settings
from ..models import (
    ActorType,
    ClaimFacet,
    EvidenceClaim,
    Job,
    JobFacet,
    SourceDocument,
    SourceDocumentStatus,
)
from ..observability.client import InstrumentedLLM, build_instrumented_llm

FACET_KEYS = (
    "industry",
    "role_family",
    "project_type",
    "capability",
    "location",
    "seniority",
)

_DEFAULT_VOCABULARY_PATH = Path(__file__).parent / "facet_vocabulary.json"
# Operator-editable extension file, relative to settings.knowledge_root.
OPERATOR_VOCABULARY_FILENAME = "facets.json"


def normalize_facet_value(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _merge_values(vocabulary: dict[str, list[str]], facet: str, values: list[str]) -> None:
    seen = set(vocabulary.setdefault(facet, []))
    for value in values:
        normalized = normalize_facet_value(str(value))
        if normalized and normalized not in seen:
            seen.add(normalized)
            vocabulary[facet].append(normalized)


def load_facet_vocabulary(settings: Settings | None = None) -> dict[str, list[str]]:
    """The closed facet vocabulary: checked-in defaults + operator seeds.

    Merged in order — defaults, settings profile (target sectors → industry,
    target roles → role family, configured location), then the optional
    ``<knowledge_root>/facets.json`` extension. Unknown facet keys in the
    extension file are ignored; values are normalized and de-duplicated.
    """
    settings = settings or get_settings()
    raw = json.loads(_DEFAULT_VOCABULARY_PATH.read_text(encoding="utf-8"))
    vocabulary: dict[str, list[str]] = {}
    for facet in FACET_KEYS:
        _merge_values(vocabulary, facet, list(raw.get(facet, [])))

    _merge_values(vocabulary, "industry", list(settings.user_target_sectors))
    _merge_values(vocabulary, "role_family", list(settings.user_target_roles))
    _merge_values(vocabulary, "location", [settings.user_location])

    operator_path = Path(settings.knowledge_root) / OPERATOR_VOCABULARY_FILENAME
    if operator_path.exists():
        try:
            extension = json.loads(operator_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            extension = {}
        if isinstance(extension, dict):
            for facet in FACET_KEYS:
                values = extension.get(facet)
                if isinstance(values, list):
                    _merge_values(vocabulary, facet, [str(v) for v in values])
    return vocabulary


class FacetAssignmentClient(Protocol):
    def assign(
        self,
        *,
        items: list[dict[str, str]],
        vocabulary: dict[str, list[str]],
        model: str,
    ) -> dict[str, Any]: ...


SYSTEM_PROMPT = """You classify short career-evidence texts against a fixed controlled vocabulary.
Return exactly one JSON object and nothing else. For each item, choose only values that the text clearly supports, copied verbatim from the vocabulary. If no vocabulary value applies for a facet, return an empty list for it. Never invent values outside the vocabulary."""


def build_assignment_prompt(
    items: list[dict[str, str]], vocabulary: dict[str, list[str]]
) -> str:
    schema = {
        "assignments": [
            {
                "id": "item id copied from ITEMS",
                "facets": {facet: ["vocabulary values that clearly apply"] for facet in FACET_KEYS},
            }
        ]
    }
    return (
        "Classify each ITEM against the VOCABULARY for a career-evidence coverage map.\n"
        "Use only values present in the vocabulary; omit rather than guess.\n\n"
        f"VOCABULARY:\n{json.dumps(vocabulary, indent=2)}\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"ITEMS:\n{json.dumps(items, indent=2, ensure_ascii=False)}"
    )


def _validate_assignment_response(parsed: dict[str, Any]) -> None:
    assignments = parsed.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("facet response missing 'assignments' list")


class InstrumentedFacetAssigner:
    """Facet assigner backed by the central instrumented LLM client (temp 0)."""

    def __init__(
        self,
        llm: InstrumentedLLM,
        *,
        session: Session | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
    ) -> None:
        self._llm = llm
        self._session = session
        self._entity_type = entity_type
        self._entity_id = entity_id

    def assign(
        self,
        *,
        items: list[dict[str, str]],
        vocabulary: dict[str, list[str]],
        model: str,
    ) -> dict[str, Any]:
        return self._llm.chat_json(
            system=SYSTEM_PROMPT,
            user=build_assignment_prompt(items, vocabulary),
            model=model,
            max_tokens=2500,
            operation_name="assign_facets",
            session=self._session,
            entity_type=self._entity_type,
            entity_id=self._entity_id,
            validate=_validate_assignment_response,
            # Deterministic to re-derive (TP-07 discipline): the same items and
            # vocabulary must produce the same facet counts across runs.
            temperature=0.0,
        )


def build_default_facet_assigner(
    settings: Settings | None = None,
    *,
    session: Session | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> FacetAssignmentClient:
    settings = settings or get_settings()
    return InstrumentedFacetAssigner(
        build_instrumented_llm(settings),
        session=session,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def validate_facet_assignments(
    raw: dict[str, Any],
    valid_ids: set[str],
    vocabulary: dict[str, list[str]],
) -> tuple[dict[str, dict[str, list[str]]], list[str]]:
    """Enforce the closed vocabulary on a raw LLM response.

    Returns ``(clean, rejected)``: ``clean`` maps each known item id to
    ``facet -> sorted unique values`` (all guaranteed in-vocabulary); every
    dropped id / facet key / value lands in ``rejected`` so the audit trail
    shows exactly what the model tried to invent.
    """
    allowed = {facet: set(values) for facet, values in vocabulary.items()}
    clean: dict[str, dict[str, list[str]]] = {}
    rejected: list[str] = []
    assignments = raw.get("assignments") if isinstance(raw, dict) else None
    for entry in assignments or []:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("id", ""))
        if item_id not in valid_ids:
            rejected.append(f"unknown item id: {item_id!r}")
            continue
        facets_in = entry.get("facets")
        item_facets: dict[str, list[str]] = {}
        if isinstance(facets_in, dict):
            for facet, values in facets_in.items():
                if facet not in allowed:
                    rejected.append(f"unknown facet: {facet!r}")
                    continue
                if not isinstance(values, list):
                    continue
                kept: set[str] = set()
                for value in values:
                    normalized = normalize_facet_value(str(value))
                    if normalized in allowed[facet]:
                        kept.add(normalized)
                    elif normalized:
                        rejected.append(f"out-of-vocabulary {facet}: {normalized!r}")
                if kept:
                    item_facets[facet] = sorted(kept)
        clean[item_id] = item_facets
    return clean, rejected


@dataclass
class FacetAssignmentReport:
    items_faceted: int = 0
    facet_rows: int = 0
    rejected: list[str] = field(default_factory=list)


def _replace_claim_facets(
    session: Session, claim_id: str, facets: dict[str, list[str]]
) -> int:
    for row in session.exec(select(ClaimFacet).where(ClaimFacet.claim_id == claim_id)):
        session.delete(row)
    count = 0
    for facet, values in facets.items():
        for value in values:
            session.add(ClaimFacet(claim_id=claim_id, facet=facet, value=value))
            count += 1
    return count


def _replace_job_facets(session: Session, job_id: int, facets: dict[str, list[str]]) -> int:
    for row in session.exec(select(JobFacet).where(JobFacet.job_id == job_id)):
        session.delete(row)
    count = 0
    for facet, values in facets.items():
        for value in values:
            session.add(JobFacet(job_id=job_id, facet=facet, value=value))
            count += 1
    return count


def assign_document_facets(
    session: Session,
    document: SourceDocument,
    *,
    assigner: FacetAssignmentClient,
    settings: Settings | None = None,
) -> FacetAssignmentReport:
    """Facet all of a document's claims in one batched LLM call."""
    settings = settings or get_settings()
    claims = session.exec(
        select(EvidenceClaim).where(EvidenceClaim.source_document_id == document.id)
    ).all()
    report = FacetAssignmentReport()
    if not claims:
        return report
    vocabulary = load_facet_vocabulary(settings)
    items = [{"id": claim.id, "text": claim.claim_text} for claim in claims]
    raw = assigner.assign(items=items, vocabulary=vocabulary, model=settings.scoring_model)
    clean, rejected = validate_facet_assignments(raw, {c.id for c in claims}, vocabulary)
    for claim_id, facets in clean.items():
        report.facet_rows += _replace_claim_facets(session, claim_id, facets)
        report.items_faceted += 1
    report.rejected = rejected
    session.commit()
    log_action_safe(
        session,
        actor=ActorType.agent,
        action="knowledge_facets_assigned",
        entity_type="source_document",
        entity_id=document.id,
        detail={
            "claims_faceted": report.items_faceted,
            "facet_rows": report.facet_rows,
            "rejected": rejected[:20],
        },
    )
    return report


def job_facet_text(job: Job) -> str:
    """The demand text a job is faceted on: title + the cleaned JD summary."""
    parts: list[str] = [f"{job.title} at {job.company}"]
    if job.location:
        parts.append(f"Location: {job.location}")
    if job.hybrid_policy:
        parts.append(f"Hybrid policy: {job.hybrid_policy}")
    if job.seniority:
        parts.append(f"Seniority: {job.seniority}")
    summary = job.job_summary or {}
    for key in (
        "role_overview",
        "company_domain",
        "location_hybrid",
        "responsibilities",
        "requirements",
    ):
        value = summary.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    if len(parts) <= 4 and job.description:
        parts.append(job.description[:2000])
    return "\n".join(parts)


def assign_job_facets(
    session: Session,
    job: Job,
    *,
    assigner: FacetAssignmentClient,
    settings: Settings | None = None,
) -> FacetAssignmentReport:
    """Facet one scored job's demand (title + JD summary) in one LLM call."""
    settings = settings or get_settings()
    report = FacetAssignmentReport()
    if job.id is None:
        return report
    vocabulary = load_facet_vocabulary(settings)
    item_id = f"job-{job.id}"
    raw = assigner.assign(
        items=[{"id": item_id, "text": job_facet_text(job)}],
        vocabulary=vocabulary,
        model=settings.scoring_model,
    )
    clean, rejected = validate_facet_assignments(raw, {item_id}, vocabulary)
    facets = clean.get(item_id, {})
    report.facet_rows = _replace_job_facets(session, job.id, facets)
    report.items_faceted = 1 if facets else 0
    report.rejected = rejected
    session.commit()
    log_action_safe(
        session,
        actor=ActorType.agent,
        action="job_facets_assigned",
        entity_type="job",
        entity_id=job.id,
        detail={"facet_rows": report.facet_rows, "rejected": rejected[:20]},
    )
    return report


def facets_available(settings: Settings) -> bool:
    """Facet assignment needs an Anthropic key; without one it is skipped, not failed."""
    return bool(settings.anthropic_api_key)


@dataclass
class FacetBackfillReport:
    documents_faceted: int = 0
    documents_skipped: int = 0
    jobs_faceted: int = 0
    jobs_skipped: int = 0
    facet_rows: int = 0
    rejected: list[str] = field(default_factory=list)


def _document_has_facets(session: Session, document_id: int) -> bool:
    claim_ids = [
        c.id
        for c in session.exec(
            select(EvidenceClaim).where(EvidenceClaim.source_document_id == document_id)
        )
    ]
    if not claim_ids:
        return False
    return (
        session.exec(
            select(ClaimFacet).where(ClaimFacet.claim_id.in_(claim_ids))  # type: ignore[attr-defined]
        ).first()
        is not None
    )


def _job_has_facets(session: Session, job_id: int) -> bool:
    return (
        session.exec(select(JobFacet).where(JobFacet.job_id == job_id)).first() is not None
    )


def backfill_facets(
    session: Session,
    *,
    assigner: FacetAssignmentClient | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> FacetBackfillReport:
    """Batch-facet every extracted document and scored job.

    A document/job that already has facet rows is skipped unless ``force`` —
    the pragmatic cache: unchanged inputs never re-spend. ``force`` re-assigns
    everything (rows are replaced wholesale, so counts stay deterministic).
    """
    settings = settings or get_settings()
    assigner = assigner or build_default_facet_assigner(settings, session=session)
    report = FacetBackfillReport()

    documents = session.exec(
        select(SourceDocument).where(SourceDocument.status == SourceDocumentStatus.extracted)
    ).all()
    for document in documents:
        if document.id is None:
            continue
        if not force and _document_has_facets(session, document.id):
            report.documents_skipped += 1
            continue
        doc_report = assign_document_facets(
            session, document, assigner=assigner, settings=settings
        )
        if doc_report.items_faceted or doc_report.facet_rows:
            report.documents_faceted += 1
        else:
            report.documents_skipped += 1
        report.facet_rows += doc_report.facet_rows
        report.rejected.extend(doc_report.rejected)

    jobs = session.exec(select(Job).where(Job.fit_score.is_not(None))).all()  # type: ignore[union-attr]
    for job in jobs:
        if job.id is None:
            continue
        if not force and _job_has_facets(session, job.id):
            report.jobs_skipped += 1
            continue
        job_report = assign_job_facets(session, job, assigner=assigner, settings=settings)
        report.jobs_faceted += 1
        report.facet_rows += job_report.facet_rows
        report.rejected.extend(job_report.rejected)
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from ..db import get_engine, init_db

    parser = argparse.ArgumentParser(description="Backfill KG-02 coverage facets.")
    parser.add_argument(
        "--force", action="store_true", help="re-assign documents/jobs that already have facets"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not facets_available(settings):
        print("No Anthropic API key configured; facet assignment needs one. Nothing done.")
        return 1
    init_db()
    with Session(get_engine()) as session:
        report = backfill_facets(session, settings=settings, force=args.force)
    print(
        f"Facet backfill: {report.documents_faceted} document(s) faceted "
        f"({report.documents_skipped} skipped), {report.jobs_faceted} job(s) faceted "
        f"({report.jobs_skipped} skipped); {report.facet_rows} facet row(s); "
        f"{len(report.rejected)} out-of-vocabulary rejection(s)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
