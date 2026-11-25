# ADR-016: email confirmation with a one-time code, and email notifications

Status: accepted, 2026-11-22 (owner, Q-13 and Q-18: sign up with email and password like any site,
then a code sent by email to confirm; notifications by email plus an in-app inbox, with email for what
needs attention; no push).

## Context

Accounts (ADR-009) accepted any address. Nobody proved they owned it, and alerts (ADR-010) were
visible only inside the app, so a withdrawn medicine could be missed.

## Decision

- **Sign-up creates an unconfirmed account and emails a six-digit code; there is no session until it is
  entered** (`POST /v1/auth/register`, then `POST /v1/auth/verify-email`, which returns the first
  session). The code is random (`secrets`), kept only as an HMAC-SHA256 with a key derived from the
  server secret (a leaked table cannot be brute-forced offline: a six-digit code has only a million
  values), valid 10 minutes, allows 5 wrong tries (then locked: 429), is used once, and a new code
  retires the older ones. Sending is limited to one a minute and five an hour per account.
- **Nothing reveals who has an account.** Signing in with a right password before confirming answers
  403 `email_not_verified`; a wrong password still answers the same 401 as an unknown address;
  `POST /v1/auth/resend-code` always answers the same 202; a code for an unknown address is just
  invalid. (Sign-up with an address that is taken still answers 409, as before.)
- **Existing accounts count as confirmed** from their creation (they predate the rule), and the operator
  made by the command starts confirmed (the person at the server console is trusted).
- **An `EmailSender` port** (`shared_kernel/email.py`) with a standard-library **SMTP adapter** (works
  with any provider that offers SMTP: STARTTLS, optional login, credentials only from the environment,
  sent in a worker thread so a slow mail server never blocks a request) and a **console adapter for
  development** that prints the message as UTF-8 and refuses to be built when
  `PHARMAVIQUE_ENVIRONMENT=prod`. The provider and the sender address are the owner's choice (Q-38).
  Header values cannot contain line breaks, and an unsubscribe link must be a single https address.
- **The code email is sent after the response**, so a slow or down mail server cannot delay or fail
  sign-up; any failure is logged without the address or the code, and the person asks for a new code.
- **Notifications:** the in-app inbox stays the alerts of ADR-010. `pharmavique notify-emails` (the daily
  refresh runs it after the relay) sends **one digest per person** of their unread, not yet emailed
  alerts, to confirmed addresses of people who keep **email notifications on** (a switch in the account
  screen, `PUT /v1/auth/me/notifications`). The email says what the registry says changed (price,
  withdrawal, relisting), in Arabic and English, with "not medical advice", no advice and no health data
  beyond the medicines the alerts are about. An alert is marked emailed only after the mail server
  accepted the email, or when the person does not want email; a failed send leaves it for the next run.
  Alerts that existed when this was added are marked emailed, so no backlog is sent.
- **Unsubscribe:** every digest has a signed link (HMAC over the account id, from a different derived
  key) and the standard `List-Unsubscribe` one-click headers. Opening the link asks first; pressing the
  button switches the account's email notifications off. It grants nothing else. The link needs
  `PHARMAVIQUE_PUBLIC_URL` (https); without it the email points to the account screen instead.
- The digest is composed in the composition root from the watchlist (the alerts), the identity
  directory (`UserDirectory`, a published contract that returns addresses only for confirmed accounts)
  and the catalog (names); none of the three imports another.

## Consequences

- Real deployments need an SMTP provider, a verified sending domain (SPF and DKIM for deliverability)
  and `PHARMAVIQUE_PUBLIC_URL`. A free tier's daily cap limits how many people can sign up and be
  notified: that matters for "very many users" and is why the sender is a port.
- Sending runs inside the API process (after the response) and in the digest job. At large scale it
  should move to the job queue of ADR-012; the port makes that a local change.
- Not built: a confirmation step at sign-in on a new device, changing the email address, password
  reset (it needs the same mechanism), and per-alert-type email preferences.
- Checked end to end on the development database on 2026-11-22: sign-up, 403 before confirming, wrong
  code 400, right code 200, a digest for a real product's price change, nothing sent on a second run,
  unsubscribe, deletion. That run found and fixed two faults: the console sender crashed printing
  Arabic on a Windows console, and an unexpected sender error surfaced as a server error.

## Update 2026-11-25: local mail catcher

Development can send real SMTP into Mailpit (`docker compose --profile mail up -d mailpit`, SMTP on
127.0.0.1:1025, mail read at http://127.0.0.1:8025; `.env.example` has the four settings). Nothing leaves
the machine. `tests/integration/test_mail_catcher.py` sends the verification email and an Arabic email
with an unsubscribe header through the real adapter and reads them back; it is skipped when the catcher
is not running. The confirm, resend, lock-out and expiry rules are covered by `tests/unit/identity` and
`tests/unit/bootstrap/test_api_auth.py`.

