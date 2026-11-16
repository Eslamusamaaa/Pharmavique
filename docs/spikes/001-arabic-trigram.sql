-- Spike 001 (ADR-003, step 0a): does pg_trgm extract usable trigrams from Arabic text
-- with the database locale used by docker-compose.yml?
-- Run: docker cp docs/spikes/001-arabic-trigram.sql <db-container>:/tmp/spike.sql
--      docker compose exec db psql -U pharmavique -d pharmavique -f /tmp/spike.sql
-- Strings below are sample text for the test only, not catalog data.

\echo '--- environment ---'
SELECT version();
SHOW server_encoding;
SELECT datname, datcollate, datctype, datlocprovider FROM pg_database WHERE datname = current_database();
SELECT extname, extversion FROM pg_extension WHERE extname IN ('pg_trgm', 'vector') ORDER BY 1;

\echo '--- trigram extraction (empty array means Arabic letters were NOT treated as word characters) ---'
SELECT show_trgm('panadol')  AS latin_trigrams;
SELECT show_trgm('بانادول')  AS arabic_trigrams;
SELECT cardinality(show_trgm('بانادول')) AS arabic_trigram_count;

\echo '--- similarity of misspellings (higher means closer) ---'
SELECT similarity('panadol', 'panadool')  AS latin_misspelled;
SELECT similarity('بنادول', 'بانادول')    AS arabic_misspelled;
SELECT similarity('بنادول', 'ابوفين')     AS arabic_unrelated;
SELECT similarity('بَانَادُول', 'بانادول') AS arabic_with_diacritics;
SELECT similarity('أموكسيسيلين', 'اموكسيسيلين') AS arabic_alef_variant;

\echo '--- GIN trigram index on a small sample (seqscan disabled only to prove index usability) ---'
CREATE TEMP TABLE sample_names (name text);
INSERT INTO sample_names VALUES
  ('بانادول'), ('بنادول اكسترا'), ('ابوفين'), ('بروفين'),
  ('panadol'), ('Panadol Extra'), ('brufen');
CREATE INDEX sample_names_trgm ON sample_names USING gin (name gin_trgm_ops);
ANALYZE sample_names;
SET enable_seqscan = off;
EXPLAIN (COSTS OFF) SELECT name FROM sample_names WHERE name % 'بنادول';
SELECT name, round(similarity(name, 'بنادول')::numeric, 3) AS score
FROM sample_names WHERE name % 'بنادول' ORDER BY score DESC;
