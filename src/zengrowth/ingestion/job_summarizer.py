"""Clean raw pasted/ingested job descriptions into concise display summaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..models import ActorType, Job
from ..observability.client import InstrumentedLLM, build_instrumented_llm

SYSTEM_PROMPT = """You clean messy copied job descriptions for a career dashboard.
Return exactly one JSON object and nothing else. Remove browser chrome, cookie banners, sign-in links, duplicate headings, and EEO boilerplate unless it changes application requirements."""


class _SummaryClient(Protocol):
    def summarize(self, system: str, user: str, model: str) -> dict[str, Any]: ...


class JobSummary(BaseModel):
    role_overview: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    company_domain: str | None = None
    location_hybrid: str | None = None
    compensation: str | None = None
    application_notes: list[str] = Field(default_factory=list)
    noise_removed: list[str] = Field(default_factory=list)

    @field_validator("responsibilities", "requirements", "application_notes", "noise_removed", mode="before")
    @classmethod
    def _coerce_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value


class InstrumentedSummaryClient:
    def __init__(self, llm: InstrumentedLLM, *, session: Session | None = None, entity_id: int | None = None) -> None:
        self._llm = llm
        self._session = session
        self._entity_id = entity_id

    def summarize(self, system: str, user: str, model: str) -> dict[str, Any]:
        return self._llm.chat_json(
            system=system,
            user=user,
            model=model,
            max_tokens=1400,
            operation_name="summarize_job",
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
        )


def build_summary_prompt(job: Job) -> str:
    schema = {
        "role_overview": "2 concise sentences about the actual role",
        "responsibilities": "3-6 concise bullets",
        "requirements": "3-6 concise bullets",
        "company_domain": "company/domain summary or null",
        "location_hybrid": "location and work pattern or null",
        "compensation": "compensation statement or null",
        "application_notes": "application deadlines, requisition id, caveats",
        "noise_removed": "examples of irrelevant copied text removed",
    }
    payload = {
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "hybrid_policy": job.hybrid_policy,
        "compensation": job.compensation,
        "application_url": job.application_url,
        "raw_description": (job.description or "")[:12000],
    }
    return (
        "Summarize this job for a candidate deciding whether to apply.\n"
        "Keep only relevant job content. Do not invent missing salary, hybrid, or requirements.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"JOB:\n{json.dumps(payload, indent=2, default=str)}"
    )


def _build_client(settings: Settings, session: Session | None = None, entity_id: int | None = None) -> _SummaryClient:
    return InstrumentedSummaryClient(build_instrumented_llm(settings), session=session, entity_id=entity_id)


def summarize_job(
    session: Session,
    job: Job,
    *,
    client: _SummaryClient | None = None,
    settings: Settings | None = None,
) -> Job:
    settings = settings or get_settings()
    client = client or _build_client(settings, session=session, entity_id=job.id)
    parsed = client.summarize(SYSTEM_PROMPT, build_summary_prompt(job), settings.scoring_model)
    try:
        summary = JobSummary.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"job summary response invalid: {exc}") from exc
    job.job_summary = summary.model_dump()
    job.summary_updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    log_action(
        session,
        actor=ActorType.agent,
        action="summarize_job",
        entity_type="job",
        entity_id=job.id,
        detail={"model": settings.scoring_model, "summary_keys": list(job.job_summary or {})},
    )
    return job
