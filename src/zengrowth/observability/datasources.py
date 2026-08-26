"""Datasource registry seeding and health sync."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from ..config import get_settings
from ..models import DataSource, DataSourceHealth, DataSourceKind, LlmCall, SourceDocument


def _upsert(
    session: Session,
    *,
    name: str,
    kind: DataSourceKind,
    config: dict | None = None,
    pii_flag: bool = False,
    retention_days: int | None = None,
    notes: str | None = None,
) -> DataSource:
    existing = session.exec(select(DataSource).where(DataSource.name == name)).first()
    now = datetime.now(UTC)
    if existing is None:
        row = DataSource(
            name=name,
            kind=kind,
            config=config,
            pii_flag=pii_flag,
            retention_days=retention_days,
            notes=notes,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    existing.kind = kind
    existing.config = config or existing.config
    existing.pii_flag = pii_flag
    existing.retention_days = retention_days or existing.retention_days
    existing.notes = notes or existing.notes
    existing.updated_at = now
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


def sync_datasources(session: Session) -> None:
    """Ensure configured external sources are registered and update usage stats."""
    settings = get_settings()

    anthropic = _upsert(
        session,
        name="anthropic",
        kind=DataSourceKind.llm,
        config={"model": settings.scoring_model},
        pii_flag=True,
        notes="Claude scoring, extraction, summarization, materials, knowledge",
    )
    # Only register the embedding datasource when embeddings are actually enabled
    # (RET-01 / RAG-eval audit): the chunk vectors are not read by any retrieval
    # path, so by default we neither compute them nor surface them on the
    # governance dashboard. Re-registers automatically if the flag is turned on.
    openai = (
        _upsert(
            session,
            name="openai",
            kind=DataSourceKind.embedding,
            config={"model": settings.embedding_model},
            notes="Knowledge chunk embeddings",
        )
        if settings.knowledge_embeddings_enabled
        else None
    )
    _upsert(
        session,
        name="tavily",
        kind=DataSourceKind.search,
        config={},
        notes="Job discovery search",
    )
    for board in settings.ats_boards:
        _upsert(
            session,
            name=f"ats:{board}",
            kind=DataSourceKind.ats,
            config={"board": board},
            notes="ATS ingestion feed",
        )
    _upsert(
        session,
        name="knowledge_files",
        kind=DataSourceKind.file,
        config={"root": settings.knowledge_root},
        pii_flag=True,
        retention_days=None,
        notes="Uploaded career documents",
    )

    doc_count = len(list(session.exec(select(SourceDocument))))
    knowledge_files = session.exec(select(DataSource).where(DataSource.name == "knowledge_files")).first()
    if knowledge_files:
        knowledge_files.record_count = doc_count
        knowledge_files.health_status = DataSourceHealth.healthy if doc_count >= 0 else DataSourceHealth.unknown
        session.add(knowledge_files)

    for provider_row in (anthropic, openai):
        if provider_row is None:
            continue
        last_call = session.exec(
            select(LlmCall)
            .where(LlmCall.provider == provider_row.name)
            .order_by(LlmCall.timestamp.desc())  # type: ignore[union-attr]
        ).first()
        if last_call:
            provider_row.last_used_at = last_call.timestamp
            provider_row.health_status = (
                DataSourceHealth.healthy if last_call.status.value == "ok" else DataSourceHealth.degraded
            )
            session.add(provider_row)
        elif settings.anthropic_api_key if provider_row.name == "anthropic" else settings.openai_api_key:
            provider_row.health_status = DataSourceHealth.unknown
            session.add(provider_row)
        else:
            provider_row.health_status = DataSourceHealth.unavailable
            provider_row.enabled = False
            session.add(provider_row)

    if not settings.knowledge_embeddings_enabled:
        # Disable (don't delete — preserve history) a stale embedding datasource
        # left over from when embeddings were enabled, so it drops off the dashboard.
        stale_openai = session.exec(select(DataSource).where(DataSource.name == "openai")).first()
        if stale_openai and stale_openai.enabled:
            stale_openai.health_status = DataSourceHealth.unavailable
            stale_openai.enabled = False
            session.add(stale_openai)

    tavily_row = session.exec(select(DataSource).where(DataSource.name == "tavily")).first()
    if tavily_row:
        tavily_row.health_status = (
            DataSourceHealth.healthy if settings.tavily_api_key else DataSourceHealth.unavailable
        )
        tavily_row.enabled = bool(settings.tavily_api_key)
        session.add(tavily_row)

    session.commit()
