# Public Repo Scope

ZenGrowth is developed in a **private canonical repository** and published here
as a **curated public mirror** (`zenouz-ai/zengrowth`). The mirror is produced
by an allowlisted, sanitized export — not a direct flip of the private repo.

This document states exactly what the public mirror includes and what it omits,
and why.

## Included

| Path / class | Notes |
|--------------|-------|
| `src/` | The full backend engine: ingestion, scoring, expected value, materials, interviews, knowledge, observability, auth, API. |
| `tests/` | Backend test suite. Uses in-memory SQLite and synthetic fixtures only. |
| `frontend/` | React/Vite dashboard source, config, and tests (no `node_modules`/`dist`; no production Dockerfile). |
| `branding/` | Logos and the asset generator. No personal data. |
| `templates/cv.tex` | Synthetic placeholder CV template. |
| `pyproject.toml`, `poetry.lock` | Python packaging and lockfile. |
| `Dockerfile`, `docker-compose.yml` | Local-first images only (no production proxy/TLS/host mounts). |
| `.github/workflows/ci.yml`, `.github/PULL_REQUEST_TEMPLATE.md` | CI and PR scaffolding with no secrets. |
| `.env.example` | Placeholders only. |
| `LICENSE`, `README.md`, `CONTRIBUTING.md`, `SECURITY.md` | Project meta. |
| `docs/` (this set) | Sanitized public documentation. |
| `papers/arxiv/`, `output/pdf/` | Working-paper source, aggregate-only measurement tool, and rendered preprint; no underlying personal data. |

## Omitted (private only)

| Class | Examples |
|-------|----------|
| AI assistant / operator context | `AGENTS.md`, `CLAUDE.md`, the public-repo playbook, the export tooling itself. |
| Runtime data | `data/`, `*.db`, `*.sqlite`, WAL/SHM files, caches. |
| Logs & audit exports | `logs/`, `runs/`, `journals/`, `audit_logs/`, `exports/`, `downloads/`. |
| Generated materials | CV variants, cover letters, application answers. |
| Personal career inputs | Master CV, source-of-truth notes, project write-ups, compensation targets. |
| Job pipeline data | Role shortlists, saved/rejected roles, company targets, interview statuses. |
| Contacts | Recruiter names/emails, referrals, hiring-manager notes. |
| Browser/session state | Playwright `storage_state.json`, cookies, downloaded pages. |
| Deployment / ops | VPS/nginx/TLS runbooks, real domains, IPs, host paths, backup scripts, prod compose/Dockerfiles. |
| Internal docs | Product vision, detailed spec, eval harness, audits, viability analyses. |
| Notebooks | Any notebook with executed output or real data. |

## How the export is produced (in the private repo)

The private repo holds `public-export/` and `scripts/publish_public_mirror.py`:

1. **Allowlist** (`manifest.txt`) — only listed paths are eligible.
2. **Denylist** (`denylist.txt`) — drops anything sensitive on top of the allowlist.
3. **Replacements** (`replacements/`) — sanitized variants of README, config, build
   files, and docs are overlaid.
4. **Content scrub** (`content-scrub.txt`) — rewrites any residual private identifiers
   to synthetic equivalents.
5. **Required check** (`required.txt`) — fails if a required public file is missing.
6. **Scans** — the exported tree is scanned for forbidden content
   (`forbidden-content.txt`) and secret patterns (`secret-patterns.txt`); git history
   can also be scanned for secret patterns.

The mirror is published as a fresh tree with no inherited git history.

## Synthetic test fixtures

Two files under `docs/career/processed/` — `cv_source.tex` and
`source_of_truth.md` — are present in the mirror as **fully synthetic fixtures**
for the fictional candidate "Jordan Avery". The material-generation test suite
needs a structure-preserving CV template and a verified evidence bank to ground
against. These contain no real personal data; the operator's real career inputs
at these paths are private and never published.

## Data hygiene

The mirror never ships a real SQLite database. Tests run against in-memory SQLite
and synthetic fixtures. If a demo database is ever needed, it must be a synthetic
fixture, not a sanitized copy of real job-search data.
