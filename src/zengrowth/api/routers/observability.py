"""Observability API: LLM telemetry, pipeline traces, datasource governance, performance."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlmodel import Session, select

from ...config import get_settings
from ...db import get_session
from ...models import (
    DataSource,
    EvidenceClaim,
    KnowledgeEntity,
    LlmCall,
    LlmCallStatus,
    PerformanceSnapshot,
    PipelineRun,
    PipelineStep,
    SourceDocument,
)
from ...observability.datasources import sync_datasources

router = APIRouter(prefix="/observability", tags=["observability"])


def _require_observability() -> None:
    if not get_settings().feature_observability:
        raise HTTPException(status_code=503, detail="observability is disabled")


def _period_start(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct))
    return float(ordered[idx])


@router.get("/summary")
def observability_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_observability()
    sync_datasources(session)
    now = datetime.now(UTC)
    windows = {"today": now - timedelta(days=1), "7d": _period_start(7), "30d": _period_start(30)}
    result: dict[str, Any] = {}
    for label, since in windows.items():
        calls = list(session.exec(select(LlmCall).where(LlmCall.timestamp >= since)))
        ok_calls = [c for c in calls if c.status == LlmCallStatus.ok]
        total_cost = sum(c.cost_usd for c in calls)
        total_tokens = sum(c.input_tokens + c.output_tokens for c in calls)
        latencies = [c.latency_ms for c in ok_calls if c.latency_ms]
        error_rate = (len(calls) - len(ok_calls)) / len(calls) if calls else 0.0
        result[label] = {
            "call_count": len(calls),
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            "error_rate": round(error_rate, 4),
        }
    return result


@router.get("/calls")
def list_llm_calls(
    limit: int = 100,
    offset: int = 0,
    operation_name: str | None = None,
    model: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> list[LlmCall]:
    _require_observability()
    stmt = select(LlmCall).order_by(LlmCall.timestamp.desc())  # type: ignore[union-attr]
    if operation_name:
        stmt = stmt.where(LlmCall.operation_name == operation_name)
    if model:
        stmt = stmt.where(LlmCall.request_model == model)
    if status:
        stmt = stmt.where(LlmCall.status == status)
    stmt = stmt.offset(offset).limit(limit)
    return list(session.exec(stmt))


@router.get("/costs")
def cost_timeseries(
    days: int = 30,
    group_by: str = "day",
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _require_observability()
    since = _period_start(days)
    calls = list(session.exec(select(LlmCall).where(LlmCall.timestamp >= since)))
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0, "calls": 0})
    for call in calls:
        if group_by == "model":
            key = call.request_model
        elif group_by == "operation":
            key = call.operation_name
        else:
            key = call.timestamp.date().isoformat()
        buckets[key]["cost_usd"] += call.cost_usd
        buckets[key]["tokens"] += call.input_tokens + call.output_tokens
        buckets[key]["calls"] += 1
        buckets[key]["key"] = key
    return sorted(buckets.values(), key=lambda row: row["key"])


@router.get("/latency")
def latency_by_operation(
    days: int = 30,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _require_observability()
    since = _period_start(days)
    calls = list(
        session.exec(
            select(LlmCall).where(LlmCall.timestamp >= since, LlmCall.status == LlmCallStatus.ok)
        )
    )
    grouped: dict[str, list[int]] = defaultdict(list)
    for call in calls:
        grouped[call.operation_name].append(call.latency_ms)
    rows = []
    for operation, latencies in grouped.items():
        rows.append(
            {
                "operation_name": operation,
                "count": len(latencies),
                "p50_ms": _percentile(latencies, 0.5),
                "p95_ms": _percentile(latencies, 0.95),
                "p99_ms": _percentile(latencies, 0.99),
                "avg_ms": round(sum(latencies) / len(latencies), 1),
            }
        )
    return sorted(rows, key=lambda row: row["count"], reverse=True)


@router.get("/runs")
def list_pipeline_runs(
    limit: int = 50,
    pipeline_type: str | None = None,
    session: Session = Depends(get_session),
) -> list[PipelineRun]:
    _require_observability()
    stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc())  # type: ignore[union-attr]
    if pipeline_type:
        stmt = stmt.where(PipelineRun.pipeline_type == pipeline_type)
    stmt = stmt.limit(limit)
    return list(session.exec(stmt))


@router.get("/runs/{trace_id}")
def get_pipeline_run(trace_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_observability()
    run = session.exec(select(PipelineRun).where(PipelineRun.trace_id == trace_id)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    steps = list(
        session.exec(
            select(PipelineStep)
            .where(PipelineStep.trace_id == trace_id)
            .order_by(PipelineStep.started_at)  # type: ignore[union-attr]
        )
    )
    return {"run": run, "steps": steps}


@router.get("/datasources")
def list_datasources(session: Session = Depends(get_session)) -> list[DataSource]:
    _require_observability()
    sync_datasources(session)
    return list(session.exec(select(DataSource).order_by(DataSource.name)))  # type: ignore[union-attr]


@router.get("/datasources/{source_id}")
def get_datasource(source_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_observability()
    sync_datasources(session)
    source = session.get(DataSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="datasource not found")
    lineage: dict[str, Any] = {"documents": [], "claims": 0, "entities": 0}
    if source.kind.value == "file":
        docs = list(session.exec(select(SourceDocument).limit(20)))
        lineage["documents"] = [{"id": d.id, "filename": d.filename, "status": d.status.value} for d in docs]
        lineage["claims"] = session.exec(select(func.count()).select_from(EvidenceClaim)).one()
        lineage["entities"] = session.exec(select(func.count()).select_from(KnowledgeEntity)).one()
    recent_calls = list(
        session.exec(
            select(LlmCall)
            .where(LlmCall.provider == source.name)
            .order_by(LlmCall.timestamp.desc())  # type: ignore[union-attr]
            .limit(10)
        )
    )
    return {"source": source, "lineage": lineage, "recent_calls": recent_calls}


@router.get("/storage")
def storage_metrics(session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_observability()
    settings = get_settings()
    table_counts: dict[str, int] = {}
    for table in (
        "job",
        "sourcedocument",
        "sourcechunk",
        "evidenceclaim",
        "knowledgeentity",
        "knowledgerelationship",
        "generatedmaterial",
        "auditlog",
        "llmcall",
        "pipelinerun",
        "pipelinestep",
        "datasource",
    ):
        try:
            count = session.exec(text(f"SELECT COUNT(*) FROM {table}")).one()
            table_counts[table] = int(count)
        except Exception:
            table_counts[table] = 0

    db_path = settings.database_url.replace("sqlite:///", "")
    db_size = Path(db_path).stat().st_size if db_path and Path(db_path).exists() else 0
    materials_size = _dir_size(Path("data/materials"))
    knowledge_size = _dir_size(Path(settings.knowledge_root))

    return {
        "table_counts": table_counts,
        "sqlite_bytes": db_size,
        "materials_bytes": materials_size,
        "knowledge_bytes": knowledge_size,
        "telemetry_retention_days": settings.telemetry_retention_days,
        "materials_retention_days": settings.materials_retention_days,
    }


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


@router.get("/performance")
def performance_scorecards(
    days: int = 30,
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _require_observability()
    since = _period_start(days)
    calls = list(session.exec(select(LlmCall).where(LlmCall.timestamp >= since)))
    grouped: dict[str, list[LlmCall]] = defaultdict(list)
    for call in calls:
        grouped[call.operation_name].append(call)

    scorecards: list[dict[str, Any]] = []
    for operation, rows in grouped.items():
        ok = [r for r in rows if r.status == LlmCallStatus.ok]
        latencies = [r.latency_ms for r in ok]
        costs = [r.cost_usd for r in ok]
        scorecards.append(
            {
                "operation_name": operation,
                "call_count": len(rows),
                "success_rate": round(len(ok) / len(rows), 4) if rows else 0.0,
                "latency_p50_ms": _percentile(latencies, 0.5),
                "latency_p95_ms": _percentile(latencies, 0.95),
                "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else 0.0,
                "total_cost_usd": round(sum(costs), 4),
            }
        )
    return sorted(scorecards, key=lambda row: row["call_count"], reverse=True)


@router.post("/performance/snapshot")
def snapshot_performance(session: Session = Depends(get_session)) -> dict[str, Any]:
    _require_observability()
    today = date.today()
    cards = performance_scorecards(days=1, session=session)
    created = 0
    for card in cards:
        snap = PerformanceSnapshot(
            snapshot_date=today,
            operation_name=card["operation_name"],
            call_count=card["call_count"],
            success_rate=card["success_rate"],
            latency_p50_ms=card["latency_p50_ms"],
            latency_p95_ms=card["latency_p95_ms"],
            avg_cost_usd=card["avg_cost_usd"],
            detail=card,
        )
        session.add(snap)
        created += 1
    session.commit()
    return {"snapshots_created": created, "date": today.isoformat()}


@router.post("/retention/purge")
def purge_old_telemetry(session: Session = Depends(get_session)) -> dict[str, int]:
    _require_observability()
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=settings.telemetry_retention_days)
    llm_deleted = 0
    for call in session.exec(select(LlmCall).where(LlmCall.timestamp < cutoff)):
        session.delete(call)
        llm_deleted += 1
    run_deleted = 0
    for run in session.exec(select(PipelineRun).where(PipelineRun.started_at < cutoff)):
        for step in session.exec(select(PipelineStep).where(PipelineStep.trace_id == run.trace_id)):
            session.delete(step)
        session.delete(run)
        run_deleted += 1
    session.commit()
    return {"llm_calls_deleted": llm_deleted, "pipeline_runs_deleted": run_deleted}
