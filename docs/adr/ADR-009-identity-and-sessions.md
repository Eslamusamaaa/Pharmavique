# ADR-009: accounts, roles and sessions in the `identity` context

Status: accepted, 2026-11-21 (owner asked for accounts and permissions; the defaults of open questions
Q-13 and Q-14 were approved with the Phase 3 plan).

## Context

Search, drug pages and the assistant work without an account. Saved medicines, allergies, alerts, shelf
lists and the company and operator views need to know who is calling, keep one person's data apart from
another's, and let a person leave and delete everything. The data is sensitive (medicines, allergies),
so the design collects the least it can.

## Decision

- **Own accounts** in the `identity` context, schema `identity`, tables `users` and `refresh_tokens`.
  Email and password; phone sign-in is a later addition because it needs an SMS provider and a cost.
- **Roles** are `patient`, `pharmacist`, `company` and `operator`. A user has one role. Pharmacists and
  companies get a **tenant id** at sign-up (their pharmacy or company); patients and operators have none.
  The database enforces both rules with CHECK constraints.
- **The role is what the person says they are.** It is not verified, so it chooses which screens and saved
  data they get; it never grants access to another tenant's data. Verification of pharmacists and
  companies is a later, human step. The `operator` role cannot be picked at sign-up: `pharmavique
  create-operator --email ...` makes it on the server, with the password read from a prompt or the
  environment, never from the command line.
- **Passwords** use scrypt from the standard library (N=2^15, r=8, p=1, 16-byte salt), stored as
  `scrypt$n$r$p$salt$hash` so the cost can rise later. Hashing runs in a worker thread. Minimum 10
  characters. A wrong email and a wrong password give the same answer and take the same time (a dummy
  hash is checked for an unknown email).
- **Access tokens** are JWT (HS256) lasting 15 minutes, signed with `PHARMAVIQUE_JWT_SECRET` (at least 32
  characters). They hold the user id, role and tenant only. Other contexts check them with no database
  call (`identity.contracts.TokenVerifier` gives a `Principal`).
- **Refresh tokens** are random, stored only as a SHA-256 hash, valid 30 days, used once and replaced on
  every refresh. A used token that comes back is a replay: every session of that user ends. This is the
  revocation design Q-13 asked for: a stolen refresh token works until its owner next refreshes, and an
  access token for at most 15 minutes.
- **Deleting an account** deletes the user and their refresh tokens (`ON DELETE CASCADE`); contexts that
  keep user-owned data delete it on the `UserDeleted` event once the outbox relay exists (Wave C).
- **Row-level security** (Q-14 default) is added with the first tenant-owned tables, because there is
  nothing to isolate before them. Each such table gets a repository filter and an isolation test that
  fails if one tenant can read another's rows.
- The router lives in the composition root (`bootstrap/api_auth.py`) like the other routers; `require_roles`
  is the guard other routers use.
- The mobile app keeps the refresh token in the device's secure storage (Keychain or Keystore) and the
  access token in memory.

## Consequences

- Login and sign-up share the "heavy" per-client rate limit, which slows password guessing; a lockout per
  account is not built.
- Roles are self-declared, so a company view must not show anything beyond public registry data until
  verification exists.
- The signing secret is one shared key: rotating it signs everyone out (access tokens only; refresh
  tokens are unaffected). Moving to asymmetric keys is possible behind `AccessTokens`.
- Legal review of health and location data (Q-9) must happen before real users sign up.
