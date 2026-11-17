"""A picture of a drug found on the web, with where it came from and how far to trust it."""

from dataclasses import dataclass
from enum import StrEnum

from pharmavique.media.domain.matching import MatchVerdict
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.provenance import Provenance


class ImageStatus(StrEnum):
    MATCHED = "matched"  # the page names the drug and shows Saudi evidence
    NEEDS_REVIEW = "needs_review"  # the page names the drug, nothing says Saudi
    CONFIRMED = "confirmed"  # a person confirmed it
    REJECTED = "rejected"  # a person rejected it

    @classmethod
    def from_verdict(cls, verdict: MatchVerdict) -> "ImageStatus":
        if verdict is MatchVerdict.MATCHED:
            return cls.MATCHED
        if verdict is MatchVerdict.NEEDS_REVIEW:
            return cls.NEEDS_REVIEW
        raise ValueError("a rejected candidate is never stored as an image")


@dataclass(frozen=True, slots=True)
class ProductImage:
    market: Market
    register_number: str
    image_url: str
    page_url: str
    query: str  # the search phrase that found it
    status: ImageStatus
    score: float
    signals: tuple[str, ...]
    content_hash: str  # sha256 of the stored bytes; the same picture is kept once
    content_type: str
    size_bytes: int
    storage_key: str  # where the bytes live in object storage
    provenance: Provenance  # unofficial_unverified: found by search, not given by an authority

    @property
    def publishable(self) -> bool:
        """Only pictures a rule or a person approved may be shown as the product's picture."""
        return self.status in (ImageStatus.MATCHED, ImageStatus.CONFIRMED)
