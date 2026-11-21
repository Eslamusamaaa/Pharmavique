# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's private reporting:
**Security → Report a vulnerability** on this repository. You will get an answer as soon as the
owner can read it.

## What this repository must never contain

- Secrets: API keys, tokens, passwords, certificates. Real values live only in `.env`, which is
  git-ignored; `.env.example` holds placeholders. GitHub secret scanning with push protection is on.
- Health data of real people: prescription photos, personal medicine lists, audio. Uploads are
  processed in memory and are not stored or logged.

## How the project protects itself

- `main` cannot be force-pushed or deleted; every push runs lint, types, architecture contracts
  and tests in CI (`.github/workflows/ci.yml`, read-only token, third-party actions pinned to a
  commit).
- Dependabot alerts and security updates are on: it opens a pull request only when a dependency has a known vulnerability (routine version-bump pull requests are off on purpose).
- The API limits requests per client (a lower limit for the assistant, voice and scan endpoints),
  caps upload sizes, restricts browser origins (CORS) and answers a model-provider limit with a
  retryable 429 instead of an error.
- Database and Redis ports in `docker-compose.yml` are bound to `127.0.0.1` only; the API
  container runs as a non-root user.
- Outbound crawlers identify themselves, honour `robots.txt`, throttle, and stop on a block.

## Known limits

The API has no user sign-in yet (the app's role choice only changes wording and suggestions), so
it must not be exposed to the public internet without a gateway that authenticates callers.
