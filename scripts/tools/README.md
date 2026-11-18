# One-off tools

Helpers used while building and measuring the system. They are **not product code**: not linted,
not tested, and they read the local `data/` folders. Run them with the project's Python
(`%USERPROFILE%\.venvs\pharmavique\Scripts\python.exe -X utf8 scripts\tools\<file>`).

| File | What it does |
|---|---|
| `pick_brands_to_search.py [N]` | Picks the next N brands (retail dosage forms first, each brand once) that still have no real picture, and writes `data/media/manual/batch.json`. Used for the by-hand web search of brand names; `data/media/manual/state.json` remembers which brands were searched |
| `eval_search_recall.py` | Recall of the in-memory search index on generated misspellings of real drug names (the measurement behind "recall@1 76% to 96%") |
| `eval_bm25_descriptive.py` | Precision of trigram vs BM25 vs fusion on descriptive queries such as "ibuprofen tablet" |
| `probe_sfda_lists.py <paths>` | One polite request per SFDA list page: columns, pager size, CAPTCHA markers |
| `grab_one_picture.py <page> <name> <query>` | Fetches one product page politely, validates and saves its picture (a demo of the pipeline) |
| `clean_stored_pictures.py` | Removes stored pictures that are shop logos or listing-page images, and reopens those drugs |
