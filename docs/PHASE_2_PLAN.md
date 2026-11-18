# Phase 2 plan: the application, AI layer and safety features (DRAFT for approval)

Date: 2026-11-18. Builds on `docs/AI_ARCHITECTURE.md`, `docs/FEATURES.md`, ADR-001..004 and the rules in
`CLAUDE.md`. Nothing here is built yet. Provider and model facts below are **the owner's notes, not
verified**: each one is checked against the provider's documentation when the keys arrive, and model
ids live in configuration, never in code.

## 1. What the owner asked for (2026-11-18)

Eight features (safety engine, AI explainer, prescription scanner, comparison engine, price
intelligence, recall intelligence, Arabic intelligence, pharmacist workspace), an embedding model
(BGE-M3 first, Qwen3-Embedding-0.6B or multilingual-e5-large as alternatives), a vision model, an
LLM, speech to text and text to speech, a web search tool, LangGraph and LangChain, onion
architecture, clean code and DDD. Keys come later.

## 2. Feature by feature: what we can build honestly

| # | Feature | Can build now from our data | Needs a source we do not have | Not allowed by the project rules |
|---|---|---|---|---|
| 1 | Medication safety engine | Patient medication list; **duplicate active ingredient** check (deterministic, from the catalog); **recall, DHPC, safety alert and RMM** matches for each listed drug; allergy match **by ingredient name** the user entered | **Drug-drug interactions, contraindications and class allergies** (penicillin allergy -> amoxicillin) need a licensed clinical source with severity levels (Q-37) | **Dose-related warnings**: the brief forbids dosing |
| 2 | AI medication explainer (patient / pharmacist / clinical levels) | Answers from our catalog fields, SFDA safety-labeling updates, DHPC letters, safety alerts, RMM pages and recall texts, with citations | "What it does, how it works, side effects" need a leaflet or label source (Q-24, Q-38). Without it the assistant says "not in our sources" | Advice, "stop", "switch", dosing |
| 3 | Prescription scanner | OCR -> names -> catalog match -> strength and form -> per-drug info -> duplicate check -> add to my list. **Unclear dose or instruction is marked uncertain, never guessed**; the pharmacist or user confirms every line | Interaction check (as feature 1) | Reading a dose and telling the user what to take |
| 4 | Comparison engine | Ingredient, strength, form, manufacturer, registered price, status, safety items; **verdict computed by our `substitution` code**: `equivalent` (same ingredient set, strength, form family) or `possible, needs pharmacist check` | Contraindication and interaction rows (Q-37) | The LLM deciding equivalence |
| 5 | Price intelligence | SFDA registered price and its **history from our own snapshots** (history starts with the 2026-11-16 crawl; a chart needs several `sfda-update` runs, so no 3 or 6 month trend exists yet) | **Pharmacy prices and availability**: no inventory or shop price data exists (Q-39) | Saying a pharmacy has a drug in stock |
| 6 | Recall and safety intelligence | Detect new items (scheduled `sfda-update` of the lists), link to products (done today), **match affected batches** when the circular names them, alert users whose list holds the product; official link and date | Push notifications need the app (section 5) | |
| 7 | Arabic intelligence | Arabic normalization and aliases (done), Arabic search, Arabic OCR (Windows OCR now, a vision model later), STT for Egyptian and Saudi dialects, TTS for answers, simple explanations of terms **from our sources** | Arabic leaflets (Q-24) | |
| 8 | Pharmacist workspace | Advanced search, comparison, prescription scanner, safety updates, saved reports with their sources | Interaction checker and therapeutic alternatives by class (Q-37) | |

## 3. Architecture (onion and DDD, unchanged rules)

New and changed contexts (`src/pharmavique/<context>/`, each with contracts, domain, application,
infrastructure, presentation):

| Context | Owns | Key ports (application layer) |
|---|---|---|
| `knowledge` (un-parked) | Document chunks from SFDA texts (DHPC, alerts, labeling, RMM, recalls) and later label sources, with provenance and `ocr` flags | `Embedder`, `ChunkStore` |
| `search` | Adds the semantic signal (pgvector) to the hybrid search already built | `Embedder` |
| `assistant` | Conversations, the agent loop, tools, citations, guardrails, cost ledger, answer levels | `LanguageModel`, `AgentRunner`, `WebSearch`, tools over other contexts' contracts |
| `recognition` | Box, prescription and shelf jobs (state machine in `AI_ARCHITECTURE.md` 4.1) | `VisionReader`, `ImageStore` |
| `voice` (new) | Speech to text and text to speech requests, never stored | `SpeechToText`, `TextToSpeech` |
| `medication_safety` (new) | The user's medication list, allergies (ingredient level), checks and their findings | `InteractionSource` (empty until Q-37), `SafetyItems` (over `catalog.contracts`) |
| `watchlist` | Alerts to users when a listed drug gets a recall, alert or price change | notifier port |

- **LangGraph and LangChain live only in `assistant.infrastructure`** (the `AgentRunner` adapter).
  The domain and application layers stay free of them: the import contracts in `pyproject.toml`
  get `langchain`, `langgraph`, `sentence_transformers`, `torch`, `openai` and `groq` added to the
  forbidden list for `domain` and `application`. Replacing LangGraph is one adapter.
- **Vector database: pgvector in the Postgres we already run** (version 0.8.7 is installed). One
  schema per context, `embedding vector(1024)`, HNSW index. A separate vector database is not needed
  at our size (about 9,000 products and a few thousand document chunks); the store is a port, so it
  can move later (ADR-004).
- **Models behind ports, chosen by measurement** (ADR-005 vision, ADR-006 embeddings, ADR-007 LLM):
  - embeddings: BGE-M3 run locally on CPU (needs installing `sentence-transformers` and `torch`,
    about 2 to 3 GB; Q-31), 1024 dimensions; Qwen3-Embedding-0.6B and multilingual-e5-large are
    tried on the same evaluation set before we commit;
  - vision (OCR of boxes and prescriptions) and the LLM: hosted (OpenRouter or Groq, owner's
    notes), set by environment variables;
  - STT and TTS: provider chosen when keys arrive; Arabic dialects tested on recordings.
- **Web search tool**: a `WebSearch` port with an allow-list of domains; every web result is labelled
  `unofficial_unverified` and shown as a link, never merged into catalog facts (Q-22).
- **Guardrails in code**: answers must cite retrieved records; nothing retrieved means "not in our
  sources"; no dosing, no "stop" or "switch"; SFDA and web text is data, never instructions; step,
  time and cost limits per question.

## 4. Free hosted tiers and health data

Free endpoints may keep or use prompts, and the owner's notes list low limits (for example 1,000
requests a day). Prescription photos, voice and medication lists are health data (`CLAUDE.md`).
**Until Q-9 is answered, only non-personal text (catalog questions) goes to hosted models; photos and
voice use them only in development with test material.**

## 5. The application (front end)

The wireframes are Arabic-first, RTL, mobile first with tablet and desktop. The stack is the owner's
choice (Q-40); the API stays first and the app only calls it.

## 6. Wireframe changes (to match the features above)

Existing screens: A1-A5, B1-B19, C1-C7, D0-D1, E1-E5. Changes:

| Screen | Change |
|---|---|
| B14 My list | Becomes the medication list: add by search, scan or prescription; allergies by ingredient; "run safety check" |
| new B20 Safety check | Findings grouped: same active ingredient twice, recall or alert on a listed drug, allergy match by ingredient; interactions shown as "needs a licensed source" until Q-37; no dosing, every item with source and date |
| B16 Assistant | Level switch (مبسط / للصيدلي / متخصص), sources under every answer, "not in our sources" state, listen button (TTS), voice input |
| B11 Compare | Verdict row from our code (متكافئ / ممكن، يحتاج مراجعة صيدلي) with the rule spelled out; safety rows |
| B12 Price history | Only real snapshots, "history starts on 2026-11-16"; no pharmacy prices |
| B15 Alerts feed | Recall item shows affected batches and "this affects a drug in your list" |
| new B21 Recall detail | Official circular: product, batches, level, reason, SFDA recommendation quoted, link; batch check against what the user entered |
| new B22 Patient safety center | RMM materials of the user's drugs (patient cards, guides) as official links |
| C2 Prescription review | Strength and form columns; unclear dose marked "غير واضح" (never filled in); add all to a list |
| C7 Pharmacist workspace | Workspace navigation: search, compare, prescription scan, safety updates, saved reports with sources |

## 7. Build order (each step: tests first, all checks green, owner sees it working)

1. ADRs 005-007 and the import contracts for the new frameworks; wireframe changes (section 6).
2. `knowledge`: chunk the SFDA texts we already have, embed with BGE-M3 into pgvector, hybrid
   retrieval with citations; measured on a small labelled question set.
3. Read API for what the app needs first: product page with its safety items, comparison with the
   computed verdict, price history, alerts.
4. `medication_safety`: list, duplicate ingredient check, recall and alert matches, batch match.
5. `assistant` with LangGraph: tools over search, product, equivalents, safety items, documents and
   web search; levels; citations; guardrails; evaluation set of questions.
6. `recognition` (box, then prescription) with a fake reader first, then the vision model.
7. `voice`: STT and TTS adapters.
8. The app screens, in the order of the wireframes.

## 8. Owner decisions (2026-11-18)

| Question | Decision | Consequence |
|---|---|---|
| Q-40 app stack | **React Native with Expo** (one TypeScript code base for mobile and web) | RTL and Arabic fonts set up from the first screen |
| Q-37 interactions | **Deferred.** Not built and not shown in the app for now | Safety check covers duplicate ingredients, recalls and alerts, ingredient allergies only; `InteractionSource` port is not created yet |
| Q-9 hosted providers | **Allowed**, including free tiers, for photos, voice and medication lists | Recorded as the owner's accepted privacy risk; free-tier terms and limits are checked when keys arrive; uploads are still deleted after processing and never logged |
| Q-31 local embeddings | **No local install**: embeddings through an external API | `Embedder` adapter over HTTP (BGE-M3 or an alternative, as the provider offers); key and model id from the environment |

Still open: Q-38 (public label source), Q-39 (pharmacy prices and stock).

## 9. Questions only the owner can answer (original list)

| # | Question | Blocks |
|---|---|---|
| Q-37 | Which licensed source for interactions, contraindications and drug classes? (for example a commercial drug database; free academic datasets usually forbid commercial use) | Interaction checker in features 1, 3, 4, 8 |
| Q-38 | May we use a public label source (for example US openFDA labels, public domain, English, US products) for "what it does, side effects"? It is not the Saudi leaflet | Explainer depth in feature 2 |
| Q-39 | Is there any pharmacy price or stock data we may use? | Feature 5 beyond SFDA prices |
| Q-40 | App stack: one code base for mobile and web (for example Flutter or React Native with web), or a web app first? | Section 5 |
| Q-9 | May photos, voice and medication lists go to hosted model providers, and on which plan? | Section 4 |
| Q-31 | May we install `torch` and `sentence-transformers` locally for BGE-M3? | Step 2 |
