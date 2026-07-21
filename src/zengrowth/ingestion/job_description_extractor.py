"""LLM-backed job-description extraction for paste-to-fill intake."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import Settings, get_settings
from ..observability.client import InstrumentedLLM, build_instrumented_llm

SYSTEM_PROMPT = """You extract structured job fields from pasted job descriptions.
Return exactly one JSON object and nothing else: no markdown, no code fences, no commentary.
Be conservative. If a field is not explicitly supported by the pasted text, return null or an empty object rather than guessing."""


class _LLMClient(Protocol):
    def extract(self, system: str, user: str, model: str) -> dict[str, Any]: ...


class ExtractedJobFields(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    hybrid_policy: str | None = None
    compensation: dict[str, Any] | None = None
    seniority: str | None = None
    application_url: str | None = None
    posting_date: date | None = None
    description: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    confidence_notes: str | None = None

    @field_validator("compensation", mode="before")
    @classmethod
    def _compensation_must_be_object(cls, value: Any) -> Any:
        if value in ("", None):
            return None
        if not isinstance(value, dict):
            raise ValueError("compensation must be a JSON object or null")
        return value


class InstrumentedJobExtractor:
    def __init__(self, llm: InstrumentedLLM) -> None:
        self._llm = llm

    def extract(self, system: str, user: str, model: str) -> dict[str, Any]:
        return self._llm.chat_json(
            system=system,
            user=user,
            model=model,
            max_tokens=1200,
            operation_name="extract_job_fields",
        )


def build_extraction_prompt(*, raw_text: str, application_url: str | None = None) -> str:
    schema = {
        "company": "string or null",
        "title": "string or null",
        "location": "string or null",
        "hybrid_policy": "string or null, e.g. '2 days/week London' or 'remote'",
        "compensation": "object or null; use keys like base_gbp, min_gbp, max_gbp, currency, equity, bonus, notes",
        "seniority": "string or null",
        "application_url": "string or null; use provided URL if relevant",
        "posting_date": "YYYY-MM-DD string or null",
        "missing_fields": "array of field names that could not be extracted",
        "confidence_notes": "short sentence explaining uncertain fields",
    }
    example = {
        "company": "Acme AI",
        "title": "Director of AI",
        "location": "London",
        "hybrid_policy": "2 days/week in London",
        "compensation": {"min_gbp": 130000, "max_gbp": 160000, "notes": "plus bonus"},
        "seniority": "Director",
        "application_url": application_url,
        "posting_date": None,
        "missing_fields": ["posting_date"],
        "confidence_notes": "Compensation range and hybrid policy were explicit; posting date was not present.",
    }
    context = {"application_url": application_url, "raw_text": raw_text.strip()}
    return (
        "Extract fields for the ZenGrowth JobCreate form from this pasted job description.\n"
        "Rules:\n"
        "- Do not fetch or infer from the URL; it is reference context only.\n"
        "- Do not include a description field in your response; the server preserves the pasted text separately.\n"
        "- Normalize UK salary figures to GBP keys when explicitly stated.\n"
        "- Keep unknown fields null and list them in missing_fields.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"EXAMPLE OUTPUT:\n{json.dumps(example, indent=2, default=str)}\n\n"
        f"INPUT:\n{json.dumps(context, indent=2)}"
    )


def _build_llm(settings: Settings) -> _LLMClient:
    return InstrumentedJobExtractor(build_instrumented_llm(settings))


def extract_job_fields(
    *,
    raw_text: str,
    application_url: str | None = None,
    client: _LLMClient | None = None,
    settings: Settings | None = None,
) -> ExtractedJobFields:
    settings = settings or get_settings()
    client = client or _build_llm(settings)
    user_prompt = build_extraction_prompt(raw_text=raw_text, application_url=application_url)
    parsed = client.extract(SYSTEM_PROMPT, user_prompt, settings.scoring_model)
    if application_url and not parsed.get("application_url"):
        parsed["application_url"] = application_url
    parsed["description"] = raw_text.strip()
    try:
        return ExtractedJobFields.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"extraction response invalid: {exc}") from exc
