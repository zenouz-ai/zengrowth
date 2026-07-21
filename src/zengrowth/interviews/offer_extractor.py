"""LLM-backed offer-term extraction for paste/upload-to-fill (OFF-04).

Offer exchanges arrive as emails and, at the end, a PDF offer letter. This
mirrors the paste-to-fill job extractor: the operator pastes the email (or
uploads the letter, parsed via the knowledge document parsers), the LLM
extracts ``JobOffer``-shaped fields conservatively, and the operator reviews
the prefilled form before anything is saved. The raw text is preserved as
``offer_text`` and is never routed through knowledge extraction.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session

from ..config import Settings, get_settings
from ..observability.client import InstrumentedLLM, build_instrumented_llm

SYSTEM_PROMPT = """You extract structured offer terms from a pasted job-offer email or offer letter.
Return exactly one JSON object and nothing else: no markdown, no code fences, no commentary.
Be conservative. If a term is not explicitly stated in the pasted text, return null rather than guessing.
Never invent figures, dates, or benefits."""

# Uploaded offer letters are parsed to text before extraction; cap what we send.
MAX_EXTRACT_CHARS = 24_000


class _LLMClient(Protocol):
    def extract(self, system: str, user: str, model: str) -> dict[str, Any]: ...


def _date_to_datetime(value: Any) -> Any:
    """Accept YYYY-MM-DD strings from the LLM for datetime fields (noon UTC)."""
    if isinstance(value, str) and len(value.strip()) == 10:
        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError:
            return value
        return datetime(parsed.year, parsed.month, parsed.day, 12, tzinfo=UTC)
    return value


class ExtractedOfferFields(BaseModel):
    """OfferCreate-shaped fields plus extraction confidence metadata."""

    base_salary: float | None = None
    currency: str | None = None
    bonus: str | None = None
    equity: str | None = None
    pension: str | None = None
    holiday_days: int | None = None
    benefits: str | None = None
    other_terms: str | None = None
    start_date: date | None = None
    received_at: datetime | None = None
    deadline_at: datetime | None = None
    offer_text: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    confidence_notes: str | None = None

    @field_validator("received_at", "deadline_at", mode="before")
    @classmethod
    def _accept_dates(cls, value: Any) -> Any:
        return _date_to_datetime(value)


class InstrumentedOfferExtractor:
    def __init__(
        self,
        llm: InstrumentedLLM,
        *,
        session: Session | None = None,
        entity_id: int | None = None,
    ) -> None:
        self._llm = llm
        self._session = session
        self._entity_id = entity_id

    def extract(self, system: str, user: str, model: str) -> dict[str, Any]:
        return self._llm.chat_json(
            system=system,
            user=user,
            model=model,
            max_tokens=1200,
            operation_name="extract_offer_fields",
            session=self._session,
            entity_type="job",
            entity_id=self._entity_id,
        )


def build_extraction_prompt(*, raw_text: str) -> str:
    schema = {
        "base_salary": "number or null; annual base salary as a plain number, no separators",
        "currency": "ISO code string or null, e.g. 'GBP', 'USD'; infer only from an explicit symbol/code",
        "bonus": "string or null, e.g. '15% target, paid annually'",
        "equity": "string or null, e.g. 'RSUs vesting over 4 years' or 'LTIP'",
        "pension": "string or null, e.g. '6% employer match'",
        "holiday_days": "integer or null; annual leave days excluding public holidays when the text distinguishes",
        "benefits": "string or null; healthcare, insurance, wellbeing and similar, comma-separated",
        "other_terms": "string or null; notice period, probation, hybrid/location policy",
        "start_date": "YYYY-MM-DD string or null",
        "received_date": "YYYY-MM-DD string or null; the date the offer was sent, if stated",
        "deadline_date": "YYYY-MM-DD string or null; the respond-by date, if stated",
        "missing_fields": "array of field names that could not be extracted",
        "confidence_notes": "short sentence explaining uncertain fields",
    }
    example = {
        "base_salary": 140000,
        "currency": "GBP",
        "bonus": "15% target bonus",
        "equity": None,
        "pension": "6% employer match",
        "holiday_days": 28,
        "benefits": "Private healthcare, life assurance",
        "other_terms": "3-month notice period; 6-month probation; hybrid 2 days/week London",
        "start_date": "2026-09-01",
        "received_date": "2026-07-10",
        "deadline_date": "2026-07-20",
        "missing_fields": ["equity"],
        "confidence_notes": "All figures were explicit; no equity component was mentioned.",
    }
    return (
        "Extract offer terms for the ZenGrowth offer form from this pasted offer email or letter.\n"
        "Rules:\n"
        "- Extract only terms explicitly stated in the text; keep unknown fields null and list them in missing_fields.\n"
        "- base_salary is the annual base only; bonus/equity go in their own fields.\n"
        "- Keep short verbatim phrasing for free-text fields rather than paraphrasing.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"EXAMPLE OUTPUT:\n{json.dumps(example, indent=2, default=str)}\n\n"
        f"INPUT:\n{json.dumps({'raw_text': raw_text.strip()[:MAX_EXTRACT_CHARS]}, indent=2)}"
    )


def _build_llm(
    settings: Settings, session: Session | None = None, entity_id: int | None = None
) -> _LLMClient:
    return InstrumentedOfferExtractor(
        build_instrumented_llm(settings), session=session, entity_id=entity_id
    )


def extract_offer_fields(
    *,
    raw_text: str,
    client: _LLMClient | None = None,
    settings: Settings | None = None,
    session: Session | None = None,
    entity_id: int | None = None,
) -> ExtractedOfferFields:
    """Extract offer terms from pasted text; the raw text is preserved verbatim."""
    text = raw_text.strip()
    if not text:
        raise ValueError("nothing to extract: paste the offer email or letter text")
    settings = settings or get_settings()
    client = client or _build_llm(settings, session=session, entity_id=entity_id)
    parsed = client.extract(SYSTEM_PROMPT, build_extraction_prompt(raw_text=text), settings.scoring_model)
    # The LLM emits *_date strings; map onto the datetime fields the form uses.
    for llm_key, field in (("received_date", "received_at"), ("deadline_date", "deadline_at")):
        if llm_key in parsed and field not in parsed:
            parsed[field] = parsed.pop(llm_key)
        else:
            parsed.pop(llm_key, None)
    parsed["offer_text"] = text
    try:
        return ExtractedOfferFields.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"offer extraction response invalid: {exc}") from exc
