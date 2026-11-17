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

## SA-2. SFDA recalls, market withdrawals and safety alerts (planned)

| | |
|---|---|
| Owner | Saudi Food and Drug Authority |
| Where | A monthly PDF bulletin titled "Recalls, Market Withdrawals & Safety Alerts" on sfda.gov.sa, and the drug circulars and withdrawals pages |
| What it adds | Official notices that a product was recalled or withdrawn, with the reason, so the drug page can say why a product disappeared from the list |
| How we would get it | Download the monthly PDF, extract product names and details, match them to catalog drugs, and have a person review each match before it is shown |
| Trust level | `official` |
| License status | **Unverified**, same position as SA-1: SFDA states its content is its property, and no reuse licence was found |
| Status | Not started. Exact page URLs and the publication schedule must be checked on sfda.gov.sa before building (OPEN_QUESTIONS Q-25) |

---

**Update 2026-11-18:** the full crawl of the drugs list is done: 9,162 unique drugs (not 9,026), see `docs/SFDA_SCRAPER.md`. Product pictures are a separate, unofficial source: see `docs/MEDIA_PIPELINE.md`.

---

## SA-3. The other official SFDA lists (catalog found 2026-11-17)

SFDA's "Information Lists" catalog (`https://www.sfda.gov.sa/en/lists-categories`, three pages) shows **28 official lists** across drugs, food, medical devices and cosmetics. Only their titles and categories were read; the **contents, columns, update frequency and terms of each list have not been checked**. Every list has the same unverified reuse status as SA-1.

### Drugs: most valuable for the product

| List (path) | What it may give us | Feature it would feed |
|---|---|---|
| Drug Shortage List (`/en/currentlyInShortageList`) | An **official** list of drugs currently in shortage | Shortage alerts from an official source |
| Drug Companies List (`/en/drug-companies`) | Company master data | Company profiles and name resolution (company role) |
| Drugs Safety Labeling Updates (`/en/drugs-safety-labeling`), Safety Alert (`/en/safety_alert`), Pharmacovigilance (`/en/pharmacovigilance`), Periodic safety reporting schedule (`/en/periodic_safety`) | Official safety notices | Safety notices on the drug page (replaces or complements the monthly PDF, SA-2) |
| Marketed Products (`/en/marketed-products`) | Which products are actually marketed | Authorization versus marketing status |
| Drug Approvals (`/en/new-sfda-drug-approvals`) | New approvals | "New product" radar for companies |
| Licensed Pharmacies List (`/en/list_registered_pharmacies`) | An official pharmacy directory | Pharmacy finder (to check against the maps provider) |
| Incentive Project List (`/en/unregistered-pharmaceuticals-lists`) | A list of unregistered pharmaceuticals (title only; its meaning must be read) | Possibly the "special access" products the owner asked about |
| Released Vaccine, Under Studying List, Drug Clinical Trials List, Saudi Public Assessment Report (`/en/drug-evaluation-reports`) | Vaccines, products under review, trials, assessment reports | Later |

### Other categories the owner asked to add

| Category | List (path) |
|---|---|
| Veterinary medicines | Veterinary drugs (`/en/vet-drugs`) |
| Medical devices | Medical Equipment List (`/en/medical-equipment-list`) |
| Cosmetics | All Cosmetic List (`/en/AllCosmeticList`), Notification of Marketing for Cosmetic Products (`/en/cosmetics-list`) |
| Food, supplements and feed | Notification of Marketing for Food Products, Registered (`/en/products`), Feed List (`/en/feed-list`) |
| Establishments | Licensed Establishments List (`/en/licensed-establishments-list`) |
| Downloadable lists | Downloadable Information Lists (`/en/information_list`) |

**Not found as separate lists:** a register of herbal or supplement products (they may sit under the food products list) and a register of drugs imported under exceptional permission. Both must be confirmed with SFDA (OPEN_QUESTIONS Q-28).

The 2023 Excel files on the Open Data page (veterinary medicines, low-risk medical devices, cosmetics, energy drinks, feed) are older snapshots of some of these; the live lists above are preferred.

### What each list looks like (probed 2026-11-17, one request per list)

All lists are server-rendered tables of **10 rows per page** with a `?page=N` pager. Every page carries the CAPTCHA fields of the site's filter form, but the plain GET list pages are returned without any CAPTCHA, exactly like the drugs list; the filter form is never used. "Pages" is the pager's last page, so rows are an estimate (pages x 10).

| List | Columns | Pages | About rows | Detail pages |
|---|---|---|---|---|
| Drug Shortage List | Generic Name, Availability Status (Arabic), Trade name number | 72 | 720 | yes |
| Drugs Safety Labeling Updates | Scientific Name, Trade Name, Updated Section, Month | 26 | 260 | no |
| Safety Alert | Title, Date, Type of news, link to a PDF | 27 | 270 | PDFs |
| Unregistered pharmaceuticals ("Incentive Project List") | Scientific Name, Strength, Dosage Form, Purpose, Date of Update | 53 | 530 | no |
| Licensed Pharmacies | Pharmacy Name, Contact Number, Address, Region | 38 | 380 | no |
| New drug approvals | Request Type, Drug Type, Trade Name, Scientific Name, Strength, Dosage Form, Approval Date, Approved Use | 46 | 460 | yes |
| Drug Companies | Company Name, Address, Company status, Registration Number, Certificate date, Drug Type, Production line, Country | 616 | 6,160 | no |
| Veterinary drugs | Trade Name, Agent Name, Manufacturer, Register Number | 136 | 1,360 | yes |
| Cosmetic ingredients (All Cosmetic List) | Scientific ingredient name, ingredient number (CAS) | 235 | 2,350 | yes |
| Feed List | Product Name, Product Type, Animal | 2,081 | 20,800 | yes |
| **Medical Equipment List** | Brand Name, Classification, Manufacturer, Status | **16,040** | **about 160,000** | yes |
| **Food products (Registered)** | Barcode, Registration Number, Brand Name, Trade Name | **150,480** | **about 1.5 million** | yes |
| **Cosmetic products (Notification of marketing)** | Product Name, Category, Country, Company | **298,336** | **about 3 million** | yes |
| Marketed Products | Registration Number, Scientific Name, Trade Name, Dosage Form | none | 3 rows seen; appears search-driven | unknown |

The Downloadable Information Lists page offers only a few PDF reports (adverse events, a pesticides list), **not bulk exports** of these registers.

**The three large lists cannot be crawled politely.** At about 2 seconds per request, the cosmetic products list alone is about 7 days of list pages with no details, and food products about 3.5 days. Crawling them would put a sustained load on SFDA's site that we should not impose without its agreement. They need an official data export (OPEN_QUESTIONS Q-29) or a decision to leave them out.

Status: the crawler is built (`pharmavique sfda-lists`, see `docs/SFDA_SCRAPER.md`, section 4) and was tried on two real pages of the shortage list on 2026-11-17: the rows, the column names and the pager (72 pages) were read correctly. The full lists have **not been crawled yet**. List pages only; details pages are not fetched. Marketed Products is left out (it appears search-driven, with no pager).

---

## EG-1. Egyptian drug data

Not started. Rules from the project brief: the official Egyptian Drug Authority search sits behind a CAPTCHA and **must not be scraped or bypassed**. Plan: a CSV-import adapter for a third-party dataset marked `unofficial_unverified`, and a request to the Egyptian Drug Authority for an official feed. EG prices have no known source (OPEN_QUESTIONS Q-6, Q-7).
