"""Orchestrates ATS pulls across the configured boards.

run_all() is idempotent: re-running with no new postings inserts nothing.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx
from sqlmodel import Session, select

from ..audit import log_action
from ..config import get_settings
from ..db import get_engine
from ..models import ActorType, Job
from ..observability.tracing import annotate_pipeline_run, pipeline_run, tool_step
from .ats_greenhouse import fetch_greenhouse
from .ats_lever import fetch_lever
from .locking import scheduler_lock
from .precheck import precheck_jobs

INGEST_LOCK_NAME = "nightly_ingest"


@dataclass
class IngestionResult:
    added: int = 0
    skipped_duplicate: int = 0
    skipped_stale: int = 0
    prechecked: int = 0
    archived: int = 0
    failed_precheck: int = 0
    failed_boards: list[str] = field(default_factory=list)
    succeeded_boards: list[str] = field(default_factory=list)
    # Boards that fetched successfully but parsed *zero* rows. A previously
    # populated board returning 0 is the silent schema-drift / outage signal
    # (SEC-01 / EA-08): "succeeded, 0 added" otherwise looks like "no new roles".
    zero_row_boards: list[str] = field(default_factory=list)
    # True when another ingest already held the advisory lock (EA-04): this call
    # did nothing rather than run a concurrent, double-spending pass.
    skipped_locked: bool = False


def _too_old(posting_date: date | None, max_age_days: int) -> bool:
    if max_age_days <= 0 or posting_date is None:
        return False
    return (date.today() - posting_date) > timedelta(days=max_age_days)


def _store_jobs(session: Session, jobs: list[Job], max_age_days: int, result: IngestionResult) -> None:
    for job in jobs:
        if _too_old(job.posting_date, max_age_days):
            result.skipped_stale += 1
            continue
        existing = session.exec(
            select(Job).where(Job.dedup_hash == job.dedup_hash)
        ).first()
        if existing is not None:
            result.skipped_duplicate += 1
            continue
        session.add(job)
        session.commit()
        session.refresh(job)
        result.added += 1
        log_action(
            session,
            actor=ActorType.system,
            action="ingest_job",
            entity_type="job",
            entity_id=job.id,
            detail={"source": job.source.value, "company": job.company, "title": job.title},
        )


def run_all(*, session: Session | None = None, use_lock: bool = True) -> IngestionResult:
    settings = get_settings()
    result = IngestionResult()
    own_session = session is None
    if own_session:
        session = Session(get_engine())
    engine = session.get_bind()
    lock = (
        scheduler_lock(engine, INGEST_LOCK_NAME, ttl_seconds=settings.ingestion_lock_ttl_seconds)
        if use_lock
        else nullcontext(True)
    )
    try:
        with lock as acquired:
            if not acquired:
                # Another ingest (cron, manual trigger, or another replica) holds
                # the lock — skip rather than run a concurrent double-spend (EA-04).
                result.skipped_locked = True
                return result
            _run_all_body(session, settings, result)
    finally:
        if own_session:
            session.close()
    return result


def _run_all_body(session: Session, settings, result: IngestionResult) -> None:
    with pipeline_run(session, pipeline_type="ingestion", detail={"boards": settings.ats_boards}):
        with httpx.Client(timeout=30.0) as client:
            for entry in settings.ats_boards:
                if ":" not in entry:
                    result.failed_boards.append(entry)
                    continue
                provider, slug = entry.split(":", 1)
                provider = provider.strip().lower()
                slug = slug.strip()
                if not slug:
                    result.failed_boards.append(entry)
                    continue
                try:
                    with tool_step(
                        session,
                        step_name=f"fetch_{provider}:{slug}",
                        step_type="tool",
                        detail={"provider": provider, "slug": slug},
                    ):
                        if provider == "greenhouse":
                            jobs = fetch_greenhouse(slug, client=client)
                        elif provider == "lever":
                            jobs = fetch_lever(slug, client=client)
                        else:
                            result.failed_boards.append(entry)
                            continue
                except (httpx.HTTPError, ValueError):
                    result.failed_boards.append(entry)
                    continue
                with tool_step(
                    session,
                    step_name="store_jobs",
                    step_type="db",
                    detail={"board": entry, "fetched": len(jobs)},
                ):
                    _store_jobs(session, jobs, settings.max_posting_age_days, result)
                result.succeeded_boards.append(entry)
                if not jobs:
                    # Fetched cleanly but parsed nothing — the schema-drift / outage
                    # tell the readiness banner surfaces (SEC-01).
                    result.zero_row_boards.append(entry)
        if settings.ingestion_precheck_on_run:
            with tool_step(session, step_name="precheck_batch", step_type="decision"):
                precheck_result = precheck_jobs(
                    session,
                    limit=settings.ingestion_precheck_batch_limit,
                    settings=settings,
                )
            result.prechecked = precheck_result.prechecked
            result.archived = precheck_result.archived
            result.failed_precheck = precheck_result.failed
        # Stamp the outcome onto the run row so readiness/banner can read "what
        # happened last night" (SEC-01/SEC-09), then fire the dead-man's-switch
        # heartbeat now that a full pass has completed without raising.
        annotate_pipeline_run(
            session,
            result={
                "added": result.added,
                "skipped_duplicate": result.skipped_duplicate,
                "skipped_stale": result.skipped_stale,
                "prechecked": result.prechecked,
                "archived": result.archived,
                "succeeded_boards": result.succeeded_boards,
                "failed_boards": result.failed_boards,
                "zero_row_boards": result.zero_row_boards,
            },
        )
    # Local import avoids a runner<->health import cycle (health reads
    # INGEST_LOCK_NAME defined below the runner imports).
    from .health import send_ingest_heartbeat

    send_ingest_heartbeat(settings, result)
