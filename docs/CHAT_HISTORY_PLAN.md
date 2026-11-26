# Chat history plan (Phase 1 of the trust plan)

Built from `docs/PHASE_1_DECISIONS.md`. The owner said to start implementing on 2026-11-26.

## Units of work (one commit each)

1. **Domain and storage.** In the `assistant` context: a conversation (level, title, pinned, share
   link) and its messages; the limits (50 per list, 10 pinned, the oldest unpinned one deleted at the
   cap); a `ConversationStore` port; a Postgres adapter under row-level security like `watchlist`; the
   migration `assistant_0001` (schema `assistant`, reversible).
2. **Saving from the ask route.** A signed-in question is saved in a conversation (a new one when no
   `conversation_id` is sent). The server reads the earlier turns from storage instead of trusting the
   app. The level comes from the account role (operator: the level it sends). A failed answer leaves the
   question marked failed; asking it again replaces it. Behind the flag `chat_history`.
3. **Conversation routes.** List (pinned first, then newest; search), read one, rename, pin, delete
   one, delete all, model-written title, share and revoke, and the public read of a shared copy.
   Account deletion deletes the conversations.
4. **App.** The list beside the assistant (new conversation, search, rename, pin, share, delete,
   delete all, a warning at 45), the account page link, reopening a conversation with the answers'
   dates, the "try again" button, and the public shared page.
5. **Docs.** ADR-022 (chat history, the encryption decision for the proof of concept), README, runbook.

## Assumptions (the owner may change them)

- **A conversation holds at most 100 questions;** after that the app asks for a new conversation.
  The decisions set no number, and a cap keeps one conversation from filling the database.
- The model still gets only the last six turns (three questions and answers), as today: the free
  models' tokens per minute are limited.
- **The title is written by a second, separate call** that the app makes after the first answer is on
  the screen, so the answer is never slower. On Vercel work after the answer is sent can be cut off.
- Only signed-in questions are saved. With `login_for_ai` switched off, guest questions are answered
  and not saved.
- Background jobs (`/v1/jobs`, unused by the app) do not save conversations.
- Search matches the title, the questions and the answers, after the same Arabic normalization as the
  drug search (diacritics, alef and ya forms, digits).
- A share link is a random 22-character token. The public read answers with `X-Robots-Tag: noindex`.
