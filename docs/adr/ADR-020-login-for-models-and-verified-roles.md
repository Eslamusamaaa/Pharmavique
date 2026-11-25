# ADR-020: an account for the model routes, a strong signing secret, verified professional roles

Status: accepted, 2026-11-25 (owner's answers to the Phase 0 questions). Amends ADR-009.

## Context

ADR-009 left the assistant, the scans and voice open to anyone. Each of those calls a model with a free
quota (Groq, OpenRouter, Cloudflare Workers AI) that one busy guest can use up for everyone, and the
per-address rate limit is weak behind shared mobile networks. The access-token signing secret was optional:
without it the API started anyway with accounts switched off, and nothing checked its length. Pharmacist
and company roles were self-declared (ADR-009), so nothing could tell a real pharmacist from anyone else.

## Decision

- **Public**: search, drug pages, alternatives, compare, similar names, shortages, pictures, pharmacies,
  ingredients, the interaction check of drugs typed in, contraindications, the sources page, `/health`,
  `/metrics` (counts and timings only), and the account endpoints themselves.
- **Any signed-in account**: the assistant, box and prescription scans, voice (transcribe, speak, drug name)
  and their background jobs, through the `signed_in_for_ai` dependency, behind the feature flag
  `PHARMAVIQUE_FEATURE_LOGIN_FOR_AI` (on). Personal data routes already needed an account.
  `GET /v1/voice/audio/{key}` (one-time link for an audio element) and `GET /v1/jobs/{id}` (long random
  ticket) stay open.
- **Every route is classified** in `tests/unit/bootstrap/test_api_login_required.py`; a new route fails
  the test until someone decides whether it needs an account.
- The website shows a guest a Saudi-dialect "sign in first" screen on the assistant, scan and voice
  screens; after signing in (or verifying a new account) it goes back to the same screen.
- **Signing secret**: in `prod` the API refuses to start without `PHARMAVIQUE_JWT_SECRET` or with one
  shorter than 32 characters; in `dev` and `test` it logs a warning and carries on.
- **Verified roles**: pharmacist and company sign-up stays open, but the account is `unverified` until an
  operator verifies or rejects it (operator screen, or `pharmavique verify-account`); the person gets an
  email. An unverified account keeps every screen of its role; only the "verified" badge (and, later,
  verified company pages) wait for verification.

## Consequences

- A guest can still look everything up but must sign up to use a model, which keeps the free quotas for
  real users and gives the rate limit a person to count instead of an address.
- Switching `PHARMAVIQUE_FEATURE_LOGIN_FOR_AI` off restores the old behaviour without a deploy.
- A missing or short secret now stops a production deploy instead of silently switching accounts off.
- Verification is a manual operator step; nothing checks a pharmacist licence automatically.
