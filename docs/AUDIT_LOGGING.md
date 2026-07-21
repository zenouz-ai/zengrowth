# Audit Logging

ZenGrowth is built to support audit. Instrumented workflow events — including
ingest, score, generate, and edit paths — stream to the dashboard. This creates
evidence for reconstruction after the fact, while log completeness remains an
explicit evaluation target rather than an assumed property.

## What is logged

`src/zengrowth/audit.py` records events for:

- **Ingestion** — pulls, dedupe outcomes, precheck archive decisions, run
  completion/staleness.
- **Scoring** — each scored role, its per-dimension scores, and rationale.
- **Materials** — generation, revision, versioning, and final-marking (employer
  CVs/cover letters/answers).
- **Interview workflow** — round create/update/delete, transcript paste, prep-pack
  generation (with web-search citations), debriefs, email drafts, artifact import,
  promote-learning into the fact queue, and simulator-prompt composition.
- **Knowledge** — source import, fact extraction, approve/reject decisions.
- **Auth/ops** — login outcomes and feature-flag-gated degradations (where
  applicable).

LLM telemetry (`src/zengrowth/observability/`) additionally records per-call
input/output tokens, cost, latency, and model for each Anthropic call.

## Where it lives

All audit and telemetry rows live in the local SQLite database alongside
application data — there is no external logging service. The audit feed is
exposed to the operator dashboard over Server-Sent Events (`/api/events`, gated
by `FEATURE_SSE`).

## Cost guard

`observability/budget.py` enforces a soft daily ceiling: once today's summed
`cost_usd` reaches `LLM_DAILY_BUDGET_USD` (default 0 = off), scoring, material,
and extraction calls fail closed with HTTP 503 until midnight UTC — so a runaway
loop can't spend unbounded.

## Retention

- LLM telemetry: `TELEMETRY_RETENTION_DAYS` (default 90).
- Generated materials: `MATERIALS_RETENTION_DAYS` (default 30).

## Privacy note

Audit rows can reference job and material details, so the audit log is part of the
local, private dataset. It is **never** exported to the public mirror. See
[PRIVACY_AND_DATA.md](PRIVACY_AND_DATA.md).
