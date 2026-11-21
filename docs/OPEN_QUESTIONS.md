# Open Questions

| | |
|---|---|
| Date | 2026-11-16 |
| Status | Living document. Each answered question moves to the ADR or doc that depends on it |

Per the working agreements, anything unknown is recorded here instead of being assumed. "Blocks" says which phase or document cannot be finalized without an answer. "Proposed default" is what I will use if you tell me to proceed without an answer; it is never a fact.

---

## A. Design decisions I made that need your confirmation

**Status 2026-11-16: accepted.** You told me to proceed and keep my recommendations, so D-1 to D-8 are treated as approved. They stay listed because each is cheap to reverse now and expensive later.

| ID | Decision | Alternative | Where |
|---|---|---|---|
| D-1 | `catalog` emits `ProductAdded` / `ProductWithdrawn` / `PriceChanged` (atomically with its state change). `ingestion` emits only run-level events. This differs from the brief's wording, which lists change events under `ingestion` | `ingestion` emits them, with a separate mechanism to keep them consistent with catalog | ARCHITECTURE 2.2 |
| D-2 | `presentation` means all inbound adapters: HTTP, the in-process implementation of `contracts`, and event subscribers | Keep `presentation` HTTP-only and add a fifth `inbound` layer | ARCHITECTURE 3 |
| D-3 | `pydantic` is forbidden in `domain` and `application` (DTOs are frozen dataclasses) | Allow pydantic DTOs in `application` | REPOSITORY_STRUCTURE C4 |
| D-4 | `presentation` may not import its own `domain`; clients get enums through application DTOs | Allow read-only imports of domain value objects/enums | ARCHITECTURE 3 |
| D-5 | `analytics` and `search` build their own projection tables from events; no materialized views over other contexts' tables | Read-only published DB views from `catalog` for analytics | ARCHITECTURE 2.2 |
| D-6 | Alembic migrations live inside each context (`infrastructure/migrations`), collected by one root `migrations/env.py`, one schema per context | One central migrations folder | REPOSITORY_STRUCTURE 1 |
| D-7 | Docs are written in English, like the brief; conversation with you is in Arabic | Arabic or bilingual docs | all docs |
| D-8 | Queue = Arq behind a `JobQueue` port, with Postgres-authoritative job state (see ADR-002 and Q-10) | Celery | ADR-002 |

---

## B. Questions about facts I do not have

### Project and team

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-1 | Team size and ops experience; hosting target (cloud provider, regions, managed Postgres/Redis or self-hosted)? | Validates ADR-001's small-team assumption; determines Redis HA/persistence, managed pgvector availability, backups | ADR-001 sign-off, Phase 7 | Small team, containers on a single cloud provider |
| Q-2 | Product and package name. The brief says "Drug Intelligence Platform", the folder is `Pharmavique` | Top-level Python package, image and repo names | Scaffold | `pharmavique` |
| Q-19 | Where will the repo be hosted and which CI will run? The folder is not a git repo yet | CI workflow format, branch protection, PR conventions | Scaffold | GitHub + GitHub Actions |

### SA data (SFDA)

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-4 | Do you already have an SFDA developer-portal key? Is it usable from outside Saudi IP ranges? Can you share a real sample response? | The brief warns the API may be restricted to Saudi IPs, and says never to invent field names. The adapter schema must come from real calls | Phase 1 SA adapter | Build the file-import adapter first and the API adapter after a real sample exists |
| Q-5 | Currency and price units in the SA data? | The SFDA pages show a bare number. **Owner decision 2026-11-17: SAR.** It is stored as SAR with the basis "owner-confirmed assumption, the source does not state it" and the API shows that basis. If SFDA documents a different unit, this is corrected in one place | Phase 1 pricing | SAR, basis shown. What the price unit is for (per pack?) is still unknown |
| Q-22 | Web search features: which sources are allowed (SFDA announcements and recalls, FDA, EMA, WHO, manufacturer sites?), which search provider, and what may be shown? | External pages are `unofficial_unverified`, have their own terms and copyright, and can be wrong | Web search features | Allow-listed official domains only, summaries with links |
| Q-23 | Maps and location: which maps provider, and what happens to the user's location? | Location is sensitive. Costs and terms differ by provider | Pharmacy finder | Location used once per request and not stored; nearest pharmacies only, no stock claims |
| Q-24 | Leaflet RAG was in the brief (Phase 4) but is now out of scope. Confirm, and write the ADR | The assistant answers from catalog data only | Phase 4 | Out of scope until a leaflet source exists |
| Q-25 | SFDA safety bulletins (monthly PDF and circulars pages): what are the exact URLs and publication schedule, may we reuse them, and who reviews the product matches? | Needed for the "why did this drug disappear" feature. Names in the PDF can differ from catalog names, so a person must confirm matches | Safety bulletin feature | Monthly fetch, automatic candidate matching, human review, show the SFDA text with a link and no advice |
| Q-26 | LASA warnings: which similarity measures and thresholds, and who reviews the first list of confusable pairs? | A pharmacist should sanity-check the pairs the first time; too many warnings are ignored | LASA feature | String and phonetic similarity in Arabic and English, tuned on a reviewed sample |
| Q-27 | Which of SFDA's 28 official lists do we add first, and in what order? The shortage list, companies list and safety lists look most valuable | Each list needs its structure, update rate and terms read before any crawl | Next data source | Shortage list, then companies, then safety labeling updates, then the other categories |
| Q-29 | The medical devices (about 160,000), food products (about 1.5 million) and cosmetic products (about 3 million) lists are too large to crawl politely. Do we ask SFDA for a data export, crawl only list pages very slowly over many days, or leave them out for now? | Sustained crawling of millions of pages is a real load on SFDA's site and is not covered by anything we have been told. The Downloadable Information Lists page has no bulk exports | Devices, food and cosmetics coverage | Ask SFDA for an export through its contact form; meanwhile cover only the small and medium lists |
| Q-28 | Where are herbal and supplement products, and drugs imported under special access, registered? No separate list was found (the "Incentive Project List" of unregistered pharmaceuticals may be related) | The owner wants these categories covered; without a source they cannot be | Category coverage | Ask SFDA through its contact form; read the unregistered pharmaceuticals list first |
| Q-30 | Is there a budget for hosted model calls (vision, language, embeddings), and a per-user or per-tenant cap? | The assistant's cost cap needs a number (`docs/AI_ARCHITECTURE.md` section 7) | Before the assistant | Small daily cap per tenant, tracked in a usage table |
| Q-31 | Is a GPU available, or must everything run on CPU or hosted APIs? | Decides whether a self-hosted OCR engine is realistic (`AI_ARCHITECTURE.md` section 8) | Before the vision adapter | Assume no GPU |
| Q-32 | Who supplies the first 100 or more real box, prescription and shelf photos, and who labels them? | Without them there is no honest vision-model choice (`AI_ARCHITECTURE.md` section 9) | Before the vision adapter | The owner collects them, we build the labeling sheet |
| Q-33 | Which languages and handwriting styles appear on prescriptions (Arabic, English, mixed, printed)? | Sets the evaluation set and the confidence thresholds | Before the vision adapter | Assume all of them |
| Q-34 | Should the assistant keep conversation history after the session, and for how long? | History can contain health information | Before the assistant | Short expiry, not logged |
| Q-36 | About three quarters of the drugs have no real picture because no Saudi online shop sells them (infusions, dialysis fluids, local generics). Will the owner ask manufacturers and distributors for pack shots, or keep dosage-form placeholders? | Decides how the rest of the catalog gets pictures (`docs/MEDIA_PIPELINE.md`) | Before pictures are shown to users | Keep the marked placeholders |

### EG data

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-6 | Which third-party EG dataset (name, owner, format, license, last update)? Any request submitted to the Egyptian Drug Authority for an official feed? | Becomes the CSV-import adapter, marked `unofficial_unverified`. No scraping, no CAPTCHA bypass | Phase 2 | CSV adapter only |
| Q-7 | Where do EG prices come from? | The official database page does not appear to show actual prices (per brief) | Phase 2 pricing | EG price fields nullable and `unconfirmed` |

### Legal and privacy

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-9 | Who handles legal review of data-protection obligations in Saudi Arabia and Egypt (national personal-data protection laws and any data-residency or cross-border-transfer rules for health data)? | Affects hosting region, whether images may go to an external vision provider, retention. I am not asserting specific legal requirements; counsel must confirm | Before any real user data (Phase 3 at the latest) | Minimum collection, delete uploads after processing unless opted in |
| Q-20 | Retention periods for personal medicine lists, alerts and (if opted in) stored images? | Needed for schema and deletion jobs | Phase 3 and 5 | Images deleted after processing; lists kept until user deletes |

### Performance and scale

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-11 | Target numbers: concurrent users, requests per second on lookups, photos per minute at peak, p95/p99 latency SLOs, availability target? | Load-test plan, ADR revisit triggers (ADR-001/002/003), cache and index sizing | Phase 1 plan (for SLOs), Phase 7 | None; I will not invent numbers |
| Q-10 | Do you accept Arq despite its maintenance-only status (ADR-002)? | Long-term dependency risk | ADR-002 sign-off | Yes, behind the port with documented exit criteria |
| Q-17 | Which managed Postgres (if any), and does it offer `pg_trgm` and `pgvector`? Which locale/encoding will the database use? | ADR-003 spike: trigram behavior on Arabic text depends on locale settings | Phase 1 | Local Docker image verified (spike 001: `en_US.UTF-8` works for Arabic trigrams). A managed Postgres must repeat the spike |

### AI providers

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-12 | Which vision/VLM provider and embedding model? May prescription or medicine-box photos be sent to an external provider, and from which region? | Privacy exposure, quality, cost, vector dimension. Providers sit behind ports | Phase 3, 4 | Decide after legal review (Q-9) |

### Product and domain

| ID | Question | Why it matters | Blocks | Proposed default |
|---|---|---|---|---|
| Q-15 | What is a "product" across markets: one global product with per-market listings, or independent per-market products linked by mapping? | Catalog aggregates and cross-market name mapping ("what is this called in the other country") | Phase 1 model, Phase 2 | Per-market products first; mapping table in Phase 2 |
| Q-13 | Identity: build auth in `identity` or use an external identity provider? Patient login method? Token revocation strategy? | `Principal` shape in the shared kernel; no per-request call to `identity` means revocation must be designed | Phase 5 (shape needed earlier) | Short-lived JWTs + refresh |
| Q-14 | Tenant isolation: Postgres row-level security or application-level filtering (the brief requires tested row-level isolation)? | Schema and session design for tenant-owned tables | Phase 5 | Row-level security plus repository filters |
| Q-16 | Which clients consume the API first (mobile app, web, partner integrations)? Webhooks vs polling for recognition results? | API shape, CORS, auth flows | Phase 3 | Polling with status endpoint |
| Q-18 | Notification channels for alerts (push, SMS, email, messaging apps)? | `NotificationSender` port and provider choice | Phase 5 | Port only, no channel until decided |
| Q-3 | Should the repo language (code comments, docs) stay English? | Consistency | None | English |
| Q-21 | How do we decide that two dosage forms are "the same" for equivalence? Research so far (2026-11-16): the FDA defines pharmaceutical equivalents as same active ingredient, **same dosage form, same route of administration** and same strength (21 CFR 314.3, Orange Book preface); a tablet and a capsule are therefore different, and immediate-release vs extended-release are "alternatives", not equivalents. The EDQM Standard Terms (ISO 11239, free after registration) give a standard vocabulary for dose forms and routes. Options: (A) strict: equivalent only when the standardized dose form, route and release type are identical; (B) the brief's wider "family" wording, where a match inside a family is only "possible, needs pharmacist check" | The code currently takes a `DosageFormFamily` as reference data and returns "possible" when it is unknown. Either option needs SFDA/EG form names mapped to standard terms, which can only be built from the real data. A pharmacist should review that mapping, but the equivalence rule itself now rests on the regulatory definition, not on our opinion | Phase 1 equivalents endpoint | Option A for "equivalent", with a family-level match only as "possible". Not implemented until real form names are seen |

---

## C. Not yet written

`docs/DATA_SOURCES.md` (license status per source) and `docs/GLOSSARY.md` are Phase 0 deliverables in the brief but outside this review step. They will be drafted after you approve this set, and the glossary needs your input on Arabic/English drug terminology.

## D. Answers given by the owner (2026-11-21)

| ID | Answer |
|---|---|
| Q-9 | The project is a proof of concept, not production. Legal review waits until the owner says it is going to production |
| Q-11 | Build for a very large number of users. No invented numbers; the load test reports measured baselines |
| Q-12 | Reuse the vision model(s) already configured for the box scan (`vision_models`) |
| Q-13 | Email and password, then an OTP sent to the email as verification (Phase 3 plan, Wave I) |
| Q-18 | Notifications by email, plus an in-app inbox; email for what needs attention. No push |

New question from these answers:

| ID | Question | Why it matters | Proposed default |
|---|---|---|---|
| Q-39 | Can we get the exact location of each pharmacy? The SFDA list only gives a city and a Saudi National Address short code (`JJMA3817`). The national address service can turn a short code into coordinates but needs an API key and has its own terms | Without it, "nearby" stops at the city (136 pharmacies in Riyadh are ordered by name) | Keep city precision; the owner decides whether to request a key from the national address service |
| Q-38 | Which email provider sends the OTPs and notifications, and from which address or domain? | Deliverability needs a verified sender domain (SPF, DKIM); free tiers cap volume, which matters for "very many users" | An `EmailSender` port with an SMTP adapter, so any provider works; for development a local mail catcher |
