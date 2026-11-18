# AI architecture: OCR, retrieval and the assistant (DRAFT for approval)

Status: **proposal, nothing built.** It follows the owner's decisions in `docs/FEATURES.md` (2026-11-17) and the rules in `CLAUDE.md`. Anything marked **[Q]** is an open question; nothing here asserts a provider's capability or price.

## 1. What is decided already

- Box photo: plain OCR reads the text on the box, then the **same fuzzy search as typed text** finds the product. No product-recognition model.
- Prescription photo: handwriting OCR, extract drug names, look each up in our data, the **pharmacist confirms** before anything is answered.
- Shelf scan: the owner wants whole-shelf photos where each drug name is readable.
- RAG is over **our own catalog data**, not leaflets. Agentic RAG is wanted: an LLM that picks among read-only tools and answers with citations.
- Equivalence is computed by our deterministic code (`substitution`), never decided by the LLM. No medical advice. Uploads are deleted after processing unless the user opts in.

## 2. The one idea that keeps this safe: models read, code decides

| Step | Done by | Never done by |
|---|---|---|
| Turn pixels into text lines | OCR / vision model (`VisionReader` port) | the catalog |
| Decide which product the text means | `search`: hybrid retrieval (fuzzy lexical and semantic signals fused), scored in our code | the vision model guessing a drug from its own knowledge |
| Confirm the match | the pharmacist or patient, in the UI | any model |
| Equivalence, price, status | `catalog` and `substitution` | the LLM |
| Phrase an answer and pick which tool to call | the LLM (`Assistant`) | deciding facts: every fact in an answer must carry a record id |

The vision model is told to **transcribe**, not to identify. Matching is ours, so a wrong guess shows up as a low match score and a confirmation prompt, not as a confident wrong drug.

## 3. Contexts (changes to `ARCHITECTURE.md` section 2.1)

| Context | Change | Owns |
|---|---|---|
| `recognition` | Defined in detail below | `RecognitionJob` aggregate, extracted lines, match candidates, the `VisionReader` port |
| `search` | Gains the semantic part of retrieval | Normalized names, aliases, trigram index, **embeddings** (pgvector), hybrid ranking. This **is** the "R" of the RAG: the assistant's search tool calls it |
| `assistant` (new) | Replaces `knowledge` for now | Conversations, the tool-using loop, tool registry, citations, guardrails, usage and cost ledger, the `LanguageModel` port |
| `knowledge` | **Parked.** Leaflet chunks only make sense once a leaflet source exists (Q-24). Keep the name free for then | nothing |

Dependencies (consumer to provider, through `contracts` only, allow-listed in `pyproject.toml`):

```
recognition -> search.contracts (candidates), catalog.contracts (details)
assistant   -> search.contracts, catalog.contracts, substitution.contracts, watchlist.contracts (history/alerts)
```

`assistant` and `recognition` never see each other. A prescription result can be sent to the assistant by the UI as plain confirmed product ids.

## 4. Onion layout for the two new contexts

```
recognition/
  contracts/     StartRecognition, RecognitionResult, RecognitionCompleted (integration event)
  domain/        RecognitionJob (aggregate), ExtractedLine, MatchCandidate, Confidence, JobStatus
  application/   StartRecognitionHandler, ProcessRecognitionHandler, ConfirmLinesHandler,
                 ports: VisionReader, ImageStore, CandidateFinder, JobRepository, Clock
  infrastructure/ vision adapters, object-storage image store, search adapter (over search.contracts),
                 SQLAlchemy repository, Alembic migrations (schema "recognition")
  presentation/  HTTP: POST /recognitions, GET /recognitions/{id}, POST /recognitions/{id}/confirm

assistant/
  contracts/     AskAssistant, AssistantAnswer (text + citations)
  domain/        Conversation (aggregate), Turn, Citation, Budget, ToolCallRecord
  application/   AnswerQuestionHandler (the loop), ToolRegistry, GuardrailPolicy,
                 ports: LanguageModel, CatalogTools (search, product, equivalents, prices, history),
                 ConversationRepository, UsageLedger, Clock
  infrastructure/ model adapters, tool adapters over other contexts' contracts, repository, migrations
  presentation/  HTTP: POST /conversations/{id}/messages (streaming later)
```

`domain` and `application` import no framework and no model SDK. The vision and language models are adapters; replacing a provider is one new adapter plus a configuration change.

### 4.1 `RecognitionJob` state machine

```
queued -> processing -> needs_review -> confirmed
                    \-> failed
queued/processing -> timed_out          (provider too slow: "try again or search manually")
any non-final -> expired                (image deleted, nothing kept)
```

Invariants: the image is deleted when the job reaches a final state unless the user opted in; a line below the confidence threshold or with a look-alike name (LASA) can never be auto-confirmed; `confirmed` needs an explicit user action.

## 5. Data model (one Postgres schema per context, no cross-schema keys)

`recognition`
- `job` (id, tenant_id, user_id, kind `box|prescription|shelf`, status, image_key, image_expires_at, opted_in_retention, created_at, finished_at, provider, model_version)
- `extracted_line` (job_id, position, raw_text, normalized_text, language, confidence, bbox nullable)
- `match_candidate` (line_id, product_id, score, signals json: which of exact, trigram, vector, alias fired), `chosen_product_id` nullable, set only on confirmation

`search` (adds to what ADR-003 defines)
- `product_document` (product_id, market, normalized_names, aliases, document_text, `embedding vector(N)` nullable, embedding_model, embedded_at). The dimension N and model are **[Q-12]**; a changed model means a re-embed job, never an in-place edit.
- `alias` (product_id or ingredient, alias, language, source)

`assistant`
- `conversation` (id, tenant_id, user_id, created_at, expires_at)
- `turn` (conversation_id, role, text, created_at): user text can contain health context, so retention is short by default and it is never written to application logs
- `tool_call` (turn_id, tool, arguments json, result_ref, duration_ms): the trace used for audit and evaluation
- `usage` (tenant_id, day, input_tokens, output_tokens, cost_estimate): the cost cap reads this

Images live in object storage (`ObjectStorage` port), encrypted at rest, keyed by job id, with a lifecycle rule as a backstop to the application's own deletion.

## 6. Retrieval ("RAG over the catalog")

**Owner decision (2026-11-17): hybrid RAG plus agentic RAG.** Retrieval is hybrid by default, not "semantic as a last resort". Every query runs all the signals and a fusion step ranks the union:

1. **Exact** lookups short-circuit when they hit: registration number, barcode.
2. **Fuzzy lexical**: trigram similarity on normalized names and aliases, Arabic and English (ADR-003, spike 001 passed locally). This is what survives misspellings and OCR errors in brand names.
3. **Semantic**: vector search over a short, normalized "product card" text (names, ingredients, strengths, form, company). It carries free-text and descriptive questions ("a cough syrup with dextromethorphan"). Brand names are poor embedding material, so the semantic signal alone never identifies a product; it adds candidates and evidence.
4. **Fusion**: reciprocal rank fusion first (no score calibration needed), a weighted score only if the evaluation set shows it wins. Each result keeps the per-signal ranks so the explanation ("matched by name 0.82, by meaning 0.64") can be shown and tested.
5. Weights, thresholds and the fusion choice are tuned on the evaluation set (section 9), not by feel.

The agentic layer (section 7) sits on top: the assistant decides *which* retrieval tool to call and how to combine results across several calls (search, then details, then equivalents), but each tool call is this same hybrid retrieval or a deterministic query.

Every assistant answer is assembled **from records the tools returned**. Each claim carries the record's id, source and snapshot (our existing provenance). If a tool returns nothing, the answer says so; there is no fallback to the model's own memory.

## 7. The assistant loop (agentic RAG)

Tools, all read-only, tenant-scoped, defined as typed contracts (no free text, no SQL):

| Tool | Backed by |
|---|---|
| `search_products(query, market, filters)` | `search.contracts` |
| `get_product(id)` | `catalog.contracts` |
| `find_equivalents(id)` | `substitution.contracts`: returns `equivalent` or `possible, needs pharmacist check`, never the LLM's opinion |
| `compare_prices(ids)` | `catalog.contracts`, with the currency basis shown (SAR is the owner's assumption) |
| `product_history(id)` | catalog change history |
| `company_analytics(query_name, params)` | predefined analytics queries, company role only |

Guardrails (enforced in code, not only in the prompt): maximum steps and wall-clock time per question, a per-tenant daily cost cap, no tool outside the registry, answer schema requires citations, a medical-advice detector routes to "ask your pharmacist or doctor", and **text coming from the catalog is treated as data**: SFDA fields are never allowed to act as instructions. Streaming and conversation memory come after the first non-streaming version works.

## 8. Vision provider choice (the part we cannot decide yet)

`VisionReader` returns lines of text with a confidence and, when available, positions. Three kinds of adapter can sit behind it, and we pick by **measuring on our own photos**, not by reputation:

| Option | Strength | Risk |
|---|---|---|
| A. A hosted vision-language model | Handles messy photos and handwriting; one integration | Photos leave our infrastructure (Q-9, Q-12); cost per image; provider latency and outages |
| B. A dedicated OCR engine we host | Data stays with us; predictable cost | Arabic handwriting quality unknown; needs hosting and maybe a GPU |
| C. Both: B first, A as a fallback for low-confidence images | Cost and privacy of B, quality of A when needed | Two adapters to maintain |

Recommendation: build the port and a **fake adapter** first, build the evaluation set, then try A and B on it. The decision becomes ADR-005 with real numbers. Whichever wins, the pipeline is the same: transcribe, normalize Arabic, search, score, ask the user to confirm.

## 9. Evaluation comes before the models

We have **no photos yet**. Without them any model choice is a guess. Proposed sets, owned by the repo (`tests/eval/`, images kept out of git):

- Box photos: name, strength and form correct on a ground-truth sheet.
- Prescriptions (handwritten, Arabic and English, and printed).
- Shelf photos.
- Assistant questions with the expected tool calls and citations.

Metrics: line-level text accuracy, **top-1 and top-3 product match rate**, share of wrong-but-confident matches (the number that matters most), latency, cost per image, refusal correctness for medical-advice questions, and citation coverage for assistant answers. A release gate fails if wrong-but-confident matches rise.

## 10. Scalability and operations (ADR-004 applies)

- Recognition and embedding run as jobs on their own worker pools (ADR-002), never inside a request; the API returns a job id and the client polls or receives a webhook.
- Per-user rate limits and queue back-pressure at admission; a provider timeout produces `timed_out`, not a hung request.
- Provider calls are throttled and retried with a circuit breaker; no provider key in the repo, only environment variables.
- The assistant is a stateless request handler plus Postgres; scale is more API processes. Token and cost metrics per tenant feed the daily cap.
- The embedding index is a rebuildable projection of catalog events, so it can move to a separate service or store later without changing the contracts.

## 11. Build order and status

Owner decision (2026-11-17): **no agentic layer until retrieval has been tried and measured.** Order, with what is done:

| # | Step | Status |
|---|---|---|
| 1 | `search`: text normalizer (Arabic and Latin) | done, tested |
| 2 | `search`: rank fusion (RRF) with reasons | done, tested |
| 3 | `search`: trigram similarity in pure Python, indexed document, ports, query and rebuild use cases, in-memory index with exact and fuzzy signals | done, tested |
| 4 | `catalog`: read contract (product cards, paged export) and its Postgres reader | done and tested on Postgres |
| 5 | `search`: adapter over the catalog's contract, Postgres projection (`pg_trgm`, schema `search`, migration `search_0001`), `search-reindex` and `search` commands | done; 9,145 SFDA drugs indexed; 13 Postgres tests incl. ranking parity with the in-memory reference |
| 6 | Evaluation of names and misspellings; tune; decide whether the semantic signal earns its place | started: 300 generated misspellings of real names; adding the brand part of the registry name to the searchable terms moved recall@1 from 76% to 96% and recall@10 from 87% to 100%. A fixed, labelled evaluation set (real user typos, OCR errors) is still to be built |
| 7 | `recognition` with a fake `VisionReader`; the job state machine; image deletion | after 6 |
| 8 | Photos collected and labelled; real vision adapters chosen by the harness (ADR-005) | needs Q-32 |
| 9 | Semantic signal (embeddings) only if step 6 shows it helps (ADR-006) | measured |
| 10 | `assistant` (agentic loop over the same tools) | only after the above are measured |
| 11 | `media` (product pictures) | blocked by Q-35 |

## 12. Assumptions

- Traffic starts small; one Postgres with pgvector is enough until measurements say otherwise (ADR-003, ADR-004).
- Owner provides sample photos or agrees to collect some (section 9).
- The assistant starts non-streaming and without long-term memory.

## 13. Open questions

| # | Question | Why it matters |
|---|---|---|
| Q-9, Q-12 | May photos go to an external provider, and from which region? Legal review is still pending | Decides option A, B or C in section 8 |
| Q-30 | Is there a budget for hosted model calls, and a per-user or per-tenant cap? | The cost cap in section 7 needs a number |
| Q-31 | Can we get a GPU or must everything run on CPU or hosted APIs? | Decides whether option B is realistic |
| Q-32 | Who supplies the first 100 or more real box and prescription photos, and who labels them? | Without them there is no honest model choice |
| Q-33 | Which languages and handwriting styles are expected on prescriptions (Arabic, English, mixed)? | Sets the evaluation set and the thresholds |
| Q-34 | Should the assistant keep conversation history after the session, and for how long? | Health data retention; default is short expiry |

## 14. Product images from the web (owner request, 2026-11-17)

**Not to be confused with section 5.** The images in object storage there are the photos a *user* uploads (a box, a prescription, a shelf) and they are deleted after processing. This section is about *reference pictures of each drug's pack*, found on the internet and kept as catalog content.

The idea: for each drug we crawled, search for pictures by trade name and active ingredient, check that a picture really shows that product, and store it with provenance.

### 14.1 Shape

A new context, `media`, owns the images and their verification; `catalog` stays free of binary content. A job per product runs: **find candidates, download, verify, store**, and publishes `ProductImageVerified` so the UI and search can use it.

Verification reuses the `VisionReader` port (section 8): it transcribes the text on the picture, and our code compares it with the catalog record (trade name, strength, dosage form, manufacturer). Outcomes:

| Status | Meaning |
|---|---|
| `verified_by_text` | name and strength both read from the picture and both match the record |
| `needs_review` | partial match (name only, or low confidence); a person decides |
| `rejected` | text contradicts the record, or a different product |

Never decided by "the picture looks similar". A rejected or unreviewed picture is never shown as that product. Each stored image carries source page URL, image URL, fetched_at, licence as found (or `unknown`), content hash (duplicates dropped), the verification result, and `trust = unofficial_unverified` until a person confirms.

### 14.2 What blocks the downloading part (not the design)

- **Rights.** A picture on a web page is usually someone's copyrighted work. Showing it in a product people use needs a licence or permission. I have not checked the terms of any source.
- **How to search.** Scraping the result pages of general search engines is against their terms and runs into CAPTCHAs, which we never bypass (project rule). The legitimate routes are an image-search API used under its terms, sources that publish reusable images, or asking manufacturers and distributors for their pack shots.
- **SFDA itself has no product images** (800 detail pages were checked).

So the first step is only the port, the verification logic and the job, tested with fake sources. **Nothing is downloaded until the owner decides which sources are allowed (Q-35).**

### 14.3 Scale

About 9,000 drugs and several candidates each means tens of thousands of downloads. They run as throttled jobs on their own worker pool (ADR-002, ADR-004), deduplicated by content hash, resumable, with a per-source politeness limit like the SFDA crawler.

