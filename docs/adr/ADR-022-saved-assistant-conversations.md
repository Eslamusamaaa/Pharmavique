# ADR-022: saved assistant conversations

Status: accepted, 2026-11-26 (owner's answers in `docs/PHASE_1_DECISIONS.md`). Amends the "server
stores nothing" rule of the assistant's conversation memory.

## Context

The assistant kept no conversation: the app held it in memory and sent the last six turns with each
question, so a page refresh lost it, and nothing was shared across devices. The owner asked for
ChatGPT-style history: a list of conversations, reopened and continued, searched, pinned and shared.

## Decision

- **Stored on the server, per account,** in a new `assistant` schema (`assistant_0001`): `conversations`
  and `messages`, every row with its `user_id` and row-level security forced, as in `watchlist`. A
  share link is read by its token with `app.system` on; nothing else is.
- **One list per account, one level per list.** The answer level now comes from the account role on
  the server (patient → patient, pharmacist → pharmacist, company → clinical); the role chosen on the
  device no longer changes it. An operator chooses the level, and each level is its own list.
- **A question is saved before the model answers** (`pending`). A failure leaves it `failed` and the app
  offers "try again"; asking the same question again in that conversation replaces it. The earlier
  turns the model sees are read from storage, not taken from the app, and still cut to the last six.
- **An answer is saved as it was shown:** text, citations with trust grades, flags and the "compare
  with my medicines" card, so reopening shows the same thing, with the answer's date and a line that
  the registry may have changed since.
- **Limits:** 50 conversations per list; at the cap the oldest unpinned one is deleted to make room
  (the app warns at 45). Up to 10 pinned, never deleted to make room. 100 questions per conversation.
- **Title:** cut from the first question, then replaced by a model-written one through a separate call
  the app makes after the first answer (never slowing the answer; Vercel may stop work after a
  response). A renamed conversation keeps the person's title.
- **Share links:** anyone with the link, no sign-in, no expiry, revocable. The link shows a copy taken
  when it was shared (sharing again updates the same link), including the medicines card. Deleting the
  conversation ends the link. The public read sends `X-Robots-Tag: noindex, nofollow`.
- **Deleted with the account**, and permanently when the person deletes one or all.
- **Storage trouble never stops an answer:** if saving fails (for example before the migration ran)
  the question is answered and not saved.
- **Flag:** `PHARMAVIQUE_FEATURE_CHAT_HISTORY` (on by default) hides the routes and stops saving.

## Encryption at rest

`CLAUDE.md` asks that health data be encrypted at rest. For the proof of concept the owner decided
that Neon's disk encryption is enough and the application does not encrypt conversation text
(2026-11-26). Anyone with database access can read the conversations. **This must be decided again
before production**: application-level encryption (AES-GCM with a key outside the database) would
also need a search that does not read the plain text.

## Consequences

- The conversation text, which may describe a person's health, now lives in the database. Retention is
  up to the person (no automatic expiry beyond the cap), and share links make a copy public by
  design. Both follow the owner's decisions and are listed here so they are revisited with production.
- Production needs the `Database migrate` workflow to create the `assistant` schema before the list
  works; until then answers still work and are not saved.
- Search is a `LIKE` over normalized text, enough for 50 conversations per list. A larger history would
  need an index (trigram) or a different design.
