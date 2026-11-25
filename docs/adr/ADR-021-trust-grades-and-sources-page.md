# ADR-021: three trust grades, a disclaimer on every medical answer, a public sources page

Status: accepted, 2026-11-25 (owner's answers to the Phase 0 questions).

## Context

Records already carry a `trust` of `official` or `unofficial_unverified` in the database, but the API
hid it: an interaction finding named its source (`ddinter-2.0`) and nothing else, so the app could not
tell a person that DDInter and MeDIC are research data nobody has verified, while the label text from
openFDA is an official reference of another country and the SFDA registry is official and Saudi. Two
medical answers (interactions, contraindications) carried an Arabic note but no `disclaimer` field.

## Decision

- **Three grades** (`bootstrap/trust.py`): `official_sa` (SFDA), `official_foreign` (openFDA and
  DailyMed label text) and `unverified` (DDInter 2.0, MeDIC, product pictures). A source nobody listed
  is `unverified`: nothing is promoted by default.
- **Every interaction finding, contraindication and assistant citation carries `trust_grade` and
  `trust_label_ar`.** A citation is graded by its kind and, for documents, by the host of its link
  (an exact domain or subdomain match, so `sfda.gov.sa.example.com` is not SFDA).
- **Every medical answer has a `disclaimer` field** (`DISCLAIMER` of `api_drugs`); the interaction and
  contraindication answers gained it. The app shows the same line under the header of every medical
  screen (`DisclaimerBar`), with a link to the sources page.
- **`GET /v1/sources`** (public, flag `PHARMAVIQUE_FEATURE_SOURCES_PAGE`): the catalogue of sources
  with grade, how each is refreshed, a public link where the repository knows one, the number of
  records and the last fetch time read from the database (one query per schema, no joins). A figure
  the database cannot give is `null` and the app says "غير معروف": never zero, never "now". The page
  answers even if the database does not.
- The grade is a statement about **where data comes from, not about its medical correctness**. An
  official source can still be wrong or outdated, and an unverified one can be right.

## Consequences

- The app can show "غير موثّق" next to DDInter and MeDIC statements, and the legend explains each grade.
- Adding a source means adding it to the catalogue in `trust.py`; the test that lists the catalogue
  and the one that maps names to grades must be updated with it.
- Egypt's CSV adapter (later) will map to `unverified` through the same rule.
- Product pictures are listed as unverified without a date until the pictures store records one.
