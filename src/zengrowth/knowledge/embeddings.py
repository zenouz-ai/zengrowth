"""Embedding clients for knowledge chunks."""

from __future__ import annotations

from typing import Protocol

from sqlmodel import Session

from ..config import Settings, get_settings
from ..observability.client import InstrumentedLLM, build_instrumented_llm


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class InstrumentedEmbeddingClient:
    def __init__(
        self,
        llm: InstrumentedLLM,
        *,
        model: str,
        session: Session | None = None,
        entity_id: int | None = None,
    ) -> None:
        self._llm = llm
        self._model = model
        self._session = session
        self._entity_id = entity_id

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._llm.embed(
            texts,
            model=self._model,
            operation_name="embed_chunks",
            session=self._session,
            entity_type="source_document",
            entity_id=self._entity_id,
        )


def build_default_embedder(
    settings: Settings | None = None,
    *,
    session: Session | None = None,
    entity_id: int | None = None,
) -> EmbeddingClient:
    settings = settings or get_settings()
    return InstrumentedEmbeddingClient(
        build_instrumented_llm(settings),
        model=settings.embedding_model,
        session=session,
        entity_id=entity_id,
    )
