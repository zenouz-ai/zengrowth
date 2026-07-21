# Security Policy

ZenGrowth is designed to be local-first and auditable. We take the security and
privacy of operators seriously.

## Reporting a vulnerability

Please report security issues **privately** to the maintainer rather than
opening a public issue or pull request. Include:

- a description of the issue and its impact,
- steps to reproduce (proof-of-concept if possible),
- any suggested remediation.

We aim to acknowledge reports promptly and will coordinate a fix and disclosure
timeline with you.

## Scope and posture

- **Protected by default.** Every `/api/*` route requires an operator session;
  the app refuses to boot in HTTPS mode without an operator password hash and a
  session secret (fail-closed).
- **Hardened auth.** PBKDF2-SHA256 password hashing, HMAC-signed `httponly` +
  `secure` session cookies, and app-level login backoff.
- **Secrets at rest.** In-app API keys are encrypted with a local keyring.
- **Local-first data.** Generated materials, knowledge originals, and the SQLite
  database stay on disk under gitignored paths. Personal data leaves only on the
  LLM/discovery calls the operator triggers.
- **Anonymous public view.** The `/public` surface exposes only aggregate,
  k-anonymized counts with complementary suppression.

## Please do not

- Commit secrets, `.env` files, real personal data, or generated materials.
- Include private domains, IPs, host paths, or deployment runbooks in issues or
  PRs against this public mirror.
