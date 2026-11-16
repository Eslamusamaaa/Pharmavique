# Spike 001: Arabic trigrams with pg_trgm

| | |
|---|---|
| Date | 2026-11-16 |
| Purpose | ADR-003, step 0a: confirm `pg_trgm` extracts usable trigrams from Arabic text with the database locale used by `docker-compose.yml` |
| Script | [001-arabic-trigram.sql](001-arabic-trigram.sql) |

## Environment (as run)

- PostgreSQL 17.12 (image `pgvector/pgvector:pg17`), encoding `UTF8`
- Locale: `datcollate = datctype = en_US.UTF-8`, provider `libc`
- `pg_trgm` 1.6, `pgvector` 0.8.7 (both created by `docker/postgres/init/01-extensions.sql`)

## Results

| Check | Result |
|---|---|
| `show_trgm('panadol')` (Latin sample) | 8 trigrams |
| `show_trgm('بانادول')` (Arabic sample) | **8 trigrams**, not empty. Arabic letters are treated as word characters. PostgreSQL prints trigrams of multibyte text as hash codes, which is expected |
| Latin misspelling `panadol` vs `panadool` | similarity 0.70 |
| Arabic misspelling `بنادول` vs `بانادول` | similarity 0.50 |
| Unrelated Arabic strings | similarity 0 |
| Same word with diacritics (`بَانَادُول` vs `بانادول`) | **0.118**: diacritics wreck similarity |
| Alef variant (`أموكسيسيلين` vs `اموكسيسيلين`) | **0.60**: letter variants lower similarity |
| GIN trigram index on a 7-row sample | Used (`Bitmap Index Scan`), with sequential scans disabled to force the planner. This proves index usability, not performance |
| `%` operator, default threshold | Returned the two expected Arabic rows (score 0.5 each) |

## Conclusions

1. **The risk flagged in ADR-003 did not materialize** for `en_US.UTF-8` on this image: Arabic trigram extraction works and misspellings score well above unrelated text.
2. **Normalization is mandatory, not optional.** Diacritics and alef/ya/ta marbuta variants cut similarity sharply, so the Arabic normalizer (Phase 1, step 8) must run on both the indexed text and the query, as ADR-003 already specifies.
3. Short misspelled names score around 0.5, close to the default `%` threshold of 0.3 once normalized. Threshold and ranking must be tuned on the labelled evaluation set, not guessed.

## Limits of this spike

- Local Docker image only. **A managed Postgres may use a different locale** and must repeat this script (OPEN_QUESTIONS Q-17).
- Seven synthetic rows: says nothing about performance at real registry size.
- Multi-word names (`word_similarity`) and Arabic-Latin transliteration pairs were not evaluated.
