# ADR-017: a web search tool for medicines the registry does not know

Status: accepted, 2026-11-22 (owner: a photographed medicine that is not in the SFDA registry, for
example one sold in Egypt, should still get an answer: its active ingredient, what it is used for,
and which Saudi products have the same ingredient).

## Context

The assistant answers only from the registry, the official documents and the interaction data
(ADR-007). For a medicine the registry does not list it can only say "not in our sources". Many
boxes people photograph come from other countries, so that answer is often the whole answer.

## Decision

- **The assistant gets one more tool, `web_search`**, offered only when a search key is configured
  (`PHARMAVIQUE_TAVILY_API_KEY`). Without a key nothing changes.
- **Provider: Tavily.** `POST https://api.tavily.com/search`, `Authorization: Bearer <key>`, body
  fields `query`, `search_depth`, `max_results`, `topic`; results carry `title`, `url`, `content`.
  Free plan: 1,000 credits a month, one credit per basic search, no card (its documentation, read on
  2026-11-22). Not chosen: Serper (its endpoint and fields could not be verified from its pages),
  Brave (no free plan any more), Google Custom Search (closed to new users). A self-hosted SearXNG
  stays an option if the free quota is not enough. Behind the `WebSearch` port, so the provider can
  change.
- **What may be searched:** the product's name and ingredient words, nothing about the person. The
  prompt says so, the query is limited to 120 characters, and a question gets at most 2 searches.
- **How the result is treated:** it is retrieved data of trust `unofficial_unverified`
  (`CLAUDE.md` domain rules; this is the owner's exception to "answers only from the registry and
  the documents"). It is cited like any record, as kind `web` with its address, and the answer
  must say that it comes from the web and is not verified by SFDA.
- **What the web can never supply:** a dose, a schedule, a price, stock or a legal status, and no
  equivalence. Equivalence stays the verdict of `same_ingredient`, which needs a registered
  product, so for a foreign product the assistant may only say that Saudi products with the same
  ingredient are *possible* alternatives and a pharmacist checks strength and form.
- **A web-only answer is not "grounded"** in the registry: the API says `web: true`, the app shows
  "معلومات من الإنترنت، غير موثّقة من الهيئة", and `grounded` stays false.
- **Egypt:** no scraping and no bypass of the Egyptian registry's check. The tool never fetches a page,
  only the search provider's snippets.
- **The photo:** the assistant screen gets a photo button. The photo goes through the existing box
  scan (the vision reader only transcribes), and the transcribed name becomes the question. No
  image goes to the assistant's language model.

## Limits to remember

- A snippet can be wrong, old or about another country's product. How well Egyptian brand names are
  found on the open web is not measured.
- Numbers in a snippet count as known facts for the grounding check (the same check that withholds
  invented numbers), so the prompt, not the check, keeps prices and doses out.
- 1,000 searches a month is about 33 a day: enough for a proof of concept, not for many users.
