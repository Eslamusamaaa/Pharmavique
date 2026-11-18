# ADR-006: Vector store in Postgres (pgvector) and chunks of official documents

| | |
|---|---|
| Status | **Accepted** (owner, 2026-11-18) |
| Date | 2026-11-18 |
| Related | ADR-003 (search), ADR-004 (scalability), ADR-005 (providers), [PHASE_2_PLAN.md](../PHASE_2_PLAN.md) |

## Context

The assistant must answer from retrieved official text with citations. What we hold today (lists-1,
2026-11-18): about 2.05 million characters of document text (94 DHPC letters, 270 safety-alert
documents, 54 of them read by OCR), plus short records (146 recalls with detail pages, 578 risk
minimization rows, 241 safety-labeling updates). The catalog has about 9,000 products. pgvector 0.8.7
is already installed in our Postgres 17.

## Decision

- **No separate vector database.** Chunks and their vectors live in a `knowledge` schema in the same
  Postgres, one row per chunk with an `embedding vector(N)` column (N from the embedding model,
  1024 for BGE-M3) and an HNSW index added when vectors exist. The store is a port, so it can move.
- **The `knowledge` context is un-parked** for official SFDA documents (not for leaflets, which we do
  not have). It owns chunks, their provenance and the retrieval over them.
- **A chunk always keeps its provenance**: list, row key, source URL or file, fetch time, snapshot,
  trust level, whether the text came from OCR, and the linked product register numbers from the
  catalog's list links. Every answer cites a chunk; a chunk cites its document.
- **Chunking is deterministic code** in the domain: paragraphs are kept whole where possible, chunks
  are about 1,200 characters with about 200 characters of overlap, and a chunk never mixes two
  documents. Short records (a recall, an RMM row, a labeling update) are one chunk each. Rebuilding
  gives the same chunk ids for the same text (content hash), so re-embedding only touches changes.
- **Retrieval is hybrid** like product search: trigram and full-text signals plus the vector signal,
  fused with RRF (ADR-003). The vector part is switched on when the embedding adapter has a key.
- The embedding model is set by configuration; a model change means a re-embed job, never mixing
  vectors from two models (the row records `embedding_model`).

## Consequences

- One database to run, back up and secure; joins inside the `knowledge` schema only.
- At our size an HNSW index on a few thousand vectors is small; ADR-004 still applies if it grows.
- OCR chunks are marked so the assistant can say the quoted text was read from a scan.
