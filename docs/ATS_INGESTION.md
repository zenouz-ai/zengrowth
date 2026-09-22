# ATS Ingestion

ZenGrowth ingests roles from **public ATS JSON** only — Greenhouse and Lever.
It does not scrape LinkedIn, Glassdoor, or Indeed. Tavily discovery is optional
and link-only (URLs are stored as references, never fetched).

All examples here use the synthetic slug `example`.

## Sources

| Provider | Client | Public endpoint shape |
|----------|--------|-----------------------|
| Greenhouse | `src/zengrowth/ingestion/ats_greenhouse.py` | `boards.greenhouse.io/<slug>` |
| Lever | `src/zengrowth/ingestion/ats_lever.py` | `jobs.lever.co/<slug>` |

Configure boards as a comma-separated list:

```env
ATS_BOARDS=greenhouse:example,lever:example
```

Finding slugs: `boards.greenhouse.io/<slug>` → `greenhouse:<slug>`;
`jobs.lever.co/<slug>` → `lever:<slug>`.

## Pipeline

1. **Pull** — each configured board is fetched as public JSON.
2. **Dedup** (`dedup.py`) — postings already seen are skipped; stale postings
   beyond `MAX_POSTING_AGE_DAYS` (default 14) are dropped.
3. **Precheck** (`precheck.py`) — when `INGESTION_PRECHECK_ON_RUN=true`, a bounded
   pass (`INGESTION_PRECHECK_BATCH_LIMIT`, default 50) archives obvious
   non-target roles with **no LLM cost**.
4. **Clean & score** — surviving rows are cleaned (`job_summarizer.py`,
   `job_description_extractor.py`) and scored. Auto-ingested rows must clear
   `PIPELINE_MIN_FIT_SCORE` (default 55) to reach the curated board; manually
   added jobs bypass this.

## Scheduling and durability

`src/zengrowth/ingestion/runner.py` + `locking.py`:

- A nightly pull runs at `INGESTION_HOUR` (0–23 local; default 6).
- An advisory lock prevents concurrent runs and self-heals after
  `INGESTION_LOCK_TTL_SECONDS` if a holder crashes.
- `INGESTION_MISFIRE_GRACE_SECONDS` lets a slightly-late cron still fire.
- `INGESTION_CATCHUP_ON_START` runs one ingest on boot if the last completed run
  is stale.

## Failure detection

The one failure the app can't report itself is *silence*. `health.py` addresses
this:

- A run is flagged **stale** once the last *successful* completion is older than
  `INGESTION_STALE_AFTER_HOURS` (default 26). Staleness surfaces on
  `/health/ready` and as a dashboard banner, so a stopped ingest can't masquerade
  as "no new roles".
- After each successful run the runner pings `INGEST_HEARTBEAT_URL` (an external
  dead-man's-switch monitor, e.g. healthchecks.io) when set, so the operator is
  alerted on the *absence* of a signal. Unset = no outbound ping.

## Rate limits and compliance

Only public ATS JSON is read, with retry-skip on stale/duplicate postings. Tavily
discovery, when enabled, prefers ATS/careers hosts (`TAVILY_JOB_DOMAINS`) and
stores result URLs as references only.
