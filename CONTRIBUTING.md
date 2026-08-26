# Contributing to ZenGrowth

Thanks for your interest. ZenGrowth is a transparent, local-first AI career
operating system. This repository is the **public mirror**; please keep
contributions free of any personal or private data.

## Ground rules

- **No personal data.** Never include real CVs, cover letters, application
  answers, recruiter/contact details, job-pipeline data, target-company lists,
  compensation figures, or anything tied to a real person's job search.
- **No secrets or deployment details.** No API keys, tokens, private domains,
  IPs, host paths, or production runbooks.
- **Synthetic examples only.** Use synthetic candidates (e.g. "Jordan Avery"),
  synthetic roles, and synthetic companies in docs, tests, and fixtures.
- **Claims must match code.** Documentation should describe what the code
  actually does. Every relative link must resolve.

## Development setup

```bash
# Backend
poetry install --with dev
poetry run python -m zengrowth.db init

# Frontend
cd frontend && npm install
```

See [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) for the full local workflow.

## Before opening a PR

Run the full suite (CI runs the same checks):

```bash
poetry run ruff check src tests branding
poetry run pytest
cd frontend && npm run lint && npm run test && npm run build
```

- Make your change on a feature branch.
- Keep PRs focused; update docs when behavior changes.
- Tests use in-memory SQLite and synthetic fixtures — do not add a real database.
- Lint is strict on unused code (Ruff F401/F841, ESLint `no-unused-vars`). Prefix a
  deliberately unused frontend parameter with `_` (e.g. `_pageCount`) — the ESLint
  config ignores that pattern.

## Reporting security issues

Please report security issues privately as described in [`SECURITY.md`](SECURITY.md)
rather than opening a public issue.
