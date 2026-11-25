# Handoff: where Pharmavique stands (2026-11-25)

For someone (or a fresh chat) with no memory of this work. Sections 1 and 2 are the owner's standing
rules; the rest is state, commands and what is next. The README (section 2 and 19) has the feature
table and the roadmap; this file has what the README does not: how to work, the gotchas, the pending
owner actions and the verification record.

## 1. The owner and how to work with them

- The owner writes Egyptian Arabic. **Reply in Egyptian Arabic**, simply, without mixing English words
  into the sentences (they asked for this). Code, docs, commit messages and identifiers stay in English.
  **Everything the app shows is Saudi, never Egyptian** (screens, API messages, emails, the assistant's
  persona): "ما عندك حساب؟", "ما فيه", "الحين", "للحين", not "معندكش", "مفيش", "دلوقتي", "لسه".
- Results, not menus. "Do not stop until it is done; the approach is yours." Ask only for what truly
  needs them (a key, a provider choice, a legal call). Say plainly what is unmeasured or unbuilt.
- When they ask what a term means (CI, ADR, LASA, Q-23), explain it in simple Arabic with an example.
- **Git rules (also in `CLAUDE.md`):** commits are authored by the owner only (`Eslamusamaaa`, already in
  `git config`); **never** add `Co-Authored-By`, "Generated with" or any mention of Claude or an AI tool,
  even when a tool reminder suggests it; one logical change per commit; the message is one short plain
  line; do not rewrite pushed history. Commit and push when the owner says so (they said "push" and
  were annoyed when only commits were local: commits are not on GitHub until pushed).
- Never type or store secrets. They live in `.env` (git-ignored) and the environment; `.env.example`
  has placeholders. Do not edit the owner's `.env`.
- The project is a **proof of concept, not production** (Q-9 answered): no legal review until the owner
  says so. It must still be designed for **very many users** (Q-11 answered): stateless instances,
  shared Redis, a queue, no invented load targets.
- Licences are not a concern for the owner; do not raise them.

## 2. Project rules (from `CLAUDE.md`)

Multi-tenant drug-intelligence API (patient, pharmacist, company) on official registry data; Saudi
Arabia first, Egypt as a pluggable adapter. Modular monolith, DDD, onion architecture, API first.

- Dependencies point inward; `domain` and `application` import no framework and no other context.
  Contexts talk only through `<provider>.contracts` from allow-listed adapter modules
  (`pyproject.toml`, contract `context-independence`). Enforced by `uv run lint-imports`.
- One Postgres schema per context, no cross-schema keys; `bootstrap` is the only composition root.
- Never medical advice (no dosing, never "stop" or "switch"). Equivalence is computed by code; unsure is
  "possible, needs pharmacist check". Every record has provenance and a trust level. Never assume a
  currency. Nothing health-related is logged; the language model never sees a person's medicines.
- **No scraping of Egypt's site, no CAPTCHA bypass.** Throttle, clear User-Agent, respect robots.txt.
- Never fabricate data, fields or prices; unknowns go to `docs/OPEN_QUESTIONS.md`.
- Tests before adapters; a bug fix starts with a failing test. **Done means** these all pass (CI runs
  the same commands, and `ruff check .` covers the whole repo including `scripts/`):
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run lint-imports`,
  `uv run pytest` (CI runs `-m "not integration"`; the ~70 integration tests need Docker and are run
  locally), and `cd mobile && npx tsc --noEmit`.

## 3. Environment

- **The owner uses production, not the laptop**: `https://pharmavique.vercel.app` (Vercel project
  `zikola/pharmavique`, fra1; Neon `pharmavique` in Frankfurt; no Redis there). Measure and verify speed
  and behaviour there too, not only on localhost. `vercel ls --prod` and `vercel inspect <url> --logs` work
  from this machine. A push to `main` deploys production in about two minutes.

- Windows 11. Project: `C:\Users\Laptop World\Downloads\Pharmavique-20261118T213916Z-1-001\Pharmavique`.
  The virtualenv is `.venv` inside it; use `uv run ...`. Shells: Git Bash and PowerShell.
- `docker compose up -d db redis`: Postgres 17 (pg_trgm, pgvector) on 127.0.0.1:5432 and Redis on 6379
  (containers `pharmavique-db-1`, `pharmavique-redis-1`). Docker Desktop once failed to start with
  "sailor-ingest.sock": quit it, rename `%LOCALAPPDATA%\\Docker\\run` and `%LOCALAPPDATA%\\docker-secrets-engine`
  (for example to `run.stale-<date>`), start it again; volumes survive. Never factory-reset. It happened
  again on 2026-11-24 and the same fix worked.
- **API servers left running from earlier sessions** do not reload code. On 2026-11-24 the server on port 8000
  (the one the phone link `http://100.85.219.44:8000` uses) had been running since 2026-11-22, so it served
  code without the search and shortage fixes of 2026-11-23 and 2026-11-24, and port 8002 had another stale
  one. After pulling or changing code, stop them and start the API again, then run `cache-invalidate`
  (the shared Redis cache keeps old search answers for a while).
- **Use `127.0.0.1`, not `localhost`**, in `PHARMAVIQUE_DATABASE_URL` and `PHARMAVIQUE_REDIS_URL`: on this
  Windows machine `localhost` costs about two seconds per new connection (the code fixes it for Redis).
- Tool quirks learned the hard way:
  - big multi-line shell heredocs die with the Bash tool: **write files with the editor tool and run patch
    scripts from files** (the scratchpad);
  - `npx expo lint` installs ESLint and rewrites `package.json` by itself: do not run it;
  - after adding an app route run `npx expo customize tsconfig.json` to regenerate typed routes, then `tsc`;
  - set `PYTHONIOENCODING=utf-8` when printing Arabic from scripts; pytest prints harmless
    "WinError 145" temp-folder warnings;
  - the Bash tool refuses removals it judges risky: say so to the owner instead of working around it;
  - a plain `uv run` / `uv sync` removes the optional `scraper` extra (playwright): use `--all-extras`
    (`daily_refresh.ps1` syncs it itself);
  - piping a patch to `git apply` from Python with `text=True` turns every newline into CRLF on Windows: pass bytes;
  - when measuring the local API in-process, switch off the rate limit and the shared cache, or the
    numbers are 429s and cache hits.

## 4. Run it

```powershell
docker compose up -d db redis
uv sync --all-extras                          # playwright (the crawler) is the optional `scraper` extra
uv run alembic upgrade heads                  # note: heads (one per context; search is at search_0002)
uv run uvicorn pharmavique.bootstrap.api:create_app --factory --port 8000
uv run pharmavique outbox-relay               # delivers catalog events: alerts, radar, cache invalidation
uv run pharmavique worker                     # only with PHARMAVIQUE_JOB_BACKEND=arq
.\scripts\daily_refresh.ps1                   # drugs, relay, digest emails, analytics, cache, lists, pictures
.\scripts\schedule_daily_refresh.ps1 -Time 03:00   # registers it (the owner's action, not done yet)
cd mobile; npx expo start                     # the app; EXPO_PUBLIC_API_URL in mobile/.env.local
```

Other commands: `analytics-rebuild`, `notify-emails`, `cache-invalidate`, `geocode-cities`,
`create-operator --email E`, `search-reindex`, the `sfda-*` family (README section 13). Measuring:
`scripts/loadtest.py` (API under load, results in `docs/PERFORMANCE.md`) and `scripts/scan_eval.py`
(scans, `docs/SCAN_EVALUATION.md`).

## 5. State, by area (details and ADRs: README section 2 and `docs/adr/`)

Done, tested and pushed: the registry (9,144 products loaded), bilingual search, drug page with
provenance, equivalence, shortage to substitutes, compare, similar-name warnings (strong matches only by
default), the assistant (LangGraph, citations, guardrails) and voice, box / prescription / shelf scans,
interactions and contraindications, accounts (email, password and emailed code), saved medicines,
allergies, alerts (in the app and one digest email), the patient's medicine history checked against any
new drug, company and operator views, nearby pharmacies by city, the shared cache, rate limit and job
queue, load-test baselines.

Architecture: 13 contexts under `src/pharmavique/` (`catalog`, `ingestion`, `search`, `substitution`,
`recognition`, `assistant`, `voice`, `knowledge`, `media`, `interactions`, `identity`, `watchlist`,
`analytics`) plus `shared_kernel`, `foundation`, `bootstrap`. ADR-001..016 record the decisions.
Routers and wiring are only in `bootstrap` (`api_*.py`, `*_cli.py`, `*_wiring.py`). The outbox relay has
three subscribers: watchlist alerts, the analytics radar and cache invalidation.

## 6. Pending actions that are the owner's

0. ~~Fill the stored look-alike names in production~~ done on 2026-11-25: **Database migrate** ran (it also
   applied the pending `offers_0001..0003`, empty tables) and **Daily refresh** with steps `names` stored them
   in 1 minute. Production answers similar names from `search.similar_name` (no fallback warnings in the
   Vercel logs), 0.27 to 0.30 s. The nightly run refreshes the table after the reindex.
00. ~~Push the local commits and refresh production (2026-11-24).~~ Pushed on 2026-11-25 (with the latency
   work below). Kept for the record: 14 commits of 2026-11-23 plus the fixes of
   2026-11-24 were only local, so GitHub shows a red cross on 9a99fab (CI failed: the architecture test did not
   list the new `offers` context; the fix is local commit 93f51af). Production (Vercel + Neon) still has the
   bugs fixed on 2026-11-24 (section 9b): checked live on 2026-11-24, `انسولين` finds unrelated products,
   AUGMENTIN 1 G TAB shows 30 "not equivalent" products and none of its 4 equivalents, and EZORA 40 mg (28S),
   PLAXOTRIN (10 ml) and GAVILDA (28S) are shown as short while SFDA lists other packs. After the push, run
   Actions, Daily refresh, Run workflow (steps `lists`) so the shortage links are rebuilt with the new rules,
   and restart the local API on port 8000.
1. **Run the app on a real phone.** It has only been type-checked: location, camera and every new screen
   (sign-up code, my list, company, operator, pharmacies, shelf, prescription check) are untried.
2. ~~JWT secret and `analytics-rebuild`~~ done on 2026-11-22 (the secret is in `.env`, accounts answer 401 for a wrong password).
3. ~~SMTP~~ for the proof of concept, emails go out through a project Gmail account with an app password
   (`PHARMAVIQUE_EMAIL_BACKEND=smtp` in `.env`; the code reached the owner's inbox on 2026-11-22). Gmail caps
   about 500 messages a day, so for many users a real provider and a verified domain are still needed (Q-38).
   `PUBLIC_URL` is the laptop's VPN address, so the unsubscribe link only opens on that network.
4. ~~Schedule the daily refresh~~ registered on 2026-11-22 (task `PharmaviqueDailyRefresh`, 03:00; the laptop must be on).
   The exit code 3 of 2026-11-21 was a lost internet connection (`ERR_NAME_NOT_RESOLVED` at list page 442 of 459),
   not a block. `daily_refresh.ps1` now waits 10 minutes and resumes the same run up to three times, only for network
   errors; a block (401/403/429) or a robots.txt refusal is never retried.
5. ~~`localhost` to `127.0.0.1` in `.env`~~ done.
6. Delete the stray file `C:\LUsers\x` (created by mistake; removal was blocked).
7. Decide about real photos for measuring the scans (Q-32) and a pharmacist reviewing similar names (Q-26).

## 7. What is next

README section 19 is the ordered list. In short: real-phone fixes; real photos and `scan_eval.py`;
shortage and safety-notice alerts (the list loader emits no events); class allergies, password reset,
change of email; exact pharmacy locations (Q-39); the app using the jobs endpoints; deployment for many
users (load balancer, PgBouncer, replica, managed Redis, CDN, object storage); Egypt as a CSV adapter.

## 8. Known limits (do not claim more than this)

- Scans were measured on **generated, clean pictures only** (names read 100%, no invented lines, no dose
  read). Real glare, angles and handwriting are unmeasured.
- Pharmacy addresses are a city plus a national-address code: "nearby" is by city. 32 of 34 cities have a
  point (Al-Namas failed a region sanity check, Alhafoof was not found); the points are unreviewed.
- Similar-name warnings: 605 of 4,859 brands (12%) have a strong match; no pharmacist has reviewed them.
- Interaction data (DDInter 2.0, 234,757 pairs) is incomplete and matches by ingredient name: "nothing found" is
  never "safe". About 18% of DDInter pairs have level `unknown`; the app shows them as "تداخل مسجّل بدون تقييم"
  (for example paracetamol with ibuprofen), never as major. Checked 2026-11-24: warfarin with aspirin major,
  clarithromycin with simvastatin major, amiodarone with digoxin major; no pair with itself; no pair recorded
  twice with two levels. Interactions and contraindications are **not** refreshed daily: they come from fixed
  downloads (DDInter, MeDIC) in `data/interactions/`, not from SFDA.
- Contraindications (MeDIC, 3,960 rows from US/EU/Japan labels) are filtered before they are shown
  (`interactions/application/contraindications.py`, tightened 2026-11-24): the condition must be in the label
  text, in a sentence that says "contraindicated" / "should not" or in a short list item; sentences limited to
  preterm infants, pregnant women, a combination with another drug, or what the drug treats are dropped; a label
  whose opening names a route or form (eye, inhaled, nasal, rectal, vaginal, cream, gel, patch, implant...) is
  dropped; a general name inside a more specific one of the same ingredient ("asthma" inside "status
  asthmaticus") is dropped. A second pass (same day) also drops a condition named only as a qualifier ("with or
  without coma", "shock (nonanaphylactic)", "diarrhea caused by poisoning", "patients with psoriasis
  ... who have", a heading such as "Myocardial Infarction Metoprolol is contraindicated if ..."),
  hedged lines ("probably should not", "may be contraindicated", "should not ordinarily"), lines
  about one strength ("the 10% strength"), NSAID "asthma ... after taking aspirin", inhaler and
  suspension labels, and **every label row for a product used locally** (route or form says skin,
  eye, nose, ear, mouth, rectal, vaginal, inhaled: lidocaine gel is not contraindicated in heart
  block). Shown: 1,068 of 3,960 rows (was 1,985); 372 of them reach a Saudi product, and all 372
  were read one by one on 2026-11-24. This removed real errors on common drugs
  (atorvastatin "atherosclerosis" and "primary hypercholesterolemia", which are its uses; Brufen "tetralogy of
  Fallot" from the IV ibuprofen for preterm babies; injected insulin "COPD" from the inhaled AFREZZA label;
  dexamethasone tablets "glaucoma" from an eye implant; esomeprazole "duodenal ulcer"; pantoprazole
  "bronchospasm"; sildenafil "hepatic impairment" from a dosing sentence; hydrocortisone "ichthyosis" from a
  cream). **What remains is not reviewed by a pharmacist**: the leftovers seen in the review are statements the
  labels really make in a narrow form (enoxaparin "thrombocytopenia" means the antibody-positive kind;
  epinephrine "cardiac dilatation" comes from an old vasopressor label). A pharmacist review of the shown rows is the only way to be sure (like Q-26).
- Row-level security does nothing for a database superuser: production must connect as an ordinary role.
- Drugs: the daily update loads what it read even when a run is partial (`data/refresh/ATTENTION.md` says
  what was not checked). A drug that left the SFDA list is withdrawn only after it is missing from two
  complete runs in a row, at most 50 at once (`sfda-withdraw-absent`, Q-40: both numbers are guesses). A
  change that is only in a details page can take up to a month to be seen (`--recheck 300`).
- The assistant's cited passages (pgvector chunks of the DHPC letters, safety alerts, circulars, RMM and
  safety labeling) are updated by the daily routine for **new rows only**: `knowledge-new-rows` writes a small
  run (`know-<date>`) with the rows that have no chunk yet, their details, files, text and OCR are fetched,
  and `knowledge-build --additive` adds their chunks, then `knowledge-embed` gives them vectors. **Never run
  plain `knowledge-build` on a daily run** (`lists-<date>` holds only `records.jsonl`, so it would replace a
  list's full chunks with thin ones). Checked for real on 2026-11-22: one new RMM row became one chunk with a
  vector, and the other lists kept their chunk counts. A row that was edited (not new) is not re-read.
- The assistant has a `web_search` tool (ADR-017) for a medicine the registry does not know. It is off until
  `PHARMAVIQUE_TAVILY_API_KEY` is set (free plan, 1,000 searches a month), and it has never run against the
  real service: the tests use a mocked transport. Its results are shown as unverified.
- Photos: the assistant screen holds a photo until the question is sent with it (box scan reads the name,
  the name joins the question). Not tried on a phone.
- **The app is a website** (no Expo Go needed): `npm run build:web` in `mobile/`, then the API serves `mobile/dist`
  at `/` (`PHARMAVIQUE_WEB_DIR`, same origin, so no CORS and no http/https mixing). It installs on a phone's
  home screen (manifest, 192/512/180 px icons made from the app logo, standalone display, RTL). Checked in the
  browser pane at 375 px and 1366 px: home, search, a drug page, the assistant answering, deep links and
  reloads. Layout: under 900 px the phone layout; above it a navigation rail on the right and cards in a row
  on the home screen; pushed screens keep a 880 px column. Not built: the two-column drug page and the dense
  results table of the desktop wireframes (B10, C7). Always light. The sign-in token is kept in the browser's
  local storage (no secure store on the web). Camera, microphone and location need HTTPS: over
  `http://100.85.219.44:8000` they do not work; Tailscale HTTPS is not switched on for the tailnet
  (`tailscale serve` needs it enabled in the admin console).
- **Cloudflare Workers AI** (free 10,000 Neurons a day, shared; token and account id in `.env`), measured on
  2026-11-22: the assistant's backup when Groq is rate limited (`Gemma 4 26B`: four real questions answered
  correctly with citations in 31 to 42 s; `gpt-oss-120b` there returned empty text on three of four, `Llama 4
  Scout` wrote tool calls as text); embeddings (`@cf/baai/bge-m3`: cosine 1.0 against six stored vectors, so
  nothing was re-embedded and the stored label stays `baai/bge-m3`); the first vision reader (Llama 4 Scout read
  a test box in 3.5 s for about 12 Neurons). A tool-call message must carry `content: ""`, not null, or
  Cloudflare answers 400 (`CloudflareChatOpenAI`). Groq's free plan allows 8,000 tokens a minute (about one
  assistant answer); three questions at once now all answer, but in 41 to 74 s.
- **Free backups for every model** (owner, 2026-11-24: "no request may break", free models only). Any failure of
  one provider (rate limit, 413, 5xx, 400, timeout, dropped connection) moves the same call to the next; only
  when all fail does the person get "busy" (never a 500). A model that answered 429 is skipped for 60 s.
  | What | Chain, in order |
  |---|---|
  | Assistant and spoken drug name | Groq `gpt-oss-120b` (25 s), Cloudflare `Gemma 4 26B` (45 s), OpenRouter `nemotron-3-ultra-550b-a55b:free`, `gemma-4-31b-it:free` (`llm_backup_models`) |
  | Speech to text | Groq Whisper, then Cloudflare `@cf/openai/whisper-large-v3-turbo` (its own `/ai/run` route: the OpenAI-style audio route does not exist there) |
  | Text to speech | ElevenLabs, then Groq Orpheus Arabic Saudi (each text cut to that provider's length) |
  | Embeddings | bge-m3 on Cloudflare, then on OpenRouter (same vectors, same stored label) |
  | Box and prescription reading | Cloudflare Llama 4 Scout, then the three free OpenRouter vision models (unchanged) |
  Measured 2026-11-24 with real calls: Nemotron 3 Ultra called `search_drugs` with "بنادول" and answered in
  Arabic in 10.6 s; Nemotron 3.5 Lightning searched "Benadryl" and was left out; the free Gemma 4 models were
  rate limited upstream at that moment (they stay last). The whole answer may now take up to 150 s
  (`RUN_TIMEOUT`; Vercel allows 300).
- **What the assistant refuses** (owner, 2026-11-24): only (A) questions outside medicines, chemicals,
  pharmacies, cosmetics and supplements, and (B) deciding for the person: an order to take, stop or switch a
  medicine, "this is the right treatment for you", or any dose. Everything else in the field is answered, with the
  web search when SFDA data lacks it (a medicine from Egypt, what a medicine is for, cosmetics). For symptoms it
  may say which active ingredients are generally used and that a product with one may help, in the same sentence
  telling them to ask the pharmacist or doctor first (`answers.py`: a "you may take" sentence passes only with
  that advice beside it). The number check now removes only the sentence with a number no tool returned
  (`without_ungrounded_sentences`); "31. 65 ريال" is read as 31.65 (`tidy_numbers`), and "[10, 11]" or "[15-18]"
  count as citations (`split_citation_groups`). The real case: the PANTOLOC question was refused because the model
  wrote "31. 65" and the check read "65 ريال".
- **Assistant input** (2026-11-24): what is said into the microphone goes into the text box instead of being sent,
  so it can be read, edited, and sent with a photo. A photo can also go alone ("وش هذا الدواء؟"). Text, voice,
  photo + text and photo + voice all work; a question that came from the microphone is answered by voice too.
- Shortage links (`catalog/domain/list_linking.py`, fixed 2026-11-24): a shortage row counts for a product only
  when it names the product's brand, strength and form; since 2026-11-24 also each strength as many times as the
  product has it ("10 mg/5 mg" is not "5 mg/5 mg") and the same pack when both name one ("14S" is not "28S", a
  "10 ml" vial is not a "20 ml" one). Local result: 1,103 products shown as short (was 1,107). Audit of every
  matched link: the brand is always in the SFDA row's trade names; 19 links still differ from the row text, all
  in the resolved list (generic "DEXTROSE 5%" products against "5% w/v DEXTROSE Injection 250 ml", ATROSOL
  250 mcg/ml against "250 mcg/2 ml", CHAMPIX 0.5 mg against a starter pack) plus Tyenne (no strength in our
  name). Second pass (2026-11-24): a concentration per another volume ("250 mcg/2 ml" is not "250 mcg/ml")
  and a starter pack ("0.5 mg 11 tablets + 1 mg 14 tablets") are conflicts; a product named after its
  substance ("DEXTROSE 5%", "CYTARABINE 100MG-1ML VIAL") is matched only when no more registered products
  fit the row's strength and form than the row names (SFDA writes a generic trade name once per maker).
  Final local result: **1,033 products shown as short** (1,108 links); every matched link was checked
  against the row's trade names; the one textual difference left is Tyenne (no strength in our name, the
  registry strength fits). Ambiguous generic rows are "possible", which the app never shows as short.
  Shortage and resolved status come only from SFDA's two lists; nothing says a pharmacy has stock.
- Equivalence (`substitution/application/compare.py`, tightened 2026-11-24): "equivalent" needs the same
  ingredient names and strengths, the same written dosage form, **the same route** (an IV and an IM vial
  of one drug are not interchangeable: the IM one comes with lidocaine), **the same release and device
  words in the names** (soluble, E.C, XR/SR/MR, retard, pen, vial, inhaler...), **no biologic**
  (biosimilars of insulin, adalimumab, trastuzumab and so on are for the pharmacist), and **names whose
  printed strength agrees with the registry** (SFDA records GARDIA PLUS 8/12.5 with candesartan 16 mg).
  A name may print the total of a combination ("AUGMENTIN 1 G" for 875 + 125 mg).
  Anything else is "possible, needs pharmacist check". Audit of the whole catalog: 14,507 equivalent pairs
  (was 15,652); what still differs between two equivalent names is only brand words (PLUS/HCT/Duo/Trio).
- Equivalence matches ingredient names exactly: "AMOXICILLIN TRIHYDRATE" + "Potassium Clavulanate" (MEGAMOX,
  Vauxlav) is not grouped with "AMOXICILLIN" + "CLAVULANIC ACID", so those are not offered as equivalents of
  AUGMENTIN 1 G (a miss, never a wrong "equivalent").
- Some SFDA registry strengths are written per ml where the product is per 5 ml (CURAM 156.25 mg/5 ml is
  "125 mg/ml" in the registry; MEGAMOX 228 is "600 mg/ml"). The app shows what SFDA states; it is not changed.
- Pictures: of 4,382 shop pictures, 437 are `strength_conflict` (the box shows other strengths, for example
  the AUGMENTIN 1 G TAB picture is a 156 mg suspension box) and 1,126 more come from a shop page whose
  address names another variant or strength (the PANADOL 500 picture is from a "بانادول اكسترا" page,
  QUETTA 25 mg from "quetta-xr-400-mg", LIPICURE 40 from a 10 mg page). Since 2026-11-24 neither is served
  (`catalog/domain/picture_page.py`, checked in the picture store, so production needs no picture reload);
  the app draws its placeholder. 2,819 pictures are shown. 16 mapped picture files are missing on disk. The
  operator screen still counts all 4,382 as "real pictures".
- Arabic search of generic names (fixed 2026-11-24): the registry writes ingredients only in English, so an
  Arabic generic name was found only when an Arabic trade name happened to contain it.
  `search/domain/arabic_names.py` is an alias table of about 95 common generics (Arabic spellings to the English
  name). Measured on 47 common Arabic generic names: 15 failed before, 2 after (`زنك` finds ZINNAT, a misspelled
  `اوزيمبك`). A generic that is not in the table and in no Arabic trade name is still not found: add it there.
- Not built: Redis failover, replicas, CDN, shared picture storage, the pictures image on ghcr (the push
  never completed; the pictures exist only on the laptop), push notifications (dropped), the Egypt adapter.

## 9. Verification record (2026-11-22)

- 1,336 tests collected; the full suite including integration passed before the last changes; CI green on
  the pushed commits.
- Run for real on the development database: sign-up, 403 before confirming, wrong code 400, right code
  200, a digest email for a real product's price change, unsubscribe, deletion; the history check
  (aspirin with warfarin: major, `ddinter-2.0`); the pharmacies endpoints; the load test (single process:
  about 1,000 requests a second from the cache at 10 users, see `docs/PERFORMANCE.md`).
- Faults found by those real runs and fixed: the console email crashed printing Arabic on Windows; an
  empty `PHARMAVIQUE_REDIS_URL` crashed start-up; a wrong geocoder point (Al-Namas) was rejected.

## 9b. Full check of 2026-11-24 (everything in the app today; nothing new started)

Quality gate, real output: `ruff check .` all passed; `ruff format --check .` 572 files formatted; `mypy src
tests` no issues in 513 files; `lint-imports` 8 contracts kept; `pytest` (with integration, Docker up) **1,667
passed** (1,647 before the fixes; 20 new tests, each written failing first); `npx tsc --noEmit` clean;
`npm run build:web` rebuilt `mobile/dist`.

Local database (Docker) checked: 9,186 drugs, all listed, each with a search entry and a picture row (4,382 real,
4,804 drawn cards); 10 SFDA lists (shortage 723, resolved 586, safety alerts 276, labeling 241, circulars 146,
DHPC 105, RMM 579, approvals 462, companies 6,135, pharmacies 385); 10,131 knowledge chunks, every one with a
vector (dhpc 819, circulars 275, rmm 579, safety alerts 1,739, labeling 241, us-labels 6,478); 234,757
interaction pairs; 3,960 contraindication rows. Production has 9,187 drugs (one added on 2026-11-23 is not in the
local copy).

Run against the real API and the website (port 8001, fresh code):
- Search: 64 queries (English, Arabic, misspellings, strength and form, register number, Arabic-Indic digits),
  all under 130 ms; brands right in Arabic and English (`بنادول`, `اوجمنتين`, `augmntin`, `augmentin 1g`,
  `nexium 40`).
- Assistant (real Groq/Cloudflare calls): a shortage question used `search_drugs` + `shortage` with citations;
  warfarin with aspirin used `check_interactions` (major, DDInter, cited); a dose question was refused; an
  unknown name used `sfda_site_check` (live SFDA site, then "not in SFDA's list", cited); Tenazin (added on
  2026-11-23) was found. One run said the SFDA site was unreachable (a single timeout; later calls worked).
- Voice: Saudi text to ElevenLabs speech (3.6 s MP3) and back through Groq Whisper gave the same sentence
  (`باندول` for `بانادول`, which search still finds). Box scan read "Augmentin 156 mg/5 ml suspension" and
  offered AUGMENTIN candidates, marked `needs_review`.
- Website: patient role screen, search with suggestions, drug page with equivalents, shortage banner,
  contraindications; company and operator screens with a temporary local operator account (deleted after).

Faults found and fixed on 2026-11-24 (each with a failing test first):
1. The same-ingredient list dropped the real equivalents (API and the assistant's tool): only the 30 cheapest
   products of the ingredient set were compared, so AUGMENTIN 1 G TAB got suspensions and injections and "no
   equivalent" (the assistant said so too), while 4 equivalent 1 g tablets exist (CLAVODAR, JULMENTIN 2X,
   MEGAMOX 1GM, KLAVOX 1GM) plus 3 "needs pharmacist check". Now every product of the set is compared and the
   closest verdicts are kept (`bootstrap/api_drugs.py`, `bootstrap/assistant_facts.py`).
2. Shortage links: combination strengths compared as sets, pack sizes ignored (section 8).
3. Contraindications shown for conditions the label does not forbid (section 8).
4. Arabic generic-name search (section 8).
5. Pictures whose box states another strength were served as the product's picture (section 8).
6. Company screen: prices shown as "15.100000"; the API's English notes shown on Arabic screens (company, shelf,
   allergy). The app now has its own Saudi notes and two-decimal prices.
7. The daily refresh schedule moved from 01:00 to 01:17 UTC (section 9c).

Second round the same day, before the first push (the owner asked for no wrong information at all):
8. Equivalence: route, release and device words, biologics, name-versus-registry strength (section 8).
9. Shortage: concentration per volume, starter packs, products named after their substance (section 8).
10. Contraindications: qualifiers, hedges, local-use products; all 372 rows that reach a Saudi product read.
11. The assistant took "كونكور 5" for CONCOR 5 PLUS: search results now carry the registered strengths, a
    typed number matches the registered strength, and a name with extra product words is `longer_name`,
    never the product asked about. Checked live: "هل كونكور 5 ناقص؟" answers about CONCOR 5 mg.
12. Pictures from a shop page of another variant or strength (section 8).
13. Scan candidates ignored the strength and form read: "Augmentin 1 g tablets" did not list AUGMENTIN
    1 G TAB. The finder now fetches 25 candidates and orders them by the strength and form read. Checked live
    with a generated prescription (Augmentin 1 g, Panadol 500, Nexium 40: each right product first, dose
    "غير واضح") and a generated shelf (CONCOR, GLUCOPHAGE 500, ZYRTEC 10).
Quality gate after the second round: ruff, format, mypy (517 files), lint-imports (8 kept) all clean;
**pytest 1,702 passed**; `tsc` clean.

Allowed on purpose, not changed: the assistant may repeat a label's "if you faint, stop and call your
doctor" (an existing rule allows a stop instruction in the same sentence as a doctor). Web search results
(Tavily) are used only for a medicine not in the registry and are marked unverified; checked live with
Crocin Advance (found on pharmeasy.in, paracetamol, cited, "not in SFDA's list" checked on the SFDA site).

## 9e. Latency (2026-11-25; numbers in `docs/PERFORMANCE.md`)

The owner found the app slow everywhere. Measured on production and fixed:
- **Cold start 8.2 s to 0.45 s.** The Vercel function was 327 MB (over the 250 MB standard size) because
  playwright was a runtime dependency: it is now the `scraper` extra. Startup imported LangChain, LangGraph
  and the OpenAI client (1.7 s; now loaded on the first question) and made twelve HTTP clients that each
  loaded the certificates (2.2 s; now one shared TLS context). A test keeps those libraries out of startup.
- **Edge cache.** Public answers: `max-age=60, s-maxage=600, stale-while-revalidate=86400`; same-ingredient,
  shortage, similar names, contraindications and compare are cached too; the no-picture 404 for a day; the
  page shell `max-age=0, must-revalidate, s-maxage=3600` (Vercel clears the edge on each deployment).
- **Web scripts 7.3 MB to 1.8 MB** (490 KB compressed): icons come one by one from
  `mobile/src/components/icons.ts`; add a new icon there, never import `phosphor-react-native` directly.
- **Assistant 29-65 s to 4.5-7.6 s** on production. Groq's free plan allows 8,000 tokens a minute per model
  and a question uses 10,000-16,000, so: Groq `gpt-oss-20b` (its own limit) follows `gpt-oss-120b`; Gemma on
  Cloudflare runs with thinking off (`cloudflare_llm_thinking`, 11.7 s to 2.5 s for one answer; a leftover
  "thought" marker is stripped); tool results go as compact JSON; documents as 4 passages of 800 characters
  (six of 1,200 made one call 12,500 tokens, which Groq refuses outright); backup timeout 25 s.
- **Similar names.** The index read only names (`CatalogNames.trade_names`, 0.04 s) and reduces each brand once:
  3.1 s to 2.6 s on Vercel's first call. Then the daily refresh stores every product's look-alikes
  (`search.similar_name`, 126 s for 9,186 products locally) and the API reads one row: 0.05 s, the same answers
  as the index on 200 of 200 sampled products. Filled in production on 2026-11-25: 0.27 to 0.30 s there.
- **The nightly refresh is slow** (run of 2026-11-25, drugs and lists: 2 h 41 min): `drugs-update` 52 min,
  **`drugs-load` 69 min** (loading the changes into Neon), `lists-crawl` 35 min (exit 2, partial, so the quick
  check did not skip it). Not changed yet; `drugs-load` is the first place to look.
- Not done: thumbnails of the product pictures (median 53 KB, 10% above 283 KB, largest 4.3 MB, shown at
  72 px); streaming the assistant's progress to the app; a provider with a larger free token limit.

## 9c. The daily refresh on GitHub (checked 2026-11-24)

What it refreshes every day (`scripts/daily_refresh.sh`, `.github/workflows/daily-refresh.yml`, into Neon):
- **Drugs** (SFDA drug list, about 9,190): re-read; changed details loaded; prices tracked; a drug missing from
  two complete runs is withdrawn (at most 50). Last scheduled run (2026-11-23): 9,187 rows, 42 added, 17 removed,
  14 changed, 11 price changes; status `partial` (5 rows the pager promised were not returned), so nothing was
  withdrawn; one product rejected (`1708260283`, no ingredient line).
- **Lists**: shortage, resolved shortage, safety alerts, safety labeling, circulars, DHPC, RMM, approvals. A list
  is loaded only when its crawl has at least 85% of the baseline rows. The shortage detail pages (trade names)
  are read before loading. New DHPC, alert, circular, RMM and labeling rows get chunks and vectors for the
  assistant (no OCR on GitHub: scanned PDFs get no text).
- **Schedule per list and the quick check** (added 2026-11-24, details in `docs/SCRAPING_ON_GITHUB.md`): the
  fast lists every night, the two shortage lists again at 13:17 UTC, the pharmacies on Fridays, the drug
  companies on the 1st of the month. Every list run starts with a two-page quick check and reuses the last
  complete run when nothing changed; a full crawl still runs at least weekly. The first night after this
  change still does full crawls (earlier runs carry no `full_crawl_at`).
- **Not refreshed daily**: the interaction and contraindication data (fixed downloads, not SFDA) and the
  pictures (`Pictures load` is manual).
- `cache-invalidate` exits 4 on GitHub: production has no shared cache, so this is expected.
- **Look-alike names** (added 2026-11-25): `similar-names-rebuild` runs after `search-reindex` in the drugs
  step; `STEPS=names` (or the workflow input `names`) runs it alone.

Runs seen: the only scheduled run so far (2026-11-23) started at 08:25 UTC instead of 01:00 (7.5 h late) and
succeeded in 1 h 51 min; the run of **2026-11-24 had not started at 08:32 UTC**. GitHub delays or drops
scheduled runs at the start of an hour when busy, so the cron is now `17 1 * * *` (in effect once pushed). If a
day is missed, run it by hand (Actions, Daily refresh, Run workflow). The manual runs of 2026-11-23 (10:52 and
12:33, lists only) succeeded. Production checked live on 2026-11-24: the shortage status of 8 sampled products
agrees with the current rules, except the pack-size cases fixed today (section 6, item 0).

The laptop's own task `PharmaviqueDailyRefresh` (03:00) ran at 09:54 on 2026-11-24 because the laptop was off at
03:00; Docker was down at that moment and the run ended with code 0xC000013A, nothing loaded, leaving
`data/refresh/running.lock`. The lock is ignored after 12 hours, so the next run is not blocked. The laptop task
writes only to the local database; production is refreshed by GitHub.

## 9d. Pharmacies: the current situation (2026-11-24)

Two different things:

1. **SFDA's list of licensed pharmacies** (385 rows: name, phone, address code, region; no website, no stock).
   About 110 are Nahdi, then Al Dawaa, Lemon, United, Adam. "Nearby pharmacies" works by city: 32 of 34 cities
   have a point (OpenStreetMap, unreviewed); `/v1/pharmacies`, `/v1/pharmacies/cities` and
   `/v1/pharmacies/nearby` answer. Loaded once, not refreshed daily. Exact locations: Q-39.
2. **Pharmacy catalogs (prices, availability, pictures, descriptions), context `offers`** (ADR-019,
   `docs/PHARMACY_SCRAPING_PLAN.md`, `docs/PHARMACY_VALIDATION.md`), approved by the owner on 2026-11-23 (D-1 to
   D-12). Done: phase 1 (schema, matching, lifecycle and price rules, tests) and phase 2 (5 pilot sites validated:
   Nahdi, United, Innova, Adam, Dr. Move; Al-Dawaa, Lemon and Kunooz refuse automated clients with 403 and are not
   bypassed). Phase 3 started: the first loads stored **21,239 listings** (Nahdi 7,108, Adam 5,323, United
   4,689, Innova 2,938, Dr. Move 1,181) of about 130,000 in the sitemaps, with 21,239 prices and 221 downloaded
   pictures; 2,758 addresses skipped (category pages, robots rules). Dr. Move hit its rate limit twice (runs
   marked `blocked`; the crawler now waits 15 s per page there). Five runs of 2026-11-23 never finished (the
   laptop stopped; they stay `partial` with no end time) and **no crawl is running now**. Not done: the rest of
   the first load (days of polite crawling), matching to SFDA products (0 matches so far; phase 4 needs a human
   review of 100 pairs), the daily offers workflow (phase 5) and anything in the app (phase 7). No offers data
   is shown to users.

## 10. Git

Branch `main`, remote `origin` = https://github.com/Eslamusamaaa/Pharmavique. On 2026-11-24 `main` was 14
commits ahead of `origin/main` (not pushed), plus the uncommitted fixes of that day (section 9b). Untracked files that must
stay out of commits: `claude-code-prompt.md`, `expo-go-qr.png`, `data/media/placeholders/`. `data/` is
git-ignored (databases dumps, crawls, pictures); `data/README.md` says how to rebuild each folder.
