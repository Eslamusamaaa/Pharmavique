"""Read one product page: the JSON-LD `Product` every pilot site publishes, plus the HTML text block
that holds the description where JSON-LD has none.

Nothing is guessed. A field the page does not state is None; a price without a stated currency keeps
currency None (unconfirmed); ingredients are filled only from a passage the page itself labels so.
"""

import html as html_lib
import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from pharmavique.offers.domain.category import extract_pack_text
from pharmavique.offers.domain.forms import dosage_form_key
from pharmavique.offers.domain.model import Availability
from pharmavique.offers.domain.page import ParsedProduct
from pharmavique.offers.infrastructure.config import RetailerConfig
from pharmavique.shared_kernel.text import normalize_text

__all__ = ["decode", "html_block_text", "parse_product"]

_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_HOME = {"home", "الرئيسيه", "الرئيسية"}
_IN_STOCK = {"instock", "limitedavailability", "onlineonly", "instoreonly", "presale"}
_OUT_OF_STOCK = {"outofstock", "soldout", "discontinued"}
_INGREDIENTS = re.compile(
    r"(?i)(active ingredients?|ingredients?|composition|المادة الفعالة|المواد الفعالة|المكونات|"
    r"التركيبة|التركيب)\s*[:\uff1a]\s*([^\n]{3,300})"
)
_VOID = {"br", "img", "input", "hr", "meta", "link", "source", "area", "base", "col", "wbr"}
_BREAK = {"p", "div", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br", "table"}


def decode(content: bytes, declared: str | None = None) -> str:
    """The page text: UTF-8 when the bytes are valid UTF-8 (what these sites send, whatever their
    headers say), otherwise the declared charset, otherwise Windows-1252."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode(declared or "cp1252", errors="replace")


def _json_ld(page: str) -> list[Any]:
    found: list[Any] = []
    for block in _LD.findall(page):
        try:
            found.append(json.loads(block.strip()))
        except ValueError:
            continue
    return found


def _nodes(node: Any, kind: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found += _nodes(item, kind)
    elif isinstance(node, dict):
        types = node.get("@type")
        if kind == types or (isinstance(types, list) and kind in types):
            found.append(node)
        for key in ("@graph", "mainEntity"):
            if key in node:
                found += _nodes(node[key], kind)
    return found


class _BlockText(HTMLParser):
    """The text of the first element that has every wanted class name."""

    def __init__(self, wanted: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._wanted = wanted
        self._depth = 0
        self._inside = False
        self.done = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done:
            return
        if not self._inside:
            classes = set((dict(attrs).get("class") or "").split())
            if self._wanted <= classes:
                self._inside, self._depth = True, 1
            return
        if tag in _BREAK:
            self.parts.append("\n- " if tag == "li" else "\n")
        if tag not in _VOID:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._inside or self.done or tag in _VOID:
            return
        if tag in _BREAK:
            self.parts.append("\n")
        self._depth -= 1
        if self._depth == 0:
            self.done = True

    def handle_data(self, data: str) -> None:
        if self._inside and not self.done:
            self.parts.append(data)


def html_block_text(page: str, class_names: Iterable[str]) -> str | None:
    """The text of the first HTML element with all of `class_names`, lines kept; else None."""
    wanted = set(class_names)
    if not wanted:
        return None
    parser = _BlockText(wanted)
    parser.feed(page)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in "".join(parser.parts).split("\n")]
    text = "\n".join(ln for ln in lines if ln and ln != "-")
    return text or None


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = html_lib.unescape(str(_first(value))).strip()
    return re.sub(r"[ \t\xa0]+", " ", text) or None


def _offer(product: dict[str, Any]) -> dict[str, Any]:
    offer = _first(product.get("offers"))
    if isinstance(offer, dict) and isinstance(offer.get("offers"), list) and offer["offers"]:
        inner = offer["offers"][0]
        offer = {**offer, **inner} if isinstance(inner, dict) else offer
    return offer if isinstance(offer, dict) else {}


def _price(offer: dict[str, Any]) -> Decimal | None:
    raw = offer.get("price", offer.get("lowPrice"))
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", ""))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _availability(offer: dict[str, Any]) -> Availability:
    word = str(offer.get("availability") or "").rsplit("/", 1)[-1].lower()
    if word in _IN_STOCK:
        return Availability.IN_STOCK
    if word in _OUT_OF_STOCK:
        return Availability.OUT_OF_STOCK
    return Availability.UNKNOWN


def _images(product: dict[str, Any]) -> tuple[str, ...]:
    raw = product.get("image")
    items = raw if isinstance(raw, list) else [raw]
    urls: list[str] = []
    for item in items:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url.startswith("http") and url not in urls:
            urls.append(url)
    return tuple(urls)


def _barcode(product: dict[str, Any], offer: dict[str, Any]) -> str | None:
    for source in (product, offer):
        for key in ("gtin", "gtin14", "gtin13", "gtin12", "gtin8"):
            value = str(source.get(key) or "").strip()
            if value.isdigit() and 8 <= len(value) <= 14:
                return value
    return None


def _category_path(page_nodes: list[Any], product: dict[str, Any], name: str) -> tuple[str, ...]:
    for crumb in _nodes(page_nodes, "BreadcrumbList"):
        names: list[str] = []
        for entry in crumb.get("itemListElement", []):
            item = entry.get("item")
            label = entry.get("name") or (item.get("name") if isinstance(item, dict) else None)
            if label:
                names.append(_clean(label) or "")
        names = [n for n in names if n]
        if names and normalize_text(names[0]) in _HOME:
            names = names[1:]
        if names and normalize_text(names[-1]) == normalize_text(name):
            names = names[:-1]
        if names:
            return tuple(names)
    raw = product.get("category")
    values = raw if isinstance(raw, list) else [raw]
    parts = [p.strip() for v in values if isinstance(v, str) for p in re.split(r"[>/|]", v)]
    return tuple(p for p in parts if p)


def _ingredients(text: str | None) -> str | None:
    if not text:
        return None
    found = _INGREDIENTS.search(text)
    return found.group(2).strip().lstrip("-• ").strip() if found else None


def _source_id(product: dict[str, Any], url: str) -> str | None:
    for key in ("sku", "mpn"):
        value = str(_first(product.get(key)) or "").strip()
        if value:
            return value
    tail = re.search(r"/(?:pdp/|p)?(\d{3,})$", url.split("?")[0])
    return tail.group(1) if tail else None


def parse_product(page: str, url: str, config: RetailerConfig) -> ParsedProduct | None:
    """The product a page describes, or None when the page is not a product page."""
    nodes = _json_ld(page)
    products = _nodes(nodes, "Product")
    if not products:
        return None
    product = products[0]
    name = _clean(product.get("name"))
    source_id = _source_id(product, url)
    if not name or not source_id:
        return None
    offer = _offer(product)
    brand = product.get("brand")
    brand_name = _clean(brand.get("name") if isinstance(brand, dict) else brand)
    json_description = _clean(product.get("description"))
    block = html_block_text(page, config.description_class)
    description = block if block and len(block) > len(json_description or "") else json_description
    if description and description == name:
        description = None
    currency = _clean(offer.get("priceCurrency"))
    return ParsedProduct(
        source_id=source_id,
        url=url,
        name=name,
        language=config.language,
        brand=brand_name,
        category_path=_category_path(nodes, product, name),
        description=description,
        ingredients_text=_ingredients(description),
        barcode=_barcode(product, offer),
        image_urls=_images(product),
        price=_price(offer),
        currency=currency.upper() if currency else None,
        availability=_availability(offer),
        pack_text=extract_pack_text(name),
        dosage_form_text=dosage_form_key(name),
    )
