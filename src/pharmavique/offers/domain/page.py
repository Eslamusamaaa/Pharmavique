"""What one product page says, as the retailer states it. Nothing here is the registry's data."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from pharmavique.offers.domain.model import Availability

__all__ = ["ParsedProduct"]


@dataclass(frozen=True, slots=True)
class ParsedProduct:
    source_id: str  # the retailer's own product id (its SKU)
    url: str
    name: str  # in the language of the page
    language: str  # "en" or "ar"
    brand: str | None
    category_path: tuple[str, ...]  # the retailer's breadcrumb without "Home" and the product
    description: str | None  # the page's own text, line breaks kept
    ingredients_text: str | None  # only when the page labels a passage as ingredients
    barcode: str | None
    image_urls: tuple[str, ...]
    price: Decimal | None
    currency: str | None  # as the page states it; None means unconfirmed
    availability: Availability
    pack_text: str | None
    dosage_form_text: str | None

    @property
    def details_hash(self) -> bytes:
        """A fingerprint of everything except price and stock; it changes with the details."""
        body = json.dumps(
            [
                self.name,
                self.brand,
                list(self.category_path),
                self.description,
                self.ingredients_text,
                self.barcode,
                list(self.image_urls),
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(body.encode("utf-8")).digest()[:16]

    @property
    def price_amount(self) -> Decimal | None:
        return None if self.price is None else self.price.quantize(Decimal("0.01"))
