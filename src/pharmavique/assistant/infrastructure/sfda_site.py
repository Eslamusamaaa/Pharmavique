"""`SfdaSiteLookup`: search SFDA's official drug list on sfda.gov.sa by trade name, live.

The assistant uses it after our own copy of the registry found nothing, so "not in the SFDA drug
list" rests on the site itself and not only on a copy that may be days old. One plain GET of
`/en/drugs-list?TradeName=<name>` (the same list page the daily crawler reads; robots.txt allows
it), a clear User-Agent, at most one request every `min_gap` seconds, and answers kept for an hour.

A page that is neither a result table nor the site's "No Results Found" is an error, never "not
found": a failing site must not turn into a claim about a drug.
"""

import asyncio
import time
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.sfda.gov.sa"
USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"
NO_RESULTS = "No Results Found"
_COLUMNS = {
    "scientific name": "scientific_name",
    "trade name": "trade_name_en",
    "strength": "strength",
    "doesage form": "dosage_form",  # the site's own spelling
    "price": "price",
}


class SfdaSiteError(Exception):
    """The site did not answer, or answered a page this code does not understand."""


def parse_results(html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        if NO_RESULTS in soup.get_text(" "):
            return []
        raise SfdaSiteError("the SFDA drug list page has no result table")
    headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
    rows: list[dict[str, Any]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        row: dict[str, Any] = {}
        for header, cell in zip(headers, cells, strict=False):
            field = _COLUMNS.get(header)
            if field is not None:
                row[field] = cell.get_text(" ", strip=True)
        link = tr.find("a", href=True)
        if link is not None:
            href = str(link["href"])
            row["source_ref"] = urljoin(base_url + "/", href)
            number = parse_qs(urlparse(href).query).get("id")
            if number:
                row["register_number"] = number[0]
        if row.get("trade_name_en"):
            rows.append({"register_number": row.pop("register_number", None), **row})
    if not rows:
        raise SfdaSiteError("the SFDA drug list table has no readable rows")
    return rows


class SfdaSiteSearch:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        min_gap: float = 1.5,
        ttl: float = 3600.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=12.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._min_gap = min_gap
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def search_url(self, trade_name: str) -> str:
        return f"{self._base_url}/en/drugs-list?TradeName={quote(trade_name)}"

    async def lookup(self, trade_name: str, limit: int) -> list[dict[str, Any]]:
        name = " ".join(trade_name.split())
        url = self.search_url(name)
        key = name.lower()
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < self._ttl:
            return cached[1][:limit]
        async with self._lock:
            wait = self._min_gap - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
            try:
                response = await self._client.get(url, headers={"User-Agent": USER_AGENT})
            except httpx.HTTPError as error:
                raise SfdaSiteError(
                    f"the SFDA site is unreachable: {type(error).__name__}"
                ) from error
        if response.status_code != 200:
            raise SfdaSiteError(f"the SFDA site answered HTTP {response.status_code}")
        rows = parse_results(response.text, self._base_url)
        if rows:
            records = [
                {**row, "title": f"{row['trade_name_en']} · قائمة أدوية الهيئة (SFDA)", "url": url}
                for row in rows
            ]
        else:
            records = [
                {
                    "found": 0,
                    "searched": name,
                    "result": "no drug with this trade name in SFDA's drug list",
                    "title": f'بحث "{name}" في قائمة أدوية الهيئة (SFDA)',
                    "url": url,
                }
            ]
        self._cache[key] = (time.monotonic(), records)
        return records[:limit]
