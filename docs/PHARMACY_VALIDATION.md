# Pharmacy validation: the five pilot sites (phase 2 of `PHARMACY_SCRAPING_PLAN.md`)

Date of the probes: 2026-11-23. Method: the project's polite rules: `robots.txt` read first and honored
for every URL (the project's own matcher), one request at a time per site, 2 seconds apart (5 seconds for
Innova, whose robots.txt asks for `Crawl-delay: 5`), the project's User-Agent, a 401, 403 or 429 would have
stopped that site (none happened), nothing bypassed. About 25 requests per site. Real pages kept as trimmed
fixtures in `tests/fixtures/offers/<site>/` (README there).

What this report is **not**: a human check of 20 pages per site. The "price in the page" column below is an
automatic consistency check (the JSON-LD price also appears in the visible HTML), not someone comparing the
page with the shop screen. That check, and whether each picture URL still loads, are still open (gate of
phase 2 asks for 20 hand-checked pages; see "Open").

## Results

| | Nahdi | United | Innova | Adam | Dr. Move (Salla) |
|---|---|---|---|---|---|
| Address | nahdionline.com | unitedpharmacy.sa | innovapharmacy.com | adamonline.com | drmovepharmacy.com |
| robots.txt | 200, 40 rules, no crawl delay | 200, 22 rules (no query strings, `*/pkginfo/*`) | 200, **Crawl-delay 5** | 200, 2 rules (`/admin/`, `/api/`) | 200, 4 rules |
| Pause used | 2 s | 2 s | **5 s** | 2 s | 2 s |
| Sitemaps | index per language, 7 child sitemaps (a first file has 10,000 URLs; the others were not read) | one file, 14,931 URLs (products **and** category, brand and campaign pages) | one products file per language; the Arabic one has 28,074 URLs; the English one was not read | index of 12 files; English products file 14,721 URLs | index of 3: `sitemap-1` categories, `sitemap-2` **3,480 products**, blog |
| Product page has JSON-LD `Product` | 20 of 20 | 13 of 20 (the other 7 are not product pages) | 20 of 20 | 19 of 20 | 17 of 20 |
| Price, currency, stock in JSON-LD | 100% | 100% of product pages | 100% | 100% | 100% of product pages |
| Currency stated | SAR | SAR | SAR | SAR | SAR |
| Stock values seen | InStock | InStock, OutOfStock | InStock, OutOfStock | InStock | InStock |
| Picture URL in JSON-LD | 95% (about 3.5 per page) | 100% (1) | 100% (1) | 100% (1) | 100% (about 1.4) |
| Brand | 100% | about 70% | 100% | 100% | about 60% |
| Barcode (GTIN) in JSON-LD | 0% | 0% | 0% | 0% | **40%** |
| Description in JSON-LD (median length) | 42 characters | 250 | **0** (the text is in the HTML sections) | 163 | **1,407** |
| Page weight (median) | 614 KB | 545 KB | 223 KB | **2,191 KB** | 377 KB |
| Saudi market | paths `ar-sa` and `en-sa`; UAE has its own sitemaps and must be left out | `.sa` domain | Saudi riyals | Saudi riyals | Saudi riyals |
| Terms of use read | personal, non-commercial use only; copying or commercial use of the materials is not allowed (no wording about crawlers) | no clause about crawling (a contest's bot rule only); general intellectual-property text | short page, no relevant clause | **no terms page found** at four common addresses | content (texts, pictures, logos) belongs to the shop; no copying without prior permission |

## What the pages do not give

- **Active ingredients: no site has a field for them.** Where they appear it is free text inside the
  description ("ingredients", "المكونات") on some products. So for a listing matched to a registered
  product the ingredients come from the registry (they are the registry's, not the shop's); for a listing
  with no match they stay as unverified text or absent. This changes the wish "active ingredients for
  everything": it is only complete for matched medicines.
- **Descriptions**: Nahdi and Innova hold the useful text in the HTML (JSON-LD has almost none), so their
  adapters read HTML sections, not only JSON-LD. Dr. Move has the longest texts.
- **Barcodes** are rare (only Dr. Move's JSON-LD). The registry has none, so a barcode helps tell two
  listings apart across shops, not match a registered product.
- **United** mixes product pages with category, brand and campaign pages in the same sitemap: a product is
  recognised by its JSON-LD `Product`, not by the address. Some names also arrive with a wrong character
  encoding that the adapter must decode properly.
- **Adam's** pages carry 2 MB of filter and menu markup; the product facts are in the JSON-LD block.
  Reading every product page would move about 30 GB; the price and stock job must use the lighter source
  when one exists, and `/api/` is disallowed.

## Size and time of the first full load (one request at a time; resumable runs)

| Site | Product URLs known | Pause | Time for one page per URL |
|---|---|---|---|
| Nahdi | at least 10,000 (1 of 7 files read) | 2 s | at least 5.6 hours |
| United | 14,931 (about 9,700 products if the sample is typical) | 2 s | about 8.3 hours for all URLs, 5.4 for products |
| Innova | 28,074 (Arabic file) | 5 s | **about 39 hours** |
| Adam | 14,721 | 2 s | about 8.2 hours and about 32 GB |
| Dr. Move | 3,480 | 2 s | about 1.9 hours |

Together about 70,000 or more listings, so the first load of the five is a matter of days, run once, in
resumable runs and in parallel across sites (each site stays at one request at a time). The daily work
afterwards is far smaller (sitemap dates, changed pages, tiered price watch), as the plan describes.

## Verdict per site

| Site | Technically | Needs before its adapter is called supported |
|---|---|---|
| Nahdi | Yes (cleanest data; Saudi paths only) | The terms restrict copying and commercial use of the materials (the project is a proof of concept, and the owner has asked not to raise licence questions; recorded here once so it is known); read all 7 sitemap files |
| United | Yes, with product-page detection | Terms read: no crawler clause; handle `Disallow: /*?` (never request a URL with a query string) |
| Innova | Yes (slowest: 5 s) | HTML description parser; the English sitemap; accept the 39-hour first load |
| Adam | Yes through JSON-LD | Find its terms page (not found); a lighter price source than 2 MB pages |
| Dr. Move | Yes | The terms forbid copying texts and pictures without permission; GTIN and long descriptions are available |

## Open

1. The human check of 20 pages per site (comparing the shop page with the stored values) and a check that
   picture URLs load (counted as `bad_images` in the run summary).
2. Adam's terms page, Nahdi's other six sitemap files, Innova's English sitemap.
3. Whether a site keeps answering at this pace for hours: only a real run shows it. Any 401, 403 or 429 ends
   that site's run and is never retried.

None of the five refused an automated request; `robots.txt` allowed every product page that was read.

## Found while loading the five catalogs (2026-11-23)

- **Sizes** (product addresses in the sitemaps): Nahdi 68,818, Innova 29,488, Adam 14,721, United about
  14,600 (a good part of them category pages, recognised and skipped), Dr. Move 3,480. Together about
  130,000 listings.
- **Category of a listing** (medicine, cosmetic, device): only Nahdi shows the category path in the
  product page. Adam, Innova and Dr. Move build it in the browser; United's category pages hold the
  products but `robots.txt` forbids their next pages (`?p=2`), and an Adam category page weighs 11 MB.
  Those four stay `unclassified`; whether a listing is a medicine is then decided by the match with the
  registry, never by guessing from its name.
- **Pictures**: Dr. Move, Nahdi and Adam serve them (a Nahdi picture averages 250 KB, Adam's 50 KB, Dr.
  Move's 60 KB). **Innova's picture host answers `Disallow: /` to every robot**, so its pictures are
  not downloaded: only their addresses are kept. United's picture host was not reached yet (the loader
  has not got to its products).
