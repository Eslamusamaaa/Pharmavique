# Data Sources

One entry per source. Every source states **what it is, how we get it, and its license status**. License status is never assumed: "unverified" means we have not seen a written permission.

Last updated: 2026-11-16.

---

## SA-1. SFDA public registered-drugs list (web pages)

| | |
|---|---|
| Owner | Saudi Food and Drug Authority (SFDA) |
| Pages | `https://www.sfda.gov.sa/en/drugs-list?page=N` (list, 20 rows per page, about 460 pages) and `/en|ar/details_data?nid=..&id=<register number>&page=..` (one page per drug and language) |
| What it contains | Per drug, 26 fields in English and in Arabic (the Arabic page also gives the Arabic trade name and translated values): register number, trade name, scientific name, strength and unit, dosage form, route of administration, size and unit, package type and size, legal status, product control, distribution site, shelf life, storage conditions, manufacturers (name and country), marketing company and its country, agents, ATC codes 1 and 2, description code, authorization status, marketing status, **price**. The list page shows a subset (scientific name, trade name, strength, dosage form, price) |
| How we get it | `pharmavique sfda-scrape` (full) and `pharmavique sfda-update` (only what changed), using headless Chromium through Playwright. See [SFDA_SCRAPER.md](SFDA_SCRAPER.md) |
| Trust level | `official` (the data is SFDA's own publication) |
| Provenance stored | source name, page URL, fetch time and run id per language, for every record |
| Currency / price unit | **Not stated on the pages.** Stored as `unconfirmed` (OPEN_QUESTIONS Q-5) |
| License status | **Unverified** (see below) |
| Where the data lives | `data/sfda/` on the machine that ran the crawl. **Git-ignored on purpose; it is never committed.** |

### Rules the crawler follows

- Reads only public pages by plain GET. It never uses the site's search/filter form, which carries a CAPTCHA. A CAPTCHA is never bypassed.
- Checks `robots.txt` before every URL and stops if a URL is disallowed.
- One request at a time, at least 1.5 s apart plus random jitter. Images, fonts, styles and media are not downloaded.
- A generic User-Agent that names no person or project. The contact details of the operator are deliberately not included; add them with `--user-agent` if SFDA asks.
- Stops immediately on HTTP 401, 403 or 429, and after repeated unreadable pages. Resumable.

### License and legal status (unverified)

- SFDA's published rules of use state that the site's content, including data compilations, is SFDA's property and protected by copyright. I found no reuse licence for this list.
- The terms I could read do not mention automated access, and `robots.txt` does not disallow these pages. That is the absence of a prohibition, not a permission.
- The project owner reports having been told by someone that scraping the site is fine. That advice is **not written down anywhere we can cite**, so it does not change the status above.
- Until there is written permission (for example an SFDA data-sharing agreement or confirmation of an open-data licence): treat the data as **internal/development use**, do not redistribute the raw pages or files, and get legal review before any commercial release (OPEN_QUESTIONS Q-8, Q-9).

### Other SFDA routes checked (2026-11-16)

| Route | Finding |
|---|---|
| Developer portal API (`developer.sfda.gov.sa`, Registered Drug Service, OAuth with consumer key and secret) | The host resets connections from this network, so it could not be read or used. Sign-up steps are unknown. A key is not needed for SA-1 |
| Open-data page (`sfda.gov.sa/en/open-data`) | Offers official Excel files, but none of those I could identify is the human drug list (cosmetics, veterinary, medical devices, energy drinks, feed) |
| National open-data platform | Not checked in detail; the license of any SFDA dataset there must be read on the dataset itself |

---

## EG-1. Egyptian drug data

Not started. Rules from the project brief: the official Egyptian Drug Authority search sits behind a CAPTCHA and **must not be scraped or bypassed**. Plan: a CSV-import adapter for a third-party dataset marked `unofficial_unverified`, and a request to the Egyptian Drug Authority for an official feed. EG prices have no known source (OPEN_QUESTIONS Q-6, Q-7).
