"""FastAPI surface for ZenGrowth.

Routes live in per-domain routers under ``zengrowth.api.routers`` and are mounted
under the ``/api`` prefix; ``/health`` stays unprefixed as the liveness probe.

  GET  /health                    -> liveness probe (always unprefixed)
  POST /api/auth/login|logout      -> operator session (signed cookie)
  GET  /api/auth/session           -> session check
  GET  /api/jobs                  -> list jobs, optionally filtered by state
  POST /api/jobs                  -> manual entry (dedup-aware)
  POST /api/jobs/extract          -> paste-to-fill job field extraction
  PATCH /api/jobs/{id}            -> partial job update (e.g. application_url)
  POST /api/jobs/purge            -> permanently delete jobs by lifecycle state
  DELETE /api/jobs/{id}           -> permanently delete one job and its materials
  GET  /api/jobs/{id}             -> full detail incl. rationale + audit
  POST /api/jobs/{id}/summarize   -> clean raw job text into concise summary
  POST /api/jobs/{id}/score       -> trigger a single-agent scoring call
  POST /api/jobs/{id}/state       -> human state change
  POST /api/jobs/{id}/materials/* -> generate CV, cover letter, answers
  GET/POST /api/jobs/{id}/interviews      -> interview timeline (INT-01)
  PATCH/DELETE /api/jobs/{id}/interviews/{iid} -> edit/remove a round
  PUT  /api/jobs/{id}/interviews/{iid}/transcript -> paste transcript/notes
  POST /api/jobs/{id}/materials/import    -> file an existing pack (backdatable)
  POST /api/jobs/{id}/materials/pack      -> generate a prep pack (web research)
  POST /api/jobs/{id}/interviews/{iid}/debrief -> transcript -> structured debrief
  POST /api/jobs/{id}/materials/email-draft    -> reply/follow-up draft (never sent)
  POST /api/ingestion/run         -> trigger an ATS pull, return summary
  GET  /api/ingestion/config      -> configured ATS/discovery settings
  POST /api/discovery/search      -> Tavily search (returns links only)
  GET  /api/discovery/searches    -> recent Tavily searches with stored hits
  GET  /api/audit                 -> recent audit entries
  GET  /api/events/stream         -> SSE audit stream (operator-gated)
  POST /api/knowledge/*           -> ingest/review user knowledge sources
  GET  /api/observability/*       -> LLM cost/latency, traces, governance
  GET  /api/public/*              -> anonymous, redacted observability surface
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..db import init_db
from ..observability.budget import BudgetExceededError
from ..scheduler import start_scheduler, stop_scheduler
from .login_throttle import LoginThrottle
from .middleware import AuthGateMiddleware
from .routers import (
    audit,
    auth,
    discovery,
    events,
    health,
    ingestion,
    interviews,
    jobs,
    knowledge,
    observability,
    offers,
    public,
)
from .routers import (
    settings as settings_router,
)

logger = logging.getLogger(__name__)

# Operator-gated domain routers, all mounted under the /api prefix.
_API_ROUTERS = (
    jobs.router,
    interviews.router,
    offers.router,
    ingestion.router,
    discovery.router,
    audit.router,
    events.router,
    knowledge.router,
    observability.router,
    settings_router.router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Fail closed: a production surface (HTTPS enforced) must not boot without a
    # configured operator. In dev we warn and continue so local runs are frictionless.
    if settings.zengrowth_require_https:
        settings.require_operator_auth()
    elif not (settings.zengrowth_operator_password_hash and settings.zengrowth_session_secret):
        logger.warning(
            "Operator auth is not configured; the /api surface relies on the "
            "localhost dev bypass. Set ZENGROWTH_REQUIRE_HTTPS=true in production."
        )
    init_db()
    # Load any dashboard-saved API keys (PS-P1) so they survive a restart. Env
    # values take precedence; this only fills what env left unset.
    _load_stored_secrets(settings)
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def _load_stored_secrets(settings) -> None:
    from sqlmodel import Session

    from ..db import get_engine
    from ..secrets_store import load_secrets_into_settings

    try:
        with Session(get_engine()) as session:
            loaded = load_secrets_into_settings(session, settings)
        if loaded:
            logger.info("Loaded stored API key(s) for: %s", ", ".join(loaded))
    except Exception:  # pragma: no cover - never block boot on secret loading
        logger.warning("Could not load stored API keys", exc_info=True)


def create_app() -> FastAPI:
    """Build a fully-configured FastAPI instance."""
    app = FastAPI(title="ZenGrowth", version="0.1.0", lifespan=lifespan)
    app.add_middleware(AuthGateMiddleware)

    # Per-app login brute-force backoff (SEC-04). One instance per app keeps the
    # counter isolated (and test clients independent); the nginx edge stays the
    # primary limiter.
    _settings = get_settings()
    app.state.login_throttle = LoginThrottle(
        max_attempts=_settings.login_max_attempts,
        lockout_seconds=_settings.login_lockout_seconds,
    )

    @app.exception_handler(BudgetExceededError)
    async def _budget_exceeded(_request: Request, exc: BudgetExceededError) -> JSONResponse:
        # SEC-08: a tripped daily spend ceiling fails closed as 503, not 500, with
        # the operator-facing reason so the dashboard can explain the pause.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # /health stays unprefixed: it is the load-balancer probe and an auth allowlist entry.
    app.include_router(health.router)
    # Auth + public surfaces are allowlisted in the gate middleware.
    app.include_router(auth.router, prefix="/api")
    app.include_router(public.router, prefix="/api")

    for router in _API_ROUTERS:
        app.include_router(router, prefix="/api")

    return app


app = create_app()
