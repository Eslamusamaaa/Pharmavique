-- Runs once, when the data volume is first created.
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fuzzy text search (ADR-003)
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector embeddings (ADR-003)
