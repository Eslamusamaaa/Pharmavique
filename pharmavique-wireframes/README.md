# Pharmavique wireframes

Arabic-first RTL wireframes (Phase 1 + Pharmacist), brand-applied.

- `Pharmavique Wireframes (standalone).html`: single offline file, open in any browser.
- `Pharmavique Wireframes.dc.html`: editable source canvas. It imports the `Pv*.dc.html` section files and needs `support.js` and `brand/` beside it.
- Sections: A onboarding/shell, B core (mobile, tablet, desktop), C pharmacist, D brand/tokens/components, E account.

All drug names, prices and company names beyond the brief are sample content.

## Phase 2 changes (2026-11-18, see `docs/PHASE_2_PLAN.md`)

- B11 compare: computed equivalence row and official safety items.
- B12 price history: only real snapshots (history starts 16 Nov 2026), no invented trend.
- B14 my list: ingredient allergies, add by search, box scan or prescription, "check my list".
- B15 alerts: recall item that touches the user's list, with batches.
- B16 assistant: answer levels, document-cited explainer, listen (TTS) and voice input (STT).
- New B20 safety check, B21 recall detail with batch check, B22 patient safety center (RMM).
- C2 prescription review: strength and form read, dose always "غير واضح" (never guessed), add to my list.
- C7: pharmacist workspace navigation.
- Interactions and contraindications are deferred (owner decision) and appear nowhere.
- `Pharmavique Wireframes (standalone).html` was exported before these changes and is **out of date**;
  open `Pharmavique Wireframes.dc.html` (served over http, for example `python -m http.server`) for the current version.
