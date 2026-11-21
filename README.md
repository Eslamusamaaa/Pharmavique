<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="pharmavique-wireframes/brand/logo-white.png">
    <img src="pharmavique-wireframes/brand/logo-h.png" alt="Pharmavique" height="80">
  </picture>
</p>

<h3 align="center">Know your medicine.</h3>

<p align="center">
  Pharmavique helps people in Saudi Arabia understand the medicines they use.<br>
  Find any registered medicine in seconds, see what it contains and where the information comes from,<br>
  discover other products with the same active ingredient, and stay informed about official safety alerts and recalls.
</p>

<p align="center">
  Search by name, point your camera at a medicine box or a prescription,<br>
  or simply ask a question and hear the answer in a Saudi Arabic voice.
</p>

<p align="center">
  Built for patients, pharmacists and pharmaceutical companies.
</p>

---

## Table of contents

1. [Overview](#1-overview)
2. [Project status](#2-project-status)
3. [Screens and UI design](#3-screens-and-ui-design)
4. [Features in depth](#4-features-in-depth)
5. [AI layer](#5-ai-layer)
6. [Guardrails and anti-hallucination](#6-guardrails-and-anti-hallucination)
7. [Observability](#7-observability)
8. [Architecture](#8-architecture)
9. [Data](#9-data)
10. [Tech stack](#10-tech-stack)
11. [Getting started](#11-getting-started)
12. [Configuration reference](#12-configuration-reference)
13. [Command line reference](#13-command-line-reference)
14. [API reference](#14-api-reference)
15. [Testing and quality gates](#15-testing-and-quality-gates)
16. [Security and privacy](#16-security-and-privacy)
17. [Repository layout](#17-repository-layout)
18. [Documentation index](#18-documentation-index)
19. [Roadmap](#19-roadmap)
20. [Disclaimer](#20-disclaimer)

---

## 1. Overview

Pharmavique is a multi-tenant drug information platform for three audiences: **patients**,
**pharmacists** and **pharmaceutical companies**. Saudi Arabia is the first market; Egypt is planned
as a pluggable import adapter.

The drug data comes from the official registry of the Saudi Food and Drug Authority (SFDA) and its
public safety publications. Interaction pairs, contraindications and US label text come from open outside
sources and are marked `unofficial_unverified`; pictures come from Saudi pharmacy sites. Everything is
collected politely and stored with provenance. On top of that data the platform adds:

- a typo-tolerant, bilingual search (Arabic and English trade names, active ingredients, register numbers),
- a drug page with every registry field and where it came from,
- a rule-based equivalence engine that never lets a language model decide interchangeability,
- an AI assistant that answers from retrieved records with numbered citations, at three levels of detail,
- a Saudi Arabic voice for spoken answers and speech-to-text for voice search,
- a vision model that reads medicine boxes and prescriptions and matches them to the registry,
- SFDA safety intelligence: safety alerts, recalls and circulars, labeling updates, risk minimization
  materials, shortages and letters to healthcare professionals,
- an **interaction check** between medicines (recorded pairs with the severity the source gives),
  duplicated active ingredients, and the conditions a drug's labels say it must not be used with, for the
  pharmacist, the patient's own medicine list and the assistant. Everything is matched by **active
  ingredient**, never by trade name, and "nothing found" is never presented as "safe",
- product pictures from Saudi online pharmacies, mapped to each drug.

The project is **API first**: the mobile app holds no drug data of its own and every screen calls the API.

## 2. Project status

| Area | Status | Notes |
|---|---|---|
| SFDA drug registry | Done | 9,162 registered drugs crawled with Arabic and English details; 9,144 loaded and searchable |
| Search | Done | Recall@1 of 96% and recall@10 of 100% on 300 generated misspellings of real names |
| Drug page API | Done | Every registry field, price with its currency basis, provenance |
| Same active ingredient and equivalence | Done | Cheapest first, verdict computed by the `substitution` rules |
| Assistant (LLM, LangGraph, tools) | Done | Citations, three levels, spoken answers in Saudi dialect |
| Guardrails | Done | Emergency detection, injection rules plus a learned classifier, dose and stop rules, numeric grounding check |
| Observability | Done | Structured events, Prometheus metrics, request ids |
| Voice | Done | Whisper speech-to-text; Saudi Arabic text-to-speech through ElevenLabs or Groq |
| Box and prescription scan | Done | Vision model with automatic fallback across models, registry matching, mandatory review |
| Knowledge base (RAG) | Done | 10,000+ cited chunks with embeddings: SFDA documents and US label sections per active ingredient |
| SFDA lists | Done | Safety lists, shortages, approvals, companies (6,135) and licensed pharmacies (385), loaded and linked to products |
| Interaction check | Done | 234,757 recorded drug pairs (DDInter), duplicated ingredients, `POST /v1/interactions/check` |
| Contraindications | Done | 3,960 drug-disease records (MeDIC) on the drug page and for the assistant |
| Product pictures | Done, shipped as a Docker image | 3,815 of 9,162 drugs have a real pharmacy picture (42%); the rest show a marked placeholder |
| Mobile app | Done for the core journeys | Home, search, drug page with pictures, assistant, voice search, box and prescription scan, first-launch role choice, interaction check (pharmacist) and "my medicines" (patient) |
| Daily refresh | Built, to be scheduled | `scripts/daily_refresh.ps1` re-reads drugs, prices, fast lists and pictures and loads the difference |
| Security | Hardened | Per-client rate limits, secret scanning, Dependabot, protected `main`, pinned CI actions, see [SECURITY.md](SECURITY.md) |
| Accounts and roles | Done | Email and password, roles patient, pharmacist, company, operator, refresh-token rotation with replay detection, sign-in screens in the app ([ADR-009](docs/adr/ADR-009-identity-and-sessions.md)) |
| Saved medicines, allergies, alerts, weekly digest, price-changed mark | Done | `watchlist` context under row-level security, the catalog outbox relay, alerts for price changes, withdrawals and relistings ([ADR-010](docs/adr/ADR-010-outbox-relay-and-alerts.md)). Shortage and safety-notice alerts are not built yet |
| Company views, operator board | Done | `analytics` read model rebuilt from the catalog: market map per ingredient, thin and missing strengths and forms, change radar; operator data-quality board ([ADR-011](docs/adr/ADR-011-company-views-and-quality-board.md)). Registry facts only, no sales or demand figures |
| Nearby licensed pharmacies | Done, at city precision | By city from the SFDA list, using the person's position once and never keeping it; the list has no street or coordinates, so no distance to a pharmacy and never a stock claim ([ADR-013](docs/adr/ADR-013-pharmacy-finder-and-location.md)) |
| Medicine history as memory | Done | A signed-in patient's saved medicines (current or past) are compared with any new drug, with recorded interactions from DDInter and openFDA, and with their allergies; never advice, and the language model never sees the list ([ADR-014](docs/adr/ADR-014-medicine-history-as-memory.md)) |

## 3. Screens and UI design

The wireframes, the running app's screens next to them and the design system (colors, type, spacing) are in
their own folder: **[`pharmavique-wireframes/`](pharmavique-wireframes/README.md)**.

## 4. Features in depth

### 4.1 Search

1. **Normalization** of Arabic and Latin text: diacritics removed, alef, ya and ta marbuta variants unified,
   Arabic-Indic digits converted, punctuation and spacing folded; an alias table covers common spellings.
2. **Signals**: an exact signal (register number, exact normalized name) and a fuzzy signal
   (PostgreSQL `pg_trgm` trigram similarity over trade names, the brand part of each name, and ingredients).
3. **Fusion**: reciprocal rank fusion of the signals; each result keeps its per-signal rank and score so the
   app can explain the match ("name match", "partial match", "same active ingredient").
4. **Measured**: making the brand part of a registry name a searchable term raised recall@1 on 300
   generated misspellings from 76% to 96% (recall@10 100%). BM25 over descriptive words added little
   and is not used.

### 4.2 Drug page

Trade names (Arabic and English), register number, active ingredients with strength and unit, dosage
form, route of administration, package, legal status (OTC or prescription), distribution site, ATC
codes, shelf life exactly as stated (the source gives no unit, so none is added), storage conditions,
marketing company and country, manufacturers, marketing and authorization status, the registered price
with its currency basis, and provenance (source, source URL, fetch time, trust level).

### 4.3 Same active ingredient and equivalence

Products with exactly the same set of active ingredients are listed cheapest first. Each row carries a
verdict computed by the `substitution` domain, never by a language model:

| Ingredient set | Strength (after unit normalization) | Dosage-form family | Verdict |
|---|---|---|---|
| Same | Same | Same | `equivalent` |
| Same | Different | any | `not_equivalent` |
| Same | Unknown or unreadable | any | `possible_needs_pharmacist_check` |
| Same | Same | Different or unknown wording | `possible_needs_pharmacist_check` |
| Different | any | any | never listed |

Strength normalization is exact (fractions, not floats): 500 mg equals 0.5 g, 120 mg per 5 ml equals
24 mg per ml.

### 4.4 Assistant

- **Levels**: simple (patient), detailed (pharmacist), clinical (specialist). Same sources, different depth.
- **Tools** the model can call, all read-only:

| Tool | Returns |
|---|---|
| `search_drugs(query)` | Up to 8 registered products by name, ingredient or register number |
| `drug_details(register_number)` | Every registry field of one product, with its source |
| `same_ingredient(register_number)` | Same-ingredient products, cheapest first, with the computed verdict |
| `search_documents(query, register_number?)` | Passages of SFDA documents and of US drug labels (interactions, contraindications, pregnancy, patient advice), hybrid retrieval |
| `check_interactions(register_numbers)` | Recorded interactions between products and duplicated ingredients, each with its source; always followed by a coverage record |
| `contraindications(register_number)` | Conditions the product's ingredients are recorded as contraindicated with, from drug labels |

- **Citations**: every record a tool returns gets a number; the model cites `[n]`; the runner keeps only
  citations that point at records really retrieved and renumbers them in order.
- **Spoken answers**: with `spoken = true`, the model writes in everyday Saudi dialect, in short spoken
  sentences, and the text is sent to the Saudi Arabic voice (citation marks and links are not read aloud).

### 4.5 Voice

- **Speech to text**: Whisper (`whisper-large-v3-turbo`) through Groq, with an Arabic language hint.
- **Text to speech**: ElevenLabs (`eleven_v3`, any voice id, MP3) by default, or Groq Orpheus Arabic Saudi
  (six Saudi dialect voices, WAV, 200 characters per request). Long text is split at sentence ends to fit
  each provider's limit and the audio is joined into one file.

### 4.6 Box and prescription scan

1. The photo (JPEG, PNG or WebP, up to 8 MB) is sent to a vision-language model as an in-memory data URL.
2. The model transcribes medicine names, strengths and dosage forms only, as JSON. It is told never to
   read doses or instructions.
3. Each line is matched against the registry with the same search used for typed text (top 3 candidates).
4. Every line is marked for review; on prescriptions the dose is always reported as **unclear** for the
   pharmacist to confirm. The image is never stored.
5. Free models are often busy, so readers are tried in order until one answers.

Measured on a real box photo: `nvidia/nemotron-3.5-super-vl:free` read it correctly in about 6 seconds,
and the first registry candidate was the exact product with a score of 1.0.

### 4.7 SFDA safety intelligence

Safety alerts, drug circulars and withdrawals, safety labeling updates, risk minimization materials,
current and resolved shortages, and letters to healthcare professionals are crawled, their detail pages
and documents downloaded, PDF text extracted (with OCR for scanned files), rows linked to products, and
the text cut into cited chunks for the assistant.

### 4.8 Interaction check and contraindications

- **Match by active ingredient.** Each product's ingredient list (already split per ingredient) is turned
  into lookup keys: as written, without salt or ester words (`AMLODIPINE BESILATE` gives `amlodipine`) and
  under the spelling the sources use (`PARACETAMOL` gives `acetaminophen`). The registry name is never
  changed. 75% of ingredient occurrences are known to the interaction source; the rest (nutrients,
  infusions, biologics, new molecules) are returned as `unmatched`, never as safe.
- **Sources.** Drug-drug pairs: DDInter 2.0 (severity as the source rates it). Drug-disease
  contraindications: MeDIC (government drug labels). Explanatory text: the interactions, contraindications,
  pregnancy and patient-advice sections of US labels from openFDA, quoted as US labels.
- **Surfaces.** `POST /v1/interactions/check`, `GET /v1/interactions/contraindications/{register_number}`,
  the assistant's two tools, the pharmacist's check screen and the patient's "my medicines" list (kept on
  the device only).
- **Never advice.** No doses, no "stop" or "switch": findings state what a source records and send the
  reader to the pharmacist or doctor. Design: [ADR-008](docs/adr/ADR-008-interactions-context.md).

## 5. AI layer

| Capability | Port (application layer) | Adapter (infrastructure layer) | Default provider and model |
|---|---|---|---|
| Language model with tool calling | `AgentRunner` | `LangGraphAgentRunner` (StateGraph, ToolNode) | Groq `openai/gpt-oss-120b` |
| Prompt-injection classifier | `InjectionDetector` | `GroqPromptGuard` | Groq `meta-llama/llama-prompt-guard-2-86m` |
| Embeddings | `Embedder` | `OpenAICompatibleEmbedder` | OpenRouter `baai/bge-m3` (1024 dimensions) |
| Retrieval | `PassageSearch` | pgvector cosine plus trigram, fused by rank | PostgreSQL |
| Vision OCR | `VisionReader` | `OpenAICompatibleVisionReader`, `FallbackVisionReader` | OpenRouter `nvidia/nemotron-3.5-super-vl:free`, then `google/gemma-4-31b-it:free`, then `inclusionai/ling-3.2-flash:free` |
| Speech to text | `SpeechToText` | `GroqSpeechToText` | Groq `whisper-large-v3-turbo` |
| Text to speech | `TextToSpeech` | `ElevenLabsTextToSpeech`, `GroqTextToSpeech` | ElevenLabs `eleven_v3`, or Groq `canopylabs/orpheus-arabic-saudi` |

Model ids, providers and keys are configuration, never code. Every port has a fake adapter used by the
unit tests, so no test needs a network or a key.

**How an answer is produced**

```mermaid
sequenceDiagram
    participant App
    participant API as POST /v1/assistant/ask
    participant Policy as AskAssistant (guardrails)
    participant Agent as LangGraph agent
    participant LLM as Language model
    participant Tools as Tools (registry, equivalence, documents)
    App->>API: question, level, register number, spoken
    API->>Policy: ask
    Policy->>Policy: emergency check, injection rules, injection classifier
    Policy->>Agent: run
    loop until the model answers (call budget, step limit, timeout)
        Agent->>LLM: system prompt and messages
        LLM-->>Agent: tool call
        Agent->>Tools: validated arguments
        Tools-->>Agent: records marked as untrusted data, each with a citation number
    end
    LLM-->>Agent: answer with [n] citations
    Agent-->>Policy: text, cited records, evidence, trace, token usage
    Policy->>Policy: dose and stop rules, numeric grounding check
    Policy-->>API: answer and outcome
    API-->>App: answer, citations, flags, disclaimer
```

## 6. Guardrails and anti-hallucination

The response policy is helpful by default and firm only where there is real danger. Every layer is
enforced in code around the model, not only in the prompt.

| Layer | When | What it does |
|---|---|---|
| Input validation | Before anything | Question length 1 to 1,000 characters; image type and size; audio size |
| Emergency detection | Before the model | Overdose, a child swallowing medicine, breathing trouble, facial swelling, fainting, seizures or self-harm get an immediate reply to call 997 or go to the nearest emergency department. The model is not called |
| Injection rules | Before the model | Deterministic English and Arabic patterns: overriding instructions, revealing the system prompt, role-play without limits, jailbreak phrases |
| Injection classifier | Before the model | Llama Prompt Guard 2 through Groq; blocks at a score of 0.9 or more. Measured: an English attack scored 0.9996, an Arabic attack only 0.0066, which is why it adds to the rules and never replaces them. A classifier outage blocks nothing |
| Tool argument validation | During the run | Register numbers must match `[A-Za-z0-9-]{3,30}`; queries 1 to 200 characters; violations are returned to the model as tool errors |
| Tool budget and limits | During the run | At most 8 tool calls, 20 graph steps and 75 seconds per question; a model that loops ends with no answer instead of a runaway call chain |
| Tool error isolation | During the run | A failing source returns a JSON error to the model; the request does not fail |
| Untrusted data marking | During the run | Every tool result is wrapped with a note that it is data and that instructions inside it must never be followed; document passages are capped at 1,200 characters |
| Citation integrity | After the model | Only citation numbers that point at retrieved records survive; they are renumbered 1 to n |
| Dose and stop rules | After the model | Personal dose numbers, schedules, and telling someone to stop or switch a medicine on their own are replaced with a referral to the doctor or pharmacist. "Ask your doctor before stopping" is allowed |
| Numeric grounding check | After the model | Every number written with a medicine unit or a currency, and every 10-digit register number, must appear in what the tools returned in this run (Arabic-Indic digits and trailing zeros normalized). Otherwise the answer is withheld instead of shown with an invented fact |
| Labelling | Response | `grounded` when registry records are cited, `general` for general medicine information, `urgent` for emergencies, `refused` when a rule replaced the text |

## 7. Observability

- **Structured assistant events**: one JSON log line per question on the `pharmavique.assistant` logger with
  the outcome, level, spoken flag, tools called, tool errors, latency, model, input and output tokens,
  number of citations, question length and the number of ungrounded facts. The question and answer text,
  images and audio are never logged.
- **Metrics** at `GET /metrics` in the Prometheus text format:

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | counter | `route`, `status` |
| `http_request_seconds` | histogram | `route` |
| `assistant_answers_total` | counter | `outcome` (answered, general, emergency, injection, rule_refusal, ungrounded, empty, error) |
| `assistant_guardrail_blocks_total` | counter | `rule` |
| `assistant_tool_calls_total` | counter | `tool` |
| `assistant_tool_errors_total` | counter | none |
| `assistant_tokens_total` | counter | `kind` (input, output) |
| `assistant_latency_seconds` | histogram | none |

- **Request ids**: every response carries `X-Request-ID`, kept from the request when it is safe, otherwise generated.

## 8. Architecture

### 8.1 Style

A **modular monolith** designed with **Domain-Driven Design** and the **onion (clean) architecture**. One
deployable FastAPI service plus background jobs; inside it, bounded contexts that talk only through
published contracts. The architecture is enforced by [`import-linter`](pyproject.toml): eight contracts,
checked on every run and in CI.

| Contract | Rule |
|---|---|
| `onion-layers` | Inside each context, presentation, infrastructure, application, domain: dependencies point inward |
| `presentation-isolation` | Presentation never imports infrastructure or domain directly |
| `infrastructure-not-presentation` | Infrastructure never imports presentation |
| `context-independence` | Contexts never import each other, except allow-listed adapters importing another context's `contracts` |
| `domain-purity` | Domain, application and the shared kernel import no framework: no SQLAlchemy, FastAPI, Pydantic, httpx, LangChain, LangGraph or model SDKs |
| `contracts-are-public-language-only` | Contracts expose no internals and use no frameworks |
| Kernel independence | `shared_kernel` and `foundation` know nothing about contexts or the composition root |
| Composition root | Only process entry points import `bootstrap` |

### 8.2 Bounded contexts

| Context | Responsibility | State |
|---|---|---|
| `catalog` | Product aggregate (registry record, price history, listing status), outbox, read contracts | Done |
| `ingestion` | SFDA crawlers, parsers, anti-corruption layer into the catalog | Done |
| `search` | Normalized product documents, exact and trigram signals, rank fusion | Done |
| `substitution` | Equivalence rules | Done |
| `knowledge` | Cited document chunks, embeddings, hybrid retrieval | Done |
| `assistant` | Response policy, guardrails, citations, the LangGraph agent and its tools | Done |
| `voice` | Speech to text and text to speech | Done |
| `recognition` | Box and prescription reading, candidates, review rules | Done |
| `media` | Product picture pipeline (shop sitemaps, OCR verification, placeholders) | Done |
| `interactions` | Ingredient name matching, drug-drug pairs, contraindications, duplicate ingredients | Done |
| `identity` | Accounts, tenants, roles | Planned |
| `watchlist` | Alerts on a user's medicines (recalls, price changes) | Planned |
| `analytics` | Company analytics and the operator's quality board | Built (read model, company and operator endpoints) |

Shared building blocks: `shared_kernel` (market, currency, money, provenance, Arabic and Latin text
normalization), `foundation` (database engine, throttling, robots rules, concurrency helpers) and
`bootstrap`, the single composition root that wires adapters, settings and HTTP routers.

### 8.3 Layers inside every context

```mermaid
flowchart TB
    subgraph ctx[One bounded context]
        P[presentation: HTTP and CLI adapters] --> I[infrastructure: Postgres, HTTP providers, LangGraph]
        I --> A[application: use cases and ports]
        A --> D[domain: entities, value objects, rules, events]
        C[contracts: published language]
    end
    B[bootstrap: composition root] --> P
    B --> I
```

### 8.4 Context map

```mermaid
flowchart LR
    ingestion -- commands through the anti-corruption layer --> catalog
    search -- read contract --> catalog
    catalog -- domain events through the outbox --> watchlist
    bootstrap{{bootstrap}} --> assistant
    bootstrap --> recognition
    assistant -. DrugFacts port .-> search
    assistant -. DrugFacts port .-> catalog
    assistant -. DrugFacts port .-> substitution
    assistant -. DrugFacts port .-> knowledge
    assistant -. DrugFacts port .-> interactions
    bootstrap --> interactions
    recognition -. CandidateFinder port .-> search
```

### 8.5 Domain-Driven Design building blocks

| Concept | Where |
|---|---|
| Aggregate with invariants and optimistic concurrency | `catalog/domain/product.py` (`Product`, versioned) |
| Value objects | `IngredientLine`, `Money`, `Currency`, `Provenance`, `Strength`, `Citation`, `ExtractedLine` |
| Domain events and transactional outbox | `catalog/domain/events.py`, `catalog/infrastructure/persistence/outbox.py` |
| Repository and unit of work | `catalog/infrastructure/persistence/` |
| Anti-corruption layer | `ingestion` maps SFDA pages into catalog commands |
| Published language | the `contracts` package of each context |
| Ports and adapters | every external capability (database, crawler, model, voice, vision) |
| One schema per context | `catalog`, `search`, `knowledge`, `interactions`; no cross-schema keys or joins |

### 8.6 Scalability

- Stateless API processes behind a load balancer; configuration from the environment.
- PostgreSQL with per-context schemas, trigram and vector indexes; Redis for queues and caches.
- Crawls, OCR and embeddings run as resumable background jobs.
- The outbox decouples contexts, so any context can later move to its own service without changing its
  domain ([ADR-001](docs/adr/ADR-001-modular-monolith-vs-microservices.md),
  [ADR-004](docs/adr/ADR-004-scalability.md)).
- Provider failures degrade gracefully: vision falls back across models, retrieval falls back to text
  search, each AI feature answers 503 until its key is configured while the rest keeps working.
- **What is built today, and what is not:** the API is stateless, queries are indexed and
  parameterised, and with `PHARMAVIQUE_REDIS_URL` set the instances share the rate limit, a versioned
  read cache for search and drug pages, spoken-answer links and a background job queue for scans and
  assistant questions (Arq workers, [ADR-012](docs/adr/ADR-012-shared-state-read-cache-and-jobs.md));
  measured baselines are in [docs/PERFORMANCE.md](docs/PERFORMANCE.md). Not built: shared storage for
  pictures (the API serves them from `PHARMAVIQUE_MEDIA_DIR`), Redis failover, database replicas and
  PgBouncer, a CDN, and the app does not call the jobs endpoints yet.

## 9. Data

### 9.1 Sources

The registry and the lists come from the official SFDA website, crawled politely: robots.txt respected,
requests throttled with jitter, crawls stop on blocks and never touch CAPTCHA-protected forms. Those records
keep their provenance and the trust level `official`. Outside sources are marked `unofficial_unverified`.

| Source | Records | Used for |
|---|---|---|
| Registered drugs list and details (Arabic and English) | 9,162 | Catalog, search, drug page, assistant |
| Drug safety alerts | 276 | Safety intelligence, knowledge base |
| Drugs circulars and withdrawals | 146 | Recalls, knowledge base |
| Drug safety labeling updates | 241 (of 261 listed by the site) | Knowledge base |
| Risk minimization measures | 578 | Patient safety center, knowledge base |
| Drug shortages, current and resolved | 723 and 586 | Shortage status |
| Letters to healthcare professionals | 105 | Knowledge base |
| Drug companies | 6,135 | Company views |
| Licensed pharmacies | 385 | Pharmacy finder |
| New drug approvals | 462 | New-product radar |
| DDInter 2.0 (outside) | 234,757 pairs | Interaction check |
| MeDIC (outside) | 3,960 drug-disease records | Contraindications |
| US drug labels through openFDA (outside) | 871 ingredients, 6,478 chunks | Assistant text, always quoted as a US label |
| Saudi pharmacy sitemaps (outside) | Nahdi, United, Aljawaher, Raf, Medon, Aster, The Outlet, Adam | Product pictures |

### 9.2 Provenance on every record

`source`, `source_ref` (URL or file), `fetched_at`, `snapshot_id` and `trust`. Currencies are never assumed
silently: the SFDA list does not state a currency, so prices carry the basis `owner_assumption` (SAR) and
the app labels them as assumed.

### 9.3 Pipeline

```mermaid
flowchart LR
    S[SFDA website] --> L[list pages] --> R[records.jsonl]
    R --> DT[detail pages]
    R --> F[linked documents]
    F --> T[PDF text]
    T --> O[OCR for scanned files]
    R --> C[(catalog)]
    C --> SI[(search index)]
    DT --> K[(knowledge chunks)]
    O --> K
    K --> E[embeddings]
```

### 9.4 Dataset in the repository

Everything needed to run on another machine is versioned in the repository: clone it and restore the
database snapshot. [`data/README.md`](data/README.md) explains every folder, its source, size and the
command that rebuilds it. In short: `data/sfda` (registry), `data/lists` (SFDA lists), `data/media`
(picture mapping and records, shop sitemaps), `data/interactions` (DDInter, MeDIC), `data/knowledge` (US label
text), `data/db` (database snapshot, one file per schema) and `data/exports` (a flat catalog CSV).

## 10. Tech stack

| Layer | Technology |
|---|---|
| Language and tooling | Python 3.12, uv, ruff, mypy (strict), import-linter, pytest, hypothesis |
| API | FastAPI, Pydantic, Uvicorn |
| Persistence | PostgreSQL 17 with `pg_trgm` and `pgvector`, SQLAlchemy (async), Alembic |
| Queues and cache | Redis |
| Crawling | Playwright (headless Chromium), BeautifulSoup, pypdf, Windows OCR for scanned PDFs |
| AI orchestration | LangGraph, LangChain Core, LangChain OpenAI (OpenAI-compatible endpoints) |
| Model providers | Groq, OpenRouter, ElevenLabs |
| Mobile and web app | React Native with Expo (Expo Router), TypeScript, Phosphor icons, IBM Plex Sans Arabic and Inter |
| Infrastructure | Docker Compose (Postgres, Redis, API), GitHub Actions CI |

## 11. Getting started

### 11.1 Requirements

Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, Node.js 20 or newer, and for the phone the
Expo Go app.

### 11.2 Backend

```bash
cp .env.example .env                      # set the Postgres password and the provider keys you have
uv sync                                   # Python dependencies
docker compose up -d db redis             # PostgreSQL (pg_trgm, pgvector) and Redis
uv run alembic upgrade heads              # every context's schema
```

### 11.3 Load the data shipped in the repository

Fastest: restore the database snapshot kept in the repository (catalog, search index, SFDA lists,
interaction data, pictures mapping and knowledge vectors), then skip the commands below.

```bash
bash scripts/db_restore.sh            # restores data/db/<schema>.dump, one file per schema
bash scripts/db_snapshot.sh           # after changing data, refresh the snapshot before committing
```

Or rebuild everything from the raw files:

```bash
uv run pharmavique sfda-load --run-id full-20261116 --from-records   # 9,144 drugs into the catalog
uv run pharmavique search-reindex                                     # the search index
uv run pharmavique sfda-lists-load --run-id lists-1                   # SFDA lists, linked to products
uv run pharmavique knowledge-build --run-id lists-1                   # cited chunks for the assistant
uv run pharmavique interactions-load                                  # DDInter pairs (data/interactions/ddinter)
uv run pharmavique interactions-load-medic                            # MeDIC contraindications
uv run pharmavique knowledge-labels                                   # US label chunks (cached in data/knowledge)
uv run pharmavique sfda-pictures-load                                 # pictures mapping into the catalog
```

Product picture files are not in git: they ship as the Docker image `ghcr.io/eslamusamaaa/pharmavique-media`.
`docker compose up -d` copies them into the volume the API reads, and `GET /v1/products/{register_number}/picture`
serves them. To run the API outside Docker: `docker compose run --rm -v "$PWD/data/media/images:/target" media`.

### 11.4 Run the API

```bash
uv run uvicorn pharmavique.bootstrap.api:create_app --factory --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation and `/metrics` for metrics.

### 11.5 Run the app on a phone

```bash
cd mobile
npm ci
EXPO_PUBLIC_API_URL=http://<computer LAN address>:8000 npx expo start
```

Scan the QR code with Expo Go. The phone and the computer must be on the same network. For a browser,
run `npx expo start --web --port 8081`.

### 11.6 Refresh the SFDA data

```bash
uv run pharmavique sfda-update --run-id <new run id>     # drug registry, incremental
bash scripts/recollect_safety_lists.sh                    # the six safety lists, end to end
```

**Daily refresh.** `scripts/daily_refresh.ps1` runs the whole routine and writes a log and a summary per
step under `data/refresh/<date>/` (git-ignored): drugs and prices (`sfda-update`, load, search reindex),
the fast lists (shortages, safety notices, approvals, circulars), pictures for new drugs, and on Sundays the
shops' sitemaps and missing pictures. It is polite, safe to repeat, never overlaps itself, and a failing
step does not stop the next one. On Windows register it once with
`.\scripts\schedule_daily_refresh.ps1 -Time 03:00`; on a server run it from cron or a scheduled container
(the drug update needs Chromium, so it belongs in a worker image, not the API image). The daily snapshots
live in the database; only the baselines `full-20261116` and `lists-1` are committed.

## 12. Configuration reference

All settings are environment variables with the `PHARMAVIQUE_` prefix, read from `.env`. Secrets are never
committed; [`.env.example`](.env.example) lists every variable with placeholders.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none | PostgreSQL connection (async driver) |
| `REDIS_URL` | none | Redis connection: shared rate limit, read cache, audio links, job queue (use `127.0.0.1`, not `localhost`, on Windows) |
| `CACHE_TTL_SECONDS` | `600` | How long a cached search or drug-page answer lives at most |
| `TRUSTED_PROXY_HOPS` | `0` | Reverse proxies of ours in front of the API (1 behind one load balancer) |
| `JOB_BACKEND` | `inline` | `inline` runs jobs in the API process; `arq` hands them to `pharmavique worker` |
| `JOB_MAX_CONCURRENCY`, `JOB_TIMEOUT_SECONDS`, `JOBS_PER_USER_PER_MINUTE`, `JOB_MAX_QUEUE_DEPTH` | `8`, `90`, `6`, `500` | Worker concurrency and timeout, submissions per caller, queue ceiling |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | `10`, `20` | Database connections per API process |
| `JWT_SECRET` | none | Signs access tokens, at least 32 random characters; without it the account endpoints answer 503 |
| `CORS_ORIGINS` | local app origins | Browser origins allowed to call the API |
| `RATE_LIMIT_PER_MINUTE` | `300` | Requests per minute per client address; `0` turns it off |
| `HEAVY_RATE_LIMIT_PER_MINUTE` | `30` | The same for the assistant, voice and scan endpoints |
| `MEDIA_DIR` | `data/media` | Folder with the product picture files the API serves |
| `GROQ_API_KEY` | none | Assistant model, prompt guard, speech to text, optional voice |
| `OPENROUTER_API_KEY` | none | Embeddings and vision models |
| `ELEVENLABS_API_KEY` | none | Saudi Arabic voice |
| `LLM_PROVIDER` | `groq` | `groq` or `openrouter` |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Language model with tool calling |
| `PROMPT_GUARD_MODEL` | `meta-llama/llama-prompt-guard-2-86m` | Injection classifier; empty disables it |
| `EMBEDDING_MODEL` | `baai/bge-m3` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1024` | Vector size stored in pgvector |
| `VISION_MODELS` | three free vision models | Tried in order for scans |
| `STT_MODEL` | `whisper-large-v3-turbo` | Speech to text |
| `TTS_PROVIDER` | `elevenlabs` | `elevenlabs` or `groq` |
| `ELEVENLABS_MODEL` | `eleven_v3` | ElevenLabs model |
| `ELEVENLABS_VOICE_ID` | a default voice | Set to a Saudi Arabic voice from the ElevenLabs voice library |
| `TTS_MODEL` | `canopylabs/orpheus-arabic-saudi` | Groq voice model |
| `TTS_VOICE` | `noura` | Groq Saudi voice: abdullah, fahad, sultan, lulwa, noura or aisha |

## 13. Command line reference

| Command | Purpose |
|---|---|
| `pharmavique sfda-scrape --run-id ID` | Full crawl of the registered drugs list (resumable) |
| `pharmavique sfda-update --run-id ID` | Incremental refresh against the latest run |
| `pharmavique outbox-relay [--once]` | Deliver the catalog's events to subscribers (the watchlist makes alerts); the daily refresh runs it with `--once` |
| `pharmavique worker` | Run background jobs (scans, assistant) from the Redis queue; the API needs `PHARMAVIQUE_JOB_BACKEND=arq` |
| `pharmavique cache-invalidate` | Make cached search and drug-page answers stale (the daily refresh and the relay do it) |
| `pharmavique geocode-cities` | Find one point per city that has licensed pharmacies (OpenStreetMap, one request a second, city names only); run once, rerun when a city appears |
| `pharmavique analytics-rebuild` | Rebuild the company views' read model from the catalog (the daily refresh runs it) |
| `pharmavique create-operator --email E` | Create an operator account (password from a prompt or `PHARMAVIQUE_OPERATOR_PASSWORD`) |
| `pharmavique sfda-diff --old A --new B` | Changes between two runs |
| `pharmavique sfda-load --run-id ID [--from-records]` | Load a run into the catalog |
| `pharmavique sfda-lists [--lists a,b]` | Crawl the other SFDA lists |
| `pharmavique sfda-list-details`, `sfda-list-files`, `sfda-list-texts`, `sfda-list-ocr` | Detail pages, documents, PDF text, OCR |
| `pharmavique sfda-lists-load --run-id ID` | Load the lists and link rows to products |
| `pharmavique knowledge-build --run-id ID` | Cut official documents into cited chunks |
| `pharmavique search-reindex` | Rebuild the search index |
| `pharmavique search "query"` | Try the search from the terminal |
| `pharmavique sfda-images*` | Product picture pipeline (`--from-sitemap-pictures` takes pictures from the shops' sitemaps with no page requests) |
| `pharmavique sfda-pictures-load` | Load the drug-to-picture mapping into the catalog |
| `pharmavique interactions-load` | Load DDInter's interaction pairs |
| `pharmavique interactions-load-medic` | Load MeDIC's drug-disease contraindications |
| `pharmavique knowledge-labels` | Fetch US label sections per ingredient (openFDA) and chunk them |
| `pharmavique knowledge-embed` | Give every knowledge chunk a vector |

## 14. API reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/auth/register` | Create an account (role patient, pharmacist or company); returns a session |
| POST | `/v1/auth/login` | Sign in; returns a session (access token valid 15 minutes, refresh token 30 days, used once) |
| POST | `/v1/auth/refresh` | Swap a refresh token for a new session |
| POST | `/v1/auth/logout` | End the session of a refresh token |
| GET | `/v1/auth/me` | The signed-in account (Bearer token) |
| DELETE | `/v1/auth/me` | Delete the account and its sessions |
| GET | `/v1/ingredients?q=` | Active ingredient names that start with the text (for the allergy picker) |
| GET, PUT, DELETE | `/v1/me/medicines[/{register_number}]` | My saved medicines, each with its allergy matches (Bearer token) |
| GET, PUT, DELETE | `/v1/me/allergies` | My recorded allergies, by active ingredient name |
| GET | `/v1/me/allergy-check/{register_number}` | Does this medicine contain an ingredient I recorded an allergy to (by name; never a clearance) |
| GET | `/v1/me/alerts` | Alerts about my saved medicines, with the unread count |
| POST | `/v1/me/alerts/read` | Mark one alert, or all of them, as read |
| GET | `/v1/me/digest?days=7` | What changed for my saved medicines, with a template summary |
| GET | `/v1/company/market?ingredient=` | Market map: products, makers, forms, strengths and price ranges per ingredient set (company or operator role) |
| GET | `/v1/company/gaps?ingredient=&thin_at=` | Strengths and forms with few registered makers, and strength and form pairs that never meet |
| GET | `/v1/company/radar?ingredient=&days=` | New, withdrawn, relisted and repriced products lately |
| POST | `/v1/jobs/scan`, `/v1/jobs/assistant` | Start a slow job; answers 202 with a job id |
| GET | `/v1/jobs/{id}` | The job's state and, when done, the same JSON as the direct endpoint |
| POST | `/v1/pharmacies/nearby` | Licensed pharmacies by city, nearest city first; the position is in the body and is never stored, logged or cached |
| GET | `/v1/pharmacies/cities`, `/v1/pharmacies?city=&region=&q=` | Cities with pharmacies, and a search with no position |
| PUT | `/v1/me/medicines/{n}/status` | Mark a saved medicine as one I take now (`current`) or took before (`past`) |
| GET | `/v1/me/history/check/{n}` | A drug against the medicines I take now: recorded interactions, duplicate ingredients, my allergies (never advice) |
| GET | `/v1/me/history/interactions` | Recorded interactions among the medicines I take now |
| GET | `/v1/operator/quality` | Data-quality counts, official-list linking, refresh status (operator role) |
| GET | `/health` | Liveness |
| GET | `/metrics` | Prometheus metrics |
| GET | `/v1/search?q=&limit=&include_withdrawn=` | Find drugs by name, ingredient or register number |
| GET | `/v1/products/{register_number}` | Product card |
| GET | `/v1/products/{register_number}/details` | Drug page: every field with provenance |
| GET | `/v1/products/{register_number}/same-ingredient` | Same ingredient set, cheapest first, with verdict |
| GET | `/v1/products/{register_number}/picture` | The drug's real pharmacy picture (404 when it has none) |
| GET | `/v1/products/{register_number}/shortage` | Whether SFDA lists the drug as short (with how sure the link is) and the same-ingredient products, each with its computed verdict |
| GET | `/v1/products/{register_number}/similar-names` | Drugs whose names are spelled or sound alike (informational, not reviewed by a pharmacist yet) |
| GET | `/v1/compare?a=&b=` | Two drugs side by side: facts, the fields that differ, and the computed equivalence verdict |
| POST | `/v1/interactions/check` | Recorded interactions and duplicated ingredients among 2 to 20 products |
| GET | `/v1/interactions/contraindications/{register_number}` | Conditions the product's ingredients are contraindicated with, with label text and source |
| POST | `/v1/assistant/ask` | Cited answer to a question |
| POST | `/v1/voice/transcribe` | Audio upload to text |
| POST | `/v1/voice/drug-name` | The drug name inside a spoken request, to search for |
| POST | `/v1/voice/speak` | Text to audio in the Saudi Arabic voice; with `as_link` a one-time link for the app's player |
| GET | `/v1/voice/audio/{key}` | Fetch a spoken answer once (expires after 10 minutes) |
| POST | `/v1/recognition/scan?kind=box` or `kind=prescription` | Photo to medicine lines with registry candidates |

Example: ask the assistant.

```http
POST /v1/assistant/ask
Content-Type: application/json

{"question": "What is the active ingredient of Panadol Extra?", "level": "pharmacist", "spoken": false}
```

```json
{
  "answer": "Panadol Extra contains paracetamol 500 mg and caffeine citrate 65 mg per tablet [1].",
  "citations": [
    {"number": 1, "source_id": "catalog:0206257530", "kind": "catalog",
     "url": "https://www.sfda.gov.sa/en/drugs-list", "published": null, "title": "PANADOL EXTRA TAB"}
  ],
  "grounded": true, "general": false, "urgent": false, "refused": false,
  "level": "pharmacist", "tools_used": ["search_drugs", "drug_details"],
  "disclaimer": "Informational only, not medical advice. ..."
}
```

Example: scan a box.

```json
{
  "kind": "box",
  "status": "needs_review",
  "lines": [{
    "raw_text": "Panadol Extra", "name": "Panadol Extra", "strength": null, "form": "tablet",
    "dose": null, "needs_review": true,
    "candidates": [
      {"register_number": "0206257530", "trade_name_en": "PANADOL EXTRA TAB", "score": 1.0},
      {"register_number": "2207257788", "trade_name_en": "PANADOL EXTEND 665MG F.C. TABLETS", "score": 0.611}
    ]
  }]
}
```

## 15. Testing and quality gates

Run before every commit and in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests            # strict typing
uv run lint-imports              # the eight architecture contracts
uv run pytest                    # unit, architecture and integration tests
cd mobile && npx tsc --noEmit    # the app's types
```

- More than 900 automated tests (83% line coverage): unit tests per layer, architecture tests, and
  integration tests against a real PostgreSQL.
- Tests come before adapters, and every bug fix starts with a failing test.
- Every port has a fake adapter, so AI behaviour (tool calls, citations, guardrails, fallbacks) is tested
  with scripted models and mock HTTP transports, without network access or keys.

## 16. Security and privacy

- No secrets in the repository: keys live only in `.env` and the environment.
- Health data is minimised: photos and audio are processed in memory and dropped with the request;
  questions, answers, images and audio are never logged.
- Provider keys are sent only in the Authorization header of their own provider and never appear in errors.
- Text from official documents is treated as data and never as instructions to the model.
- Crawling is polite: robots.txt, throttling, a clear user agent, stop on blocks, no CAPTCHA bypass.
- The API limits requests per client (lower for the assistant, voice and scan), caps upload sizes and
  restricts browser origins. It has **no sign-in yet**: do not expose it to the internet without a gateway
  that authenticates callers.
- The repository is public and protected: secret scanning with push protection, Dependabot alerts and
  updates, a protected `main` (no force push or deletion), CI with a read-only token and actions pinned to a
  commit. Reporting a vulnerability and the full policy: [SECURITY.md](SECURITY.md).

## 17. Repository layout

```
src/pharmavique/
  <context>/
    contracts/        published language of the context
    domain/           entities, value objects, rules, events
    application/      use cases and ports
    infrastructure/   adapters: Postgres, HTTP providers, LangGraph, crawlers
    presentation/     HTTP and CLI adapters
  shared_kernel/      market, currency, money, provenance, text normalization
  foundation/         database engine, throttling, robots rules, concurrency
  bootstrap/          composition root: settings, API, CLI, observability
tests/
  unit/ · architecture/ · integration/
mobile/               Expo app (Expo Router), right-to-left, light and dark
pharmavique-wireframes/  wireframe canvas and brand assets
data/                 the dataset and the database snapshot (see data/README.md)
docs/                 architecture, ADRs, plans, data sources, media
scripts/              crawl, OCR, daily refresh, database snapshot and restore
migrations/           Alembic environment
```

## 18. Documentation index

| Document | Content |
|---|---|
| [Project brief](docs/PROJECT_BRIEF.md) | Goals, audiences, scope |
| [Architecture](docs/ARCHITECTURE.md) | Contexts, layers, data ownership |
| [AI architecture](docs/AI_ARCHITECTURE.md) | Search, OCR, assistant, retrieval design |
| [Domain model](docs/DOMAIN_MODEL.md) | Aggregates, value objects, invariants |
| [Features](docs/FEATURES.md) | Product decisions |
| [Phase 2 plan](docs/PHASE_2_PLAN.md) | Application and AI plan with the owner's decisions |
| [Phase 3 plan](docs/PHASE_3_PLAN.md) | Accounts, alerts, company views, scale, shortages, compare, LASA, pharmacies |
| [ADR-009](docs/adr/ADR-009-identity-and-sessions.md) | Accounts, roles and sessions |
| [ADR-010](docs/adr/ADR-010-outbox-relay-and-alerts.md) | Outbox relay, watchlist, allergies and alerts |
| [ADR-011](docs/adr/ADR-011-company-views-and-quality-board.md) | Company views and the operator's quality board |
| [ADR-012](docs/adr/ADR-012-shared-state-read-cache-and-jobs.md) | Shared state, read cache and background jobs |
| [ADR-014](docs/adr/ADR-014-medicine-history-as-memory.md) | The patient's medicine history checked against a new drug |
| [ADR-013](docs/adr/ADR-013-pharmacy-finder-and-location.md) | The pharmacy finder and how the person's location is handled |
| [Performance](docs/PERFORMANCE.md) | Measured baselines and what a large deployment needs |
| [Data sources](docs/DATA_SOURCES.md) | Every source and its probe results |
| [SFDA scraper](docs/SFDA_SCRAPER.md) | Crawler behaviour and site quirks |
| [Media pipeline](docs/MEDIA_PIPELINE.md) | Product pictures |
| [UI design and wireframes](pharmavique-wireframes/README.md) | Wireframes, app screens, design system |
| [Data layout](data/README.md) | Every data folder: source, size, rebuild command |
| [Security policy](SECURITY.md) | Reporting, protections, known limits |
| [Open questions](docs/OPEN_QUESTIONS.md) | Unknowns waiting for decisions |
| [ADR-001](docs/adr/ADR-001-modular-monolith-vs-microservices.md) · [002](docs/adr/ADR-002-job-queue.md) · [003](docs/adr/ADR-003-search-strategy.md) · [004](docs/adr/ADR-004-scalability.md) · [005](docs/adr/ADR-005-ai-providers-behind-ports.md) · [006](docs/adr/ADR-006-pgvector-and-document-chunks.md) · [007](docs/adr/ADR-007-langgraph-in-infrastructure.md) · [008](docs/adr/ADR-008-interactions-context.md) | Architecture decision records |

## 19. Roadmap

1. Schedule the daily refresh and show changes (price changes, new and withdrawn drugs) to pharmacists and companies.
2. Accounts, tenants and roles with sign-in on the API; alerts on a user's medicines through the outbox relay.
3. Drug-food and drug-condition notes beyond the contraindication list; ingredient allergy in "my medicines".
4. Shared storage for pictures; the app uses the jobs endpoints; email verification and notifications; the patient's medicine history as memory.
5. Egypt as a CSV-import adapter marked unverified.

## 20. Disclaimer

Pharmavique provides information from official registry data and public SFDA publications. It is not
medical advice and does not replace a doctor or a pharmacist. It never gives a personal dose and never
tells anyone to stop or switch a prescribed medicine.
