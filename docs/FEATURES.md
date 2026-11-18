# Features and Product Decisions

Last updated: 2026-11-17. The three roles (patient, pharmacist, pharma company) have **equal priority**. Everything below respects the safety rules of the brief: the system gives facts from our data (price, active ingredient, similar products), never a recommendation, never dosing, never "stop" or "switch".

## Decisions log

| Date | Decision | Notes |
|---|---|---|
| 2026-11-17 | Patient, pharmacist and company are equally important | Build the shared core first, then role views |
| 2026-11-17 | **Box photo**: plain OCR reads the text on the box (name, strength, form), then we search our data | No product-recognition model; OCR text goes through the same fuzzy search as typed text |
| 2026-11-17 | **Prescription photo**: handwriting OCR, extract drug names, look them up in our data, answer the pharmacist's questions (price, active ingredient, similar products, cheaper equivalents) | Answers come from our data only; no recommendations |
| 2026-11-17 | **Leaflet (package insert) RAG is out of scope for now.** RAG is over our own catalog data | The project brief listed leaflet RAG in Phase 4; this changes it. Needs an ADR when we start |
| 2026-11-17 | **Voice search**: a speech-to-text API turns speech into text, then the normal text search runs | Egyptian and Saudi dialects must be tested |
| 2026-11-17 | **Prices are in Saudi riyals (SAR)** | Owner's decision. The SFDA pages do not state a currency, so the API marks it as an owner-confirmed assumption, not as a source fact (OPEN_QUESTIONS Q-5) |
| 2026-11-17 | **Find pharmacies near me**: ask for the location, show nearby pharmacies on a map | Nearest pharmacies only. It never says that a pharmacy has a given drug, because we have no inventory data |
| 2026-11-17 | Web search features are wanted | Scope and allowed sources to be decided (OPEN_QUESTIONS Q-22) |
| 2026-11-17 | Agentic RAG is wanted, as a read-only tool-using assistant over our own contracts | See "AI features" below |
| 2026-11-17 | **Look-alike sound-alike (LASA) name warnings** are an early feature | Computed from the catalog names (about 9,000) with string and phonetic similarity, in Arabic and English. Informational only: "a similar name exists, double-check". Also lowers OCR confidence for confusable names |
| 2026-11-17 | **SFDA safety bulletins linked to the drug page** is the first extra data source | The monthly "Recalls, Market Withdrawals & Safety Alerts" PDF. Product matching is reviewed by a person. We show what SFDA published, with a link, and no advice. Same unverified SFDA reuse status (DATA_SOURCES SA-2) |

| 2026-11-18 | Phase 2 scope: safety engine, explainer, prescription scanner, comparison, price and recall intelligence, Arabic intelligence, pharmacist workspace | Details and limits in `docs/PHASE_2_PLAN.md` |
| 2026-11-18 | App in **React Native with Expo**; LangGraph and LangChain for the assistant (infrastructure only); pgvector in our Postgres | |
| 2026-11-18 | **Interaction and contraindication checking deferred**; hosted model providers (free tiers included) allowed for photos, voice and lists; embeddings by external API, no local model | Privacy risk accepted by the owner |

### Later decisions (2026-11-17)

- The feature build order was approved by the owner (see "Build order").
- **Pharmacist shelf scan:** the pharmacist photographs a whole shelf and the system finds each box and reads the name on it, so items are never typed in by hand. The confirmed items become the shelf list used for price and safety alerts. Details under "AI features".
- The system must be **scalable**; software architecture gets focused attention before feature code (ADR-004, proposed).
- **More SFDA categories are in scope**: veterinary medicines, medical devices, cosmetics, food and supplements, feed, and products under special access. SFDA publishes 28 official lists (DATA_SOURCES SA-3). Each is added as its own source once its structure is read.
- **Official sources now exist for features first planned from other data**: an official drug shortage list, a drug companies list, safety labeling updates and alerts, and a licensed pharmacies directory. These are candidates to replace or complement the monthly PDF and the maps provider.
- **The SFDA public pages contain no product images and no leaflet files** (800 pages checked), so image-based features cannot rely on SFDA.

## Core features (data we already collect)

Search in Arabic and English with spelling tolerance; full drug page (26 fields in both languages, with source and fetch time); equivalents sorted by price (with a "possible, needs pharmacist check" tier); side-by-side comparison; price history; change alerts (price, new drug, authorization or marketing status); patient list with a shared-ingredient warning; competitor radar, market map per active ingredient and gap discovery for companies; company portfolio view; data-quality dashboard for operators.

## AI features

| Feature | How | Guardrails |
|---|---|---|
| Prescription reader | Handwriting OCR, then match each extracted name to candidates in our data | Show the extracted text and a confidence per drug; low confidence is flagged; the pharmacist confirms before anything is looked up. Images deleted after processing |
| Box reader | OCR of the box text, then the same search | Same confirmation step |
| Voice search | STT API, then text search | The recognized text is shown and editable |
| Assistant (agentic RAG) | An LLM chooses among read-only tools (search, product details, equivalents, price comparison, change history) and answers with citations to our records | Equivalence is computed by our deterministic code, never decided by the LLM. Step limit, timeout, cost cap. Medical-advice questions get a polite "ask your pharmacist or doctor" |
| Ingredient and form normalization | Offline LLM-assisted mapping of free text (salts, dosage forms) to canonical ids, reviewed by a person | Nothing goes live unreviewed |
| Alias generation | Offline Arabic and English transliteration aliases for trade names, reviewed | Same |
| Shelf scan (pharmacist) | One photo of a shelf: find each box, read the name on it, match it to the catalog, and show a grid to confirm. The confirmed items become the pharmacy's shelf list for price and safety alerts | Names are never typed in by hand. Each match shows a confidence; low confidence is flagged and the pharmacist confirms. Similar names (LASA) are highlighted. No stock counts and no availability claims. Photos are deleted after processing |
| Weekly change digest | Natural-language summary of the change report | Generated only from the structured diff |
| Company analytics questions | The LLM calls predefined analytics queries (no free SQL) | Read-only, tenant-scoped |
| Price anomaly flags | Statistical outlier detection on price changes | Informational |
| Web-search enrichment | Search allowed sources, summarize with links | Labeled `unofficial_unverified`, allow-listed domains, link instead of copy |

## Build order

Shared core first (all three roles need it), then the two safety features, then the role views and AI features.

1. Slice 1: search, drug page, price (shared by patient, pharmacist and company)
2. Equivalents sorted by price
3. Change history and alerts
4. **LASA name warnings**
5. **SFDA safety bulletins linked to the drug page**
6. Role views and the public API
7. OCR (box first, then prescription) and voice search
8. Assistant (agentic RAG), web search enrichment, pharmacy finder

## Not now

Drug-interaction checking (needs a licensed clinical source), dosing or adherence reminders, anything resembling advice.
