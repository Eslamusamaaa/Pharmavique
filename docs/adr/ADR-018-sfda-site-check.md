# ADR-018: check SFDA's own drug list before saying a drug is not in it

Status: accepted, 2026-11-23 (owner: after the assistant looks in our database, it must also search
SFDA's site, so "not in the SFDA list" is certain and not only a statement about our copy).

## Context

Our registry copy is refreshed daily at best, and a drug can appear on SFDA's site before it does in
our database. Telling someone "this drug is not registered" from a stale copy is a claim about a
medicine, so it needs the source itself.

## Decision

- **A tool `sfda_site_check(trade_name)`**, always offered (no key; turn it off with
  `PHARMAVIQUE_SFDA_SITE_CHECK=false`). It does one plain GET of
  `https://www.sfda.gov.sa/en/drugs-list?TradeName=<name>`, the list page the daily crawler already
  reads. The page answers with a result table, or with the text "No Results Found" (read on
  2026-11-23: Cataflam gives one row, Redoxon gives none).
- **Polite:** the crawler's User-Agent, one request at a time and at most one every 1.5 seconds,
  answers cached for an hour, at most 2 checks per question. `robots.txt` has no rule against the
  path (read 2026-11-23).
- **Never a false "absent":** a page that is neither a table nor "No Results Found", a non-200
  status or a network error raises. The assistant is told to say it could not check the site, not
  that the drug is absent.
- **Wording:** the drug list covers medicines. Supplements and other health products are registered
  elsewhere, so the answer says "not in SFDA's drug list", never "not registered with SFDA".
- The record is cited like any other source (kind `sfda_site`, a link to the search it came from).

## Consequences

- One more outbound call to sfda.gov.sa, only for names the registry copy did not find.
- Unknown: whether sfda.gov.sa answers requests from Vercel's addresses. If it does not, the tool
  reports "could not check" and the answer falls back to our copy, said plainly.
