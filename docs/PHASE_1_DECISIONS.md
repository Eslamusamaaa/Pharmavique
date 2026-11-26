# Phase 1 decisions: chat history

The owner's answers from the grill round on 2026-11-26, before the Phase 1 plan is written. The plan
follows these; they are not asked again.

Phase 1 adds ChatGPT-style conversation history to the assistant. Today nothing is saved: the app keeps
the conversation in memory and sends the last six turns with each question, so a page refresh loses it
(`assistant/domain/conversation.py`: "the server stores nothing").

## What was found in the code first

- There is one assistant with three levels: patient, pharmacist, clinical. The original brief names
  patient, pharmacist, company and a general bot, but no company or general bot exists.
- The level comes from the role chosen on the device (patient → patient, pharmacist → pharmacist,
  company → clinical), not from the account.
- No encryption at rest exists in the code.
- Account deletion exists (`DELETE /v1/auth/me`), so conversations can be deleted with it.

## Decisions

| Topic | Decision |
|---|---|
| Storage | On the server, per account, in a new `assistant` schema on Neon. |
| Which bots | No new bots in Phase 1. One list per account, chosen by the account role. |
| Answer level | Always from the account role, set by the server; the role chosen on the device no longer changes it. |
| Operator accounts | Choose the level themselves; each level has its own list. |
| Encryption | No encryption in the application; Neon's disk encryption is enough for the proof of concept. This overrides the "encrypt at rest" rule in `CLAUDE.md`: record it in an ADR and raise it again before production. |
| Retention | Kept until the user deletes it (one conversation or all); deleted with the account. Deletion is permanent. |
| Cap | 50 conversations per list. At the cap, the oldest unpinned one is deleted automatically. Up to 10 pinned, never deleted automatically. The app warns at 45. |
| Title | Written by the model after the first answer (the free fallback chain). If the model fails, the first question cut to about 40 characters. |
| Voice | Treated exactly like text: the transcript is saved, the audio never. |
| "Compare with my medicines" card | Saved as it was, with its date. |
| Reopening | Saved answers show as they were (citations, trust grade, the answer's date), and the user can continue the conversation. |
| Failed answer | The question is saved with a "try again" button. |
| Extra features | Rename, search in conversations, pin, share by link. |
| UI | A button on the assistant screen opens a side list (new conversation, newest first), and the account page links to the same list. |

## Share links

| Topic | Decision |
|---|---|
| Who can open it | Anyone with the link, no sign-in. |
| Expiry | None; the user can revoke it. |
| Content | A read-only copy taken when shared; sharing again updates the same link. Includes the "compare with my medicines" card as it is. |
| After deletion | Deleting the conversation (by hand or by the 50 cap) ends the link. |

## Next step

Write the Phase 1 plan from these decisions (assumptions, open questions, commits per unit of work)
and wait for the owner's approval before coding.
