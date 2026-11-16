# ADR-003: Search: PostgreSQL (pg_trgm + pgvector) behind a port, not a separate search engine (yet)

| | |
|---|---|
| Status | **Accepted** (2026-11-16) |
| Date | 2026-11-16 |
| Deciders | Project owner, architecture lead |
| Related | [ARCHITECTURE.md](../ARCHITECTURE.md), OPEN_QUESTIONS Q-11, Q-12, Q-17 |

## Context

The `search` context must support:

- **Fuzzy text lookup** of trade names, active ingredients and registration numbers, in Arabic and English, tolerant to misspellings and transliteration (a trade name written in either script).
- **Semantic retrieval** for leaflets (`knowledge`, Phase 4) and, possibly, product-name fallback matching for photo recognition (Phase 3).
- A read-heavy path with caching in Redis and keyset pagination for large lists.
- Arabic normalization (diacritics, alef/ya/ta marbuta variants, Arabic-Indic digits) and an alias table.

Data size: not known yet. The working assumption is that a national drug registry is modest (order of tens of thousands to low hundreds of thousands of rows per market). **This is an assumption to validate** with real SFDA data in Phase 1 and recorded in OPEN_QUESTIONS.

The stack already mandates PostgreSQL with `pg_trgm` and `pgvector`, and the architecture makes `search` a **rebuildable projection** of catalog events behind a `SearchIndex` port.

## Options considered

### A. PostgreSQL: `pg_trgm` for fuzzy text, `pgvector` for embeddings (chosen)
- Pros: no new datastore to run, secure, back up or comply with; one operational model; transactional with the rest of Postgres; trigram similarity handles misspellings; pgvector supports approximate nearest-neighbour indexes (HNSW) and exact search for small sets; hybrid ranking can be done in SQL or application code; fits the extraction path (the projection can be rebuilt anywhere).
- Cons: relevance tuning (field boosts, typo-tolerance ranking, synonyms, faceting) is manual and less polished than dedicated engines; trigram indexes are larger and slower to maintain at very high write volume; vector search shares CPU/memory with the OLTP workload; no built-in Arabic morphology (stemming/lemmatization), so Arabic quality depends on our normalization and alias table.

### B. Dedicated engine, lightweight (for example Meilisearch or Typesense)
- Pros: typo tolerance and ranking work well out of the box; fast to integrate; good developer experience.
- Cons: a new stateful service holding health-adjacent data to secure and operate in two jurisdictions; eventual consistency with Postgres (acceptable given the projection design); Arabic handling quality and licensing/hosting terms **not verified by me** and must be evaluated, not assumed.

### C. Dedicated engine, heavyweight (OpenSearch or Elasticsearch)
- Pros: richest analyzers (including Arabic analysis), faceting and aggregations, scale-out.
- Cons: highest operational and cost burden; overkill for the assumed data size; cluster management on a small team.

### D. Postgres full-text search only
- Not chosen as the main mechanism: lexical matching alone does not give typo tolerance for drug names, which is the dominant failure mode. May be added later as a complementary signal.

## Decision

Start with **option A**, with the following design so that moving to B or C stays cheap:

1. **`SearchIndex` port.** `search.application.ports.SearchIndex` exposes `search(query, market, filters, limit, cursor)` and `upsert/remove`. Postgres is one adapter. Another engine is another adapter.
2. **Projection, not source of truth.** `search` owns a denormalized table (normalized names, aliases, ingredient names, market, status) built from catalog events and fully rebuildable from catalog's export.
3. **Normalization is domain logic.** An Arabic/English normalizer in `search.domain` (pure functions, hypothesis and example tests with misspellings) produces the normalized text that is indexed and the normalized query. The same function is used on both sides.
4. **Layered matching.** Exact registration number/barcode first, then trigram similarity on normalized names and aliases (GIN or GiST trigram indexes, chosen by `EXPLAIN` evidence), then optional semantic fallback via pgvector for low-confidence cases. Result scores are combined in application code (simple, explainable weighting; the exact scheme is decided during Phase 1 from an evaluation set, not now).
5. **Evaluation set first.** A labelled query set (real misspellings and transliterations of drug names) with recall@k and MRR is built in Phase 1 and gates any relevance change. It also provides the data to decide whether option A is enough.
6. **Phase 1 spike (mandatory, first task). Result 2026-11-16: passed on the local Docker image with `en_US.UTF-8`, see [spike 001](../spikes/001-arabic-trigram.md); managed Postgres must still repeat it.** Verify on the target Postgres image that trigram extraction works for Arabic text. `pg_trgm` decides what counts as a word character from the database's locale settings, and a locale that treats non-ASCII letters as non-word characters would make Arabic trigrams empty. The spike must also confirm that the chosen managed Postgres (Q-17) offers both `pg_trgm` and `pgvector`. I am flagging this as a known risk class, not asserting that it will occur.
7. **Vector index policy.** Exact search while a vector table is small; an approximate index (HNSW) introduced only when `EXPLAIN` and load tests show it is needed. Embedding model and provider are open (Q-12) and sit behind a port, so vector dimensions are a migration concern, not an architectural one.
8. **Cache.** Hot lookups cached in Redis with explicit invalidation on ingestion runs and relevant events.

### Hybrid retrieval, BM25 and semantic models

Hybrid search (lexical/fuzzy plus semantic) is the intended shape, but each signal is used where it is strong:

- **Trigram** for drug names and misspellings (BM25 compares whole words, so one wrong letter defeats it).
- **Semantic embeddings** for free-text questions and leaflets; weak for brand names, which are meaningless strings to an embedding model, so never the only signal for identifying a product.
- **BM25:** PostgreSQL full-text ranking is not BM25, and I have not verified any Postgres BM25 extension. BM25 comes out of the box with a dedicated engine (option C), so it enters the design only if the evaluation set shows it beats trigram, via the `SearchIndex` port.
- Fusion by reciprocal rank fusion or a simple weighted score, decided from the Phase 1 evaluation set, not now.
- A semantic signal does not depend on the database locale, which partly mitigates the Arabic trigram risk but does not replace the spike below.

### Exit triggers (move to B or C through a new ADR)

- p95 latency of search endpoints misses the agreed target under the agreed load after indexing and caching work (targets pending, Q-11).
- Recall@k or MRR on the evaluation set stays below the agreed threshold after normalization/alias/scoring improvements.
- Product needs facets, aggregations or morphological Arabic analysis at a scale Postgres serves poorly.
- Search load measurably harms OLTP latency, and read replicas do not fix it.

## Consequences

Positive:
- Zero new infrastructure and no extra data-protection surface in Phase 1.
- Search quality is measured, not assumed, from the first week.
- Swapping engines affects one adapter and a rebuild job.

Negative / risks:
- Manual relevance engineering for Arabic and transliteration; the alias table becomes a maintained asset.
- Trigram and vector indexes increase storage and write cost; bulk ingestion must account for index maintenance (batching, possibly deferring index builds on full reloads).
- Postgres is shared by OLTP and search; contention is possible. Mitigations: read replicas, caching, index tuning, and the exit triggers above.
- The data-size assumption may be wrong; the Phase 1 data profile will confirm or correct it.
