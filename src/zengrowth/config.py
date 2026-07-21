"""Settings loaded from .env via pydantic-settings.

API keys are intentionally optional at load time so the API and dashboard can
boot without them. Code paths that need a key (scoring, Tavily discovery) call
`require_anthropic_key()` / `require_tavily_key()` and fail loud when missing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource


class _CsvFallbackMixin:
    """pydantic-settings 2.x JSON-parses complex types before validators run;
    CSV strings from .env fail that parse. Overriding decode_complex_value to
    fall back to the raw string lets field_validators handle CSV splitting."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value  # let field_validator handle CSV splitting


class _CsvFriendlyEnvSource(_CsvFallbackMixin, EnvSettingsSource):
    pass


class _CsvFriendlyDotEnvSource(_CsvFallbackMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None
    openai_api_key: str | None = None

    scoring_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"

    database_url: str = "sqlite:///data/zengrowth.db"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    user_target_roles: list[str] = Field(
        default_factory=lambda: [
            "Head of AI",
            "Director of AI",
            "Head of Data Science",
            "Director of Data Science",
            "Lead AI Engineer",
            "AI Strategy Lead",
            "Agentic AI Lead",
            "AI Innovation Lead",
        ]
    )
    user_target_sectors: list[str] = Field(
        default_factory=lambda: [
            "AI",
            "Robotics",
            "Research",
            "FinTech",
            "MedTech",
            "Healthcare",
            "Finance",
            "Government",
            "Big Tech",
        ]
    )
    # Candidate identity printed on generated materials (cover letter header /
    # sign-off). Defaults are neutral synthetic placeholders so no personal data
    # is baked into the source; the operator sets their real values in .env
    # (gitignored) — see .env.example.
    user_full_name: str = "Jordan Avery"
    user_email: str = "jordan.avery@example.com"
    user_phone: str = ""
    user_linkedin: str = ""

    user_location: str = "Remote"
    user_hybrid_max_office_days: int = 3
    # Personal compensation targets are not baked into source; set them in .env.
    user_comp_min_gbp: int = 0
    user_comp_target_gbp: int = 0

    ats_boards: list[str] = Field(
        default_factory=lambda: [
            "greenhouse:anthropic",
            "greenhouse:stripe",
            "lever:netflix",
        ]
    )
    max_posting_age_days: int = 14
    ingestion_hour: int = 6
    ingestion_precheck_on_run: bool = True
    ingestion_precheck_batch_limit: int = 50
    pipeline_min_fit_score: float = 55.0
    # CV tailoring: widen grounding for high-fit jobs (TP-16..TP-20); gates stay on.
    cv_aligned_fit_threshold: float = 70.0
    cv_priority_fit_threshold: float = 75.0
    # Evidence retrieval (RET-01). The generator loads a broad pool of verified
    # claims ordered by confidence, then *relevance-ranks* the pool against the JD
    # and keeps the top `evidence_prompt_limit` for both the prompt and the
    # grounding corpus. Ranking the full pool before the cap is the fix for the
    # recall bug where a highly-relevant but lower-confidence claim was truncated
    # by the confidence cap before relevance was ever considered.
    evidence_candidate_pool: int = 200
    evidence_prompt_limit: int = 40
    # Scheduler durability (EA-04). The advisory lock self-heals after this TTL if
    # a holder crashes; misfire grace lets a slightly-late cron fire still run;
    # catch-up runs one ingest on boot when the last completed run is stale.
    ingestion_lock_ttl_seconds: int = 7200
    ingestion_misfire_grace_seconds: int = 3600
    ingestion_catchup_on_start: bool = True
    # Failure detection (SEC-01/SEC-09). A nightly pipeline is considered "stale"
    # once the last *successful* completion is older than this; readiness and the
    # dashboard banner surface it so a silently-stopped ingest can't masquerade as
    # "no new roles". After each successful run the runner pings
    # ``ingest_heartbeat_url`` (a free external dead-man's-switch monitor, e.g.
    # healthchecks.io) so the operator is alerted on the *absence* of a signal —
    # the one failure the app itself can never report. Unset = no outbound ping.
    ingestion_stale_after_hours: float = 26.0
    ingest_heartbeat_url: str | None = None

    # Cost guard (SEC-08). A soft daily ceiling on summed LLM spend: once today's
    # ``LlmCall.cost_usd`` total reaches this, scoring/material/extraction calls
    # fail closed with 503 until midnight UTC rather than spending unbounded. 0
    # disables the cap (default) so nothing changes until an operator opts in.
    llm_daily_budget_usd: float = 0.0

    # Interview prep packs (INT-02). Company/interviewer research uses Anthropic's
    # server-side web_search tool on the same instrumented call — one vendor, cost
    # in LlmCall, citations returned inline. When disabled (or the account lacks
    # the tool) packs are generated from stored context only and say so.
    interview_research_web_search: bool = True
    interview_research_max_searches: int = 5
    interview_pack_max_tokens: int = 6000

    # Login brute-force backoff (SEC-04). Defence-in-depth behind the nginx edge
    # limiter: after this many failed logins from one client within the window the
    # operator login locks out (429) for the window. Generous by default so normal
    # use never trips it; the real throttle is the edge. 0 disables the app guard.
    login_max_attempts: int = 10
    login_lockout_seconds: int = 300

    # Tavily discovery: prefer ATS and careers hosts when searching for applyable roles.
    tavily_job_domains: list[str] = Field(
        default_factory=lambda: [
            "boards.greenhouse.io",
            "jobs.lever.co",
            "jobs.ashbyhq.com",
            "myworkdayjobs.com",
            "linkedin.com",
            "smartrecruiters.com",
            "icims.com",
            "workable.com",
            "bamboohr.com",
            "teamtailor.com",
            "greenhouse.io",
            "lever.co",
        ]
    )

    # Operator auth + edge hardening. Defaults are dev-safe: with require_https
    # off the auth gate falls back to a localhost bypass so local dev and the
    # test suite run without a configured operator. Production sets
    # ZENGROWTH_REQUIRE_HTTPS=true, which makes the fail-closed lifespan demand
    # a password hash + session secret before the app will boot.
    zengrowth_operator_password_hash: str | None = None
    zengrowth_session_secret: str | None = None
    zengrowth_require_https: bool = False
    zengrowth_session_ttl_seconds: int = 28_800  # 8 hours

    # Feature flags. Disabled features degrade to 503 rather than 500.
    feature_public_observability: bool = True
    feature_sse: bool = True
    feature_observability: bool = True

    # Optional JSON overrides for per-model token pricing (USD per 1M tokens).
    llm_price_overrides: dict[str, Any] | None = None
    telemetry_retention_days: int = 90

    knowledge_root: str = "data/knowledge"
    knowledge_auto_verify_threshold: float = 0.75
    # Chunk embeddings are computed on ingest only when this is on. They are
    # currently *not* read by any retrieval path (RET-01 / RAG-eval audit): the
    # generator selects evidence by JD relevance over verified claims, not by
    # vector similarity. Left off by default so we don't pay the OpenAI embedding
    # bill for an unqueried index; flip on (with OPENAI_API_KEY) when a semantic
    # or hybrid retriever is built that actually consumes them.
    knowledge_embeddings_enabled: bool = False
    materials_retention_days: int = 30
    # Prefix for exported CV/cover-letter filenames, e.g. Jordan_Avery_CV_Northwind_v1.pdf.
    # Neutral synthetic default; operators set MATERIALS_EXPORT_NAME in .env.
    materials_export_name: str = "Jordan_Avery"

    @field_validator("user_target_roles", "user_target_sectors", "ats_boards", "tavily_job_domains", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (
            init_settings,
            _CsvFriendlyEnvSource(settings_cls),
            _CsvFriendlyDotEnvSource(settings_cls),
            file_secret_settings,
        )

    def require_anthropic_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for scoring. "
                "Set it in .env and restart the service."
            )
        return self.anthropic_api_key

    def require_tavily_key(self) -> str:
        if not self.tavily_api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is required for discovery search. "
                "Set it in .env and restart the service."
            )
        return self.tavily_api_key

    def require_openai_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for knowledge embeddings. "
                "Set it in .env and restart the service."
            )
        return self.openai_api_key

    def require_operator_auth(self) -> tuple[str, str]:
        """Return (password_hash, session_secret) or fail loud if either is unset.

        Called by the fail-closed lifespan when ZENGROWTH_REQUIRE_HTTPS is on so
        a production deployment never boots an unprotected operator surface.
        """
        missing = [
            name
            for name, value in (
                ("ZENGROWTH_OPERATOR_PASSWORD_HASH", self.zengrowth_operator_password_hash),
                ("ZENGROWTH_SESSION_SECRET", self.zengrowth_session_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Operator auth is required when ZENGROWTH_REQUIRE_HTTPS is set, but "
                f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} unset. "
                "Set them in .env and restart the service."
            )
        return self.zengrowth_operator_password_hash, self.zengrowth_session_secret  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
