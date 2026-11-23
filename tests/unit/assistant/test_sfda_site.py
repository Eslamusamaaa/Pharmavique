"""The live search of SFDA's official drug list: what it reads, and what it never claims."""

import httpx
import pytest

from pharmavique.assistant.infrastructure.sfda_site import (
    SfdaSiteError,
    SfdaSiteSearch,
    parse_results,
)

FOUND = """
<form></form>
<table class="table responsive-enabled table-striped">
  <thead><tr><th>Scientific Name</th><th>Trade Name</th><th>Strength</th>
  <th>Doesage Form</th><th>Price</th><th>Details</th></tr></thead>
  <tbody><tr class="odd">
    <td>DICLOFENAC POTASSIUM</td><td>CATAFLAM 50MG TABLET</td><td>50</td>
    <td>Coated tablet</td><td>31.7</td>
    <td><a href="/en/details_data?nid=17582&amp;id=0207245466&amp;page=0">Details</a></td>
  </tr></tbody>
</table>
"""
NOTHING = "<form></form>\n\nNo Results Found\n\n<div></div>"


def test_a_result_row_keeps_the_fields_the_site_shows() -> None:
    rows = parse_results(FOUND, "https://sfda.test")

    assert rows == [
        {
            "register_number": "0207245466",
            "scientific_name": "DICLOFENAC POTASSIUM",
            "trade_name_en": "CATAFLAM 50MG TABLET",
            "strength": "50",
            "dosage_form": "Coated tablet",
            "price": "31.7",
            "source_ref": "https://sfda.test/en/details_data?nid=17582&id=0207245466&page=0",
        }
    ]


def test_a_page_that_says_no_results_is_an_empty_answer() -> None:
    assert parse_results(NOTHING, "https://sfda.test") == []


def test_a_page_that_is_neither_is_never_read_as_not_found() -> None:
    with pytest.raises(SfdaSiteError):
        parse_results("<html><body>Service unavailable</body></html>", "https://sfda.test")


def client_for(handler: httpx.MockTransport) -> SfdaSiteSearch:
    return SfdaSiteSearch(
        base_url="https://sfda.test",
        client=httpx.AsyncClient(transport=handler),
        min_gap=0.0,
    )


async def test_a_name_with_no_match_gives_one_citable_no_result_record() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=NOTHING)

    records = await client_for(httpx.MockTransport(handler)).lookup("Redoxon", 5)

    assert str(seen[0].url) == "https://sfda.test/en/drugs-list?TradeName=Redoxon"
    assert "DrugRegistrySync" in seen[0].headers["user-agent"]
    assert len(records) == 1
    assert records[0]["found"] == 0
    assert records[0]["url"] == "https://sfda.test/en/drugs-list?TradeName=Redoxon"
    assert "Redoxon" in records[0]["title"]


async def test_the_same_name_is_asked_once_within_the_cache_time() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=FOUND)

    search = client_for(httpx.MockTransport(handler))
    first = await search.lookup("Cataflam", 5)
    second = await search.lookup("cataflam", 5)

    assert calls == 1
    assert first == second
    assert first[0]["trade_name_en"] == "CATAFLAM 50MG TABLET"
    assert first[0]["title"].startswith("CATAFLAM 50MG TABLET")


async def test_a_site_that_fails_is_an_error_not_a_no_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(SfdaSiteError):
        await client_for(httpx.MockTransport(handler)).lookup("Redoxon", 5)
