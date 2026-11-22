# Product pictures: how they are found, checked and mapped

Status 2026-11-18: built and run once over the whole SFDA drug list. Pictures come from Saudi
online pharmacies; drugs no shop sells get a marked stand-in.

## The idea in one paragraph

For every SFDA drug we have its trade name (English and Arabic), active ingredients, strengths,
dosage form and company. We find the page of that drug in a Saudi pharmacy's own catalog, check
that the page is about this drug (name, strength, Saudi evidence), download its picture, and read
the text printed on the picture with OCR to confirm it is the right box. Each drug ends up with
one row in `data/media/mapping.jsonl`.

## Where pictures come from (no search engine)

Search-engine result pages are not scraped (their terms forbid it and they answer with CAPTCHAs).
Instead the pipeline uses the **sitemaps** that shops publish for crawlers:

1. `sfda-images-sitemaps` collects the page addresses of the shops once (robots.txt first). The
   built-in list: Life, United, Raf, Aljawaher, Nahdi, Medon, Ibrand, Aster, The Outlet. Shops that
   blocked us (Boots, Dawi, Desertcart, Danube, Al-Dawaa, Tdawi, Lemon) are left alone.
2. A drug's page is found by matching the words of its brand name against the words in each
   address ("panadol-extra-24-tablets"). Form and strength words in the registry name ("TAB",
   "500 MG", "F.C") are dropped first.
3. The page is read politely: one pace per website, robots.txt obeyed, a bot check or HTTP 403 means
   the site is left alone for the run, and HTTP 429 means a cool-down (it was once treated as a
   permanent block, which lost thousands of drugs; fixed 2026-11-18).

## Checks, in order

| Check | What it looks at | Result |
|---|---|---|
| Page check | The page text and address: every word of the brand, a `.sa` address or the word Saudi or the company, and the registry strength | `matched`, `needs_review` (no Saudi evidence, or a different strength) or rejected |
| Not a listing page, not a shop logo | `/collections/`, `/brands/`, `logo`, `og-image`, a picture already used by 4 other drugs | rejected |
| Box check (OCR) | The text on the picture, read in English and Arabic by the OCR built into Windows (`scripts/ocr_windows.ps1`, nothing leaves the PC) | `confirmed`, `likely`, `strength_conflict`, `not_confirmed` |

Only `confirmed` means "the box shows this drug's name". `not_confirmed` is not "wrong": stylised
logos, tiny pictures and some Arabic packs cannot be read. A different strength on the box
(`Glucophage XR 750` for the registry's 500 mg) is never confirmed.

## Drugs with no real picture

Many registry entries (infusions, dialysis fluids, local generics, hospital-only products) are sold
in no online shop, so **no real picture exists to find**. A manual web search of 12 such brands found
a shop page for none of the seven that no shop lists. For those the mapping offers a plain picture
of the dosage form (tablet, capsule, liquid, drops, injection, topical, inhaler, suppository,
other) and marks it `picture_kind = placeholder`. A placeholder is never counted as a picture of
the drug and never shown as its box. A real picture replaces it when one appears.

## Commands

```bash
uv run pharmavique sfda-images-export --run-id full-20261116      # products from the crawl (incremental)
uv run pharmavique sfda-images-sitemaps                           # shops' page addresses (once)
uv run pharmavique sfda-images-sync --run-id full-20261116 --sitemaps data/media/sitemaps
uv run pharmavique sfda-images --sitemaps data/media/sitemaps --retry   # work the drugs tried before
uv run pharmavique sfda-images-verify                             # OCR every stored picture (Windows)
uv run pharmavique sfda-images-map                                # write the mapping and its summary
uv run pharmavique sfda-images-report                             # coverage and the missing list
```

`scripts/run_images_sync.ps1` restarts the sync if it stops. Progress is kept on disk
(`images.jsonl`, `attempts.jsonl`, `verification.jsonl`), so every command can be repeated.

## Output files (all under `data/`, ignored by git)

- `media/products.jsonl`: the drugs, one JSON line each (names, ingredients, strengths, form).
- `media/images/` and `media/images.jsonl`: the downloaded pictures and their records
  (source page, image address, status, score, hash, provenance, trust `unofficial_unverified`).
- `media/verification.jsonl`: the OCR text and verdict for each picture.
- `media/mapping.jsonl`: **one row per drug**: names in both languages, scientific names,
  strengths, company, picture path, `picture_kind` (`real` or `placeholder`), `picture_status`,
  `picture_check`, source page and image address.
- `media/placeholders/*.svg`: the dosage-form stand-ins.

## Result of the first full run (2026-11-18)

9,162 drugs, one mapping row each:

| | Drugs |
|---|---|
| Real picture from a Saudi pharmacy | **2,754** (30%) |
| of which the text on the box confirms the brand (`confirmed`) | 1,377 |
| of which `likely` (ingredient and strength read, brand not) | 90 |
| of which the box shows another strength of the same brand (`strength_conflict`) | 359 |
| of which not confirmed (text not readable or different) | 928 |
| No real picture: a marked dosage-form placeholder | **6,408** (70%) |

The placeholders are tablets 2,591, injections 2,300, capsules 586, liquids 461, topical 194,
drops 112, inhalers 99, suppositories 49 and other 16. About 165 drugs were not tried because a
shop (Aljawaher) was cooling down at the end; `sfda-images --retry` works them again.

## Pictures on Vercel (Neon object storage), 2026-11-23

Vercel has no media folder. The pictures that belong to a drug (the mapping's `real` rows) are in the
public bucket `pharmavique` of the Neon project, under the same key the API uses
(`products/SA/<register>/<file>`). `scripts/upload_pictures_to_bucket.py` uploads them (safe to repeat;
the S3 settings come from the git-ignored `.env.neon-storage`); a picture without a drug is never
uploaded. When `PHARMAVIQUE_PICTURE_BASE_URL` is set (the bucket's public address,
`https://<branch>.storage.<region>.aws.neon.tech/pharmavique`), `GET /v1/products/{rn}/picture`
answers with a redirect to it; without it the API reads the media folder as before.

`sfda-images-restore` downloads again the files that are missing. A picture file that answers 403
no longer stops the whole host: only five refusals in a row do (one removed file made the first
restore give up on 515 pictures of one shop).

## Known limits

- **Coverage is bounded by what shops sell.** 30% of the drugs have a real picture from the
  pharmacies in the list; the rest wait for another source (manufacturers or distributors
  supplying their pack shots) or keep the placeholder.
- **The OCR cannot read everything**: tiny pictures, decorative lettering and some Arabic packs.
- **Drugs whose SFDA details page is empty** (18 of 9,162; the page exists but its table is empty)
  are built from the list data alone: no Arabic name, no strength unit.

## Hand-fed search results: read all pages of a phrase (2026-11-18)

`sfda-images --results` reads only `--pages-per-query` pages per phrase (default 3) and works only the first `--limit` products (default 50). For a results file pass `--pages-per-query 10 --limit 100000 --retry`. With the defaults a brand that has several strength pages loses most of them: a second batch of 15 brands stored 3 pictures with the defaults and 7 with ten pages per phrase. Restricting the web search to the Saudi shops (`allowed_domains`: nahdionline.com, medononline.com, adamonline.com, unitedpharmacy.sa, myaster.com, theoutlet.sa, almujtamapharmacy.com) returns shop pages instead of papers and patents. Even so, about half of the brands searched had no Saudi shop page at all.
