# ADR-010: the outbox relay, the watchlist and alerts

Status: accepted, 2026-11-21 (owner asked for alerts, allergies in "my medicines" and a "price changed"
mark; Q-18 default: in-app list first, push later behind a port).

## Context

`catalog` has always written its integration events (`ProductAdded`, `ProductWithdrawn`, `PriceChanged`,
...) to an outbox table in the same transaction as the change, but nothing read them. Alerts need a
reader, and the people who saved a medicine need somewhere to keep that list, their allergies and the
alerts about them. That data is sensitive and belongs to one person each.

## Decision

- **A relay** (`foundation/events/relay.py`) carries events from an outbox to subscribers. The catalog's
  adapter (`SqlAlchemyOutboxPublisher`) claims a batch with `FOR UPDATE SKIP LOCKED`, calls every
  subscriber for every event in order, and marks the batch published in the same transaction. If any
  subscriber fails nothing is marked and the error propagates, so delivery is **at least once**.
  Two relays can run at once. `pharmavique outbox-relay` runs it (a loop, or `--once`); the daily
  refresh calls `--once` after loading the drugs.
- **Subscribers are idempotent.** The watchlist keeps one alert per person and event (`UNIQUE (user_id,
  event_id)`), so a re-delivered event adds nothing.
- **The relay hands subscribers a `StoredEvent`** (envelope plus plain JSON payload, in the shared
  kernel), not the catalog's classes. The wiring that maps event types to handlers lives in the
  composition root, so `watchlist` imports nothing from `catalog`.
- **`watchlist` context**, schema `watchlist`: `saved_medicines`, `allergies`, `alerts`. Alerts are made
  for price changes, withdrawals and relistings of a saved medicine. Shortage and safety-notice alerts
  are not built: the list loader does not emit events yet (planned: a `ListItemLinked` event).
- **Row-level security** is on and forced for the three tables. A transaction sees only rows whose
  `user_id` equals its `app.user_id` setting; event handlers set `app.system` instead; with neither set,
  nothing is visible. The repository sets the setting on every call, so a query that forgot its own
  filter still cannot read another person's rows. Isolation is tested at the database as an ordinary
  role. **Superusers and `BYPASSRLS` roles skip row-level security**, and the development database
  user is a superuser, so production must connect as an ordinary role (documented in the migration).
- **Allergies are by active ingredient name**, picked from the catalog's own list, matched on the
  normalized name or the same substance plus a salt or ester word. Class allergies (penicillin to
  amoxicillin) are not covered because no clinical source is available; every answer says so, and "no
  match" is never a clearance.
- **Deleting an account** calls `WatchlistService.forget` first, then deletes the identity rows. (An
  event would be cleaner, but account deletion must not depend on a relay being up.)
- **"Price changed"** comes from our own price snapshots: the drug page shows the last change between two
  different recorded prices, and nothing before two prices exist.
- **The digest** (`GET /v1/me/digest`) is built from the person's alerts with a fixed template; no model
  writes it and nothing is added to the facts.

## Consequences

- Alerts only appear after the relay has run, so they lag a refresh by at most one relay round.
- The saved list is the first server-side health data; the existing on-device "my medicines" basket for
  interaction checks is unchanged and still never leaves the phone. Legal review (Q-9) must happen
  before real users save medicines or allergies.
- Push notifications (Q-18) need a `NotificationSender` port and a provider; alerts are readable in the
  app until then.
