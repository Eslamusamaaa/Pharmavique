# Data

Everything the project needs to run on another machine is in this folder and is versioned in git:
clone the repository, start the database, restore the snapshot, and you have the same state. Nothing here
is secret; secrets live only in `.env`.

```
data/
  db/            database snapshot, one file per schema            (55 MB)
  sfda/          the drug registry crawl                            (37 MB)
  lists/         the other official SFDA lists, one folder each     (250 MB)
  media/         picture mapping and records, shop sitemaps         (87 MB)
  interactions/  interaction sources: DDInter and MeDIC             (36 MB)
  knowledge/     US drug-label text per active ingredient           (5.6 MB)
  exports/       a flat CSV of the catalog                          (2.6 MB)
  refresh/       logs of the daily refresh (git-ignored, local)
```

## Start on a new machine

```bash
git clone https://github.com/Eslamusamaaa/Pharmavique.git && cd Pharmavique
cp .env.example .env                 # set the Postgres password and the provider keys you have
uv sync && docker compose up -d db redis
uv run alembic upgrade heads         # creates every schema
bash scripts/db_restore.sh           # loads data/db/*.dump: catalog, search index, lists, interactions, vectors
uv run uvicorn pharmavique.bootstrap.api:create_app --factory --port 8000
```

**The picture files are not in git.** They ship as a Docker image, `ghcr.io/eslamusamaaa/pharmavique-media`
(about 700 MB). With Docker Compose the `media` service copies them into the volume the API reads:
`docker compose up -d` does it. To run the API outside Docker, put them in `data/media/images/` with

```bash
docker compose run --rm -v "$PWD/data/media/images:/target" media
```

To rebuild the database from the raw files instead of the snapshot, see section 11.3 of the main
[README](../README.md).

## Folders

| Folder | What it holds | Source | Size | Rebuild or refresh |
|---|---|---|---|---|
| `db/` | `pg_dump` of the schemas `public`, `catalog`, `search`, `knowledge`, `interactions`: `catalog.dump` (3 MB), `interactions.dump` (2 MB), `knowledge.dump` (50 MB), `public.dump` (0 MB), `search.dump` (0 MB) | our database | 55 MB | `bash scripts/db_snapshot.sh` writes it, `bash scripts/db_restore.sh` reads it |
| `sfda/full-20261116/` | `records.jsonl`: one line per registered drug (English and Arabic fields, provenance) | SFDA drugs list, crawled 2026-11-16 to 18 | 37 MB | `sfda-update` (daily job) |
| `exports/catalog_full.csv` | the catalog as one flat table, for people who do not use the database | derived | 2.6 MB | export from the catalog |
| `lists/<list>/lists-1/` | one folder per SFDA list: `records.jsonl` (the rows), `manifest.json` (counts, status), `list/` (stored list pages), `details.jsonl`, `files/` and `texts.jsonl` where the rows link to documents | SFDA information lists | 250 MB | `sfda-lists`, then `sfda-lists-load` |
| `media/images/` (**not in git**) | the product picture files, `products/SA/<register number>/<name>.<ext>`; shipped as the Docker image `pharmavique-media`, see `docker/media/Dockerfile` | Saudi pharmacy sites | about 700 MB | find with `sfda-images --from-sitemap-pictures`, refill with `sfda-images-restore`, package with `bash scripts/build_media_image.sh` |
| `media/images.jsonl` | one record per picture: shop page, picture address, hash, status, provenance | derived | 7.0 MB | written by the picture commands |
| `media/mapping.jsonl` (and `.csv`) | **one row per drug**: names, picture path, `picture_kind` (`real` or `placeholder`), `picture_status`, `picture_check` | derived | 5.3 MB | `sfda-images-map`, loaded by `sfda-pictures-load` |
| `media/verification.jsonl` | the text read on each picture by OCR and the verdict | derived | 2.6 MB | `sfda-images-verify` |
| `media/attempts.jsonl` | which drugs were already searched, so a run never repeats itself | derived | 5.8 MB | written by the picture commands |
| `media/products.jsonl` | the drugs as the picture commands read them (names, ingredients, form, company) | derived from `sfda/` | 2.9 MB | `sfda-images-export` |
| `media/sitemaps/` | the address and picture of every product page of each shop, one `<shop>.jsonl` | the shops' own sitemaps | 51 MB | `sfda-images-sitemaps` (weekly in the daily job) |
| `media/generated/` | marked stand-in cards for drugs no shop sells | generated | 6.9 MB | `sfda-images-map` |
| `interactions/ddinter/` | 14 CSV files, one per ATC group: pairs of drugs with a severity | DDInter 2.0 | 30 MB | `interactions-load` |
| `interactions/medic/` | `contraindicationList.xlsx` (drug, disease, label text) and `drugList.tsv` | MeDIC (RENCI) | 6.0 MB | `interactions-load-medic` |
| `knowledge/openfda-labels/` | one JSON per active ingredient: the interactions, contraindications, pregnancy and patient-advice sections of one US label, with its DailyMed address | openFDA | 5.6 MB | `knowledge-labels` |

## What the numbers are today

- **Drugs:** 9,162 registered products.
- **SFDA lists** (rows in `lists-1`): drug-shortage 723, drug-shortage-resolved 586, safety-alert 276, safety-labeling 241, drugs-circulars 146, rmm 578, dhpc 105, drug-approvals 462, drug-companies 6,135, pharmacies 385.
- **Pictures:** 3,815 drugs have a real pharmacy picture (971 `matched` on the page text, 2,844
  `needs_review`), 5,347 have a marked placeholder; 6,320 picture files on disk.
- **Interactions:** 234,757 drug pairs, 3,960 drug-disease contraindications.
- **Knowledge:** 871 ingredients with US label text.

## Conventions

- **Provenance on every record:** `source`, `source_ref` (URL or file), `fetched_at`, `snapshot_id`, and a
  `trust` level: `official` (SFDA's own publication) or `unofficial_unverified` (pharmacy pictures,
  DDInter, MeDIC, openFDA).
- **Run ids:** `full-<date>` is the full registry crawl, `lists-1` the baseline of each list. The daily
  refresh creates `update-<date>` and `lists-<date>` folders; they stay out of git (the database holds
  the current state) and are listed in `.gitignore`.
- **Files are JSON lines** (`.jsonl`, one record per line) so a diff shows exactly what changed, except the
  external files kept as downloaded (`.csv`, `.xlsx`, `.tsv`).
- **Size rule:** every file stays under GitHub's 100 MB limit; the database snapshot is split per schema
  for that reason.
- **Not committed:** the picture files (they ship as a Docker image), logs (`*.log`), the daily refresh
  output (`refresh/`), local backups (`*.bak`, `*.pre-*`), and lists that were started and stopped.

## Refreshing

The daily job ([`scripts/daily_refresh.ps1`](../scripts/daily_refresh.ps1)) re-reads what changes quickly
and loads the difference into the database. After changing data you want to keep in git, run
`bash scripts/db_snapshot.sh` and commit `data/`.
