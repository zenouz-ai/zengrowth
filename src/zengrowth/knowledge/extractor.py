"""LLM extraction of claims, entities, and relationships from knowledge chunks."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlmodel import Session

from ..config import Settings, get_settings
from ..observability.client import InstrumentedLLM, build_instrumented_llm

SYSTEM_PROMPT = """You extract a career evidence graph from user-provided CVs, project notes, and documents.
Return exactly one JSON object and nothing else. Extract only claims supported by the source text. Every claim must include a short direct source_span copied or tightly paraphrased from the text."""


class ExtractedClaim(BaseModel):
    claim_text: str
    category: str = "general"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_span: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [tag.strip() for tag in value.split(",") if tag.strip()]
        return value


class ExtractedEntity(BaseModel):
    name: str
    entity_type: str = "entity"


class ExtractedRelationship(BaseModel):
    source: str
    target: str
    relationship_type: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


class KnowledgeExtractionClient(Protocol):
    def extract(self, *, text: str, metadata: dict[str, object], model: str) -> ExtractionResult: ...


class InstrumentedKnowledgeExtractor:
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

    def extract(self, *, text: str, metadata: dict[str, object], model: str) -> ExtractionResult:
        raw = self._llm.chat_json(
            system=SYSTEM_PROMPT,
            user=build_extraction_prompt(text, metadata),
            model=model,
            max_tokens=4000,
            operation_name="extract_knowledge",
            session=self._session,
            entity_type="source_document",
            entity_id=self._entity_id,
        )
        try:
            return ExtractionResult.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"knowledge extraction response invalid: {exc}") from exc


def build_extraction_prompt(text: str, metadata: dict[str, object]) -> str:
    schema = {
        "claims": [
            {
                "claim_text": "specific factual career/application claim",
                "category": "leadership|technical|delivery|domain|education|recognition|general",
                "confidence": "0.0-1.0 confidence in source support",
                "source_span": "short supporting source span",
                "tags": ["optional", "tags"],
            }
        ],
        "entities": [{"name": "entity name", "entity_type": "person|employer|project|skill|tool|role|domain"}],
        "relationships": [
            {
                "source": "entity name",
                "target": "entity name",
                "relationship_type": "WORKED_ON|USED|LED|DELIVERED|RELATED_TO",
                "confidence": "0.0-1.0",
            }
        ],
    }
    return (
        "Extract career evidence for a job-application knowledge graph.\n"
        "Prefer concise, reusable claims. Do not invent dates, employers, metrics, tools, or qualifications.\n\n"
        "Limits: return at most 6 claims, 10 entities, and 8 relationships for this chunk.\n"
        "If the chunk contains more evidence, choose the strongest facts with direct source spans.\n\n"
        f"OUTPUT SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"METADATA:\n{json.dumps(metadata, indent=2, default=str)}\n\n"
        f"SOURCE TEXT:\n{text[:4500]}"
    )


def build_default_extractor(
    settings: Settings | None = None,
    *,
    session: Session | None = None,
    entity_id: int | None = None,
) -> KnowledgeExtractionClient:
    settings = settings or get_settings()
    return InstrumentedKnowledgeExtractor(
        build_instrumented_llm(settings),
        session=session,
        entity_id=entity_id,
    )
