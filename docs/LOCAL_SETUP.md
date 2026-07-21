# Local Setup

ZenGrowth runs local-first. This guide covers a Poetry + Vite dev loop and a
container path. All values are placeholders — never commit a real `.env`.

## Prerequisites

- Python ≥ 3.11 and [Poetry](https://python-poetry.org/)
- Node 20.19+ or 22.12+ (for the dashboard)
- A Claude (Anthropic) API key
- For PDF material generation: a LaTeX toolchain (`latexmk`, `texlive-latex-extra`).
  The provided `Dockerfile` installs this for you.

## 1. Configure environment

```bash
cp .env.example .env
```

Fill in at least `ANTHROPIC_API_KEY`. Everything else has a working default. In
dev, leave `ZENGROWTH_REQUIRE_HTTPS=false`; the auth gate then falls back to a
localhost bypass so you can run without configuring an operator. You can also
connect your Claude key later in the dashboard setup wizard.

Keys you may set:

- `ANTHROPIC_API_KEY` — required for scoring, summaries, materials, extraction.
- `TAVILY_API_KEY` — optional; only for the "Find jobs" discovery search.
- `OPENAI_API_KEY` — optional; only if `KNOWLEDGE_EMBEDDINGS_ENABLED=true` (off by
  default; embeddings are not read by any retrieval path yet).

## 2. Backend

```bash
poetry install --with dev
poetry run python -m zengrowth.db init          # create SQLite schema
poetry run uvicorn zengrowth.api.main:app --reload   # API on :8000
```

The database is created at `data/zengrowth.db` (`DATABASE_URL`), gitignored.

## 3. Dashboard

In a second terminal:

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

Vite proxies `/api` and `/health` to the API on `:8000` (see
`frontend/vite.config.ts`).

## 4. Container path (optional)

```bash
docker compose up --build
```

This builds and runs the **API only**, published on `127.0.0.1:8000`. Run the
dashboard with `npm run dev` as above. Production reverse proxy, TLS, and real
domains are intentionally not part of this mirror.

## 5. Your first five minutes (walkthrough)

With the API on `:8000` and the dashboard on `:3000`, do this in order:

1. **Open** http://localhost:3000. In dev (no `ZENGROWTH_REQUIRE_HTTPS`) you are
   not prompted to log in — the dashboard renders immediately.
2. **Connect your Claude key** in the Setup wizard. It is validated with a cheap
   1-token ping and stored encrypted under `data/.keyring`. Do this **before**
   the next steps — scoring, summarization, and knowledge extraction all need it.
3. **Add your first job** on *Add Job*: paste a job description and submit. Manual
   entry creates the row immediately; "Prepare application" then cleans and scores
   it (this is the first step that spends LLM tokens).
4. **Upload your first documents** on *Knowledge*: drop in a CV or project
   write-up. Upload stores the file and then extracts verified facts — which
   requires the Claude key from step 2, so connect the key first. Approve facts
   in the review queue; they become the evidence bank that grounds materials.

> Order matters: connect the key (step 2) before uploading documents (step 4) or
> the extraction step returns a clear 503 asking for the key.

## 6. Validation

```bash
poetry run ruff check src tests branding
poetry run pytest
cd frontend && npm run lint && npm run test && npm run build
```

CI runs the same commands on every push and PR.

> **Note on type checking:** mypy is not configured as a blocking gate in this
> repo. The required quality gates are ruff, pytest, and the frontend
> lint/test/build. If you add type checking locally, expect a baseline of
> pre-existing findings.

## Finding ATS slugs

`boards.greenhouse.io/<slug>` → `greenhouse:<slug>`;
`jobs.lever.co/<slug>` → `lever:<slug>`. Set a comma-separated list as
`ATS_BOARDS`, e.g. `greenhouse:example,lever:example`. See
[ATS_INGESTION.md](ATS_INGESTION.md).
