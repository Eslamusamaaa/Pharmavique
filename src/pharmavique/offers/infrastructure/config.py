"""A retailer is a configuration file (config/retailers/<id>.toml), not code.

Adding a retailer on a platform we already read is a new file; code is written only for a platform
we cannot read yet.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = ["RetailerConfig", "load_retailer", "load_retailers"]


@dataclass(frozen=True, slots=True)
class RetailerConfig:
    id: str
    name: str
    base_url: str
    platform: str  # "jsonld" for every site read so far; a new platform gets its own parser
    market: str
    language: str  # the language of the pages we read ("en" or "ar")
    sitemaps: tuple[str, ...]  # sitemap files or indexes to start from
    min_interval: float = 2.0  # seconds between requests, never below the site's Crawl-delay
    currency: str | None = None  # only what the site states; None means "as each page says"
    url_include: str | None = None  # a regex a product address must match
    url_exclude: str | None = None  # a regex that rules an address out
    sitemap_include: str | None = None  # a regex a child sitemap address must match
    description_class: tuple[str, ...] = ()  # class names of the HTML block holding the description


def _config(data: dict[str, object]) -> RetailerConfig:
    def text(key: str) -> str | None:
        value = data.get(key)
        return str(value) if value else None

    return RetailerConfig(
        id=str(data["id"]),
        name=str(data["name"]),
        base_url=str(data["base_url"]).rstrip("/"),
        platform=str(data.get("platform", "jsonld")),
        market=str(data.get("market", "SA")),
        language=str(data.get("language", "en")),
        sitemaps=tuple(str(s) for s in data["sitemaps"]),  # type: ignore[attr-defined]
        min_interval=float(data.get("min_interval", 2.0)),  # type: ignore[arg-type]
        currency=text("currency"),
        url_include=text("url_include"),
        url_exclude=text("url_exclude"),
        sitemap_include=text("sitemap_include"),
        description_class=tuple(str(c) for c in data.get("description_class", ())),  # type: ignore[attr-defined]
    )


def load_retailer(path: Path) -> RetailerConfig:
    return _config(tomllib.loads(path.read_text(encoding="utf-8")))


def load_retailers(folder: Path) -> dict[str, RetailerConfig]:
    found = [load_retailer(p) for p in sorted(folder.glob("*.toml"))]
    return {c.id: c for c in found}
