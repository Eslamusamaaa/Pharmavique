# ADR-023: choosing a new password with an emailed code

Status: accepted, 2026-11-26 (owner: a person who forgot the password gets a code by email, then may
choose a new one). Builds on ADR-016, which listed password reset as not built.

## Context

Sign-up confirms the address with a one-time code (ADR-016), but a person who forgot the password had
no way back into the account. The same mechanism proves who owns the address, so it can prove it here.

## Decision

- **Two steps, no new secret.** `POST /v1/auth/forgot-password` emails a six-digit code; `POST
  /v1/auth/reset-password` takes the email, the code and the new password, sets it, and signs the person
  in. The code has the same rules as the sign-up code: random, kept only as a keyed hash, valid 10
  minutes, five wrong tries then locked (429), used once, one a minute and five an hour per account
  (counting both kinds), the email sent before the answer.
- **Each code has a purpose** (`verify` or `reset`, `email_codes.purpose`, migration `identity_0004`).
  The purpose is also part of the keyed hash, so a sign-up code can never reset a password and a reset
  code can never confirm an address. A new code retires only the earlier codes of its own purpose, so
  asking to reset does not kill a sign-up code still in the inbox. Codes that existed become `verify`.
- **Nothing reveals who has an account.** `forgot-password` always answers the same 202, for an address
  with no account, a malformed one, a request that is too soon and one that was sent. `reset-password`
  answers 400 for any code that is wrong, expired, used or for an unknown address.
- **The new password follows the sign-up rules** (10 to 256 characters, not the email) and is checked
  before the code is spent, so a weak choice (422) can be fixed with the same code.
- **Every earlier session ends** when the password changes (all refresh tokens are revoked), so anyone
  who knew the old password is signed out; the person is signed in with a fresh session.
- **A code that reached the inbox also proves the address**, so an account that never confirmed its
  email counts as confirmed after a reset.
- A pharmacist or company account keeps its review status: a reset does not make anyone verified.

## Consequences

- The app has a "forgot password" link on the sign-in screen and a two-step screen
  (`mobile/src/app/forgot-password.tsx`).
- The migration only adds a column with a default and rebuilds one index, and old code keeps working on
  the new schema, so **Database migrate** runs before the deployment that uses it. Deploying first
  would make every sign-up fail (the new code writes `purpose`).
- Whoever controls the inbox controls the account, as with any email reset. There is no second factor.
- Not built: telling the person by email that their password changed, and a limit on reset requests per
  IP beyond the general rate limit.
