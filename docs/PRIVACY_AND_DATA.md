# Privacy and Data

ZenGrowth is local-first by design. Your career data is yours and stays on your
machine. This document describes the data boundaries and what must never be
committed.

## Local-first storage

- The canonical store is **local SQLite** (`DATABASE_URL`, default
  `sqlite:///data/zengrowth.db`).
- Generated materials, knowledge originals, and processed chunks live on **local
  disk** under `data/` (and `KNOWLEDGE_ROOT`, default `data/knowledge`).
- API keys entered in-app are **encrypted at rest** with a local keyring
  (`data/.keyring`).

All of these paths are gitignored.

## What leaves the machine, and when

Personal data leaves only on calls the operator deliberately triggers:

| Trigger | Destination | Data sent |
|---------|-------------|-----------|
| Scoring / materials | Anthropic (Claude) | Job description + your relevant CV/evidence text |
| Discovery ("Find jobs") | Tavily | Your search query (link-only results) |
| Embeddings (off by default) | OpenAI | Knowledge chunks, only if explicitly enabled |

Nothing is sold or shared. Discovery results are stored as URL references and
never fetched.

## Access boundaries

- Every `/api/*` route (except the aggregate public view) requires an operator
  session.
- In production (`ZENGROWTH_REQUIRE_HTTPS=true`) the app fails closed: it will not
  boot without an operator password hash and session secret.
- The `/public` surface exposes only aggregate, **k-anonymized** counts with
  complementary suppression, so a hidden cell cannot be recovered by differencing
  (`src/zengrowth/api/kanon.py`).

## What never gets committed

The `.gitignore` excludes — and the public mirror never ships — the following:

- `.env` and any `.env.*` (except `.env.example`)
- SQLite databases and `*-wal` / `*-shm` files
- `data/`, `logs/`, `runs/`, `journals/`, `audit_logs/`, `exports/`, `downloads/`
- Generated CVs, resumes, cover letters, and application answers
- Browser/session state including `storage_state.json`
- Notebook checkpoints and executed-output artifacts
- Local credentials/secrets directories

## Public mirror guarantee

The public mirror (`zenouz-ai/zengrowth`) is produced by an allowlisted,
sanitized export and contains no personal job-search data, contacts, pipeline
data, or deployment secrets. See [PUBLIC_REPO_SCOPE.md](PUBLIC_REPO_SCOPE.md).
