"""The words of the `offers` context: what a pharmacy listing is and in which state it can be.

A listing is a retailer's statement about a product (unofficial), never the registry's. Every enum
here is stored as text with a `CHECK` in the schema, so a typo cannot become data.
"""

from enum import StrEnum


class ListingCategory(StrEnum):
    MEDICINE = "medicine"
    COSMETIC = "cosmetic"
    DEVICE = "device"
    OTHER = "other"  # supplements, food, baby care: whatever the retailer's category map names so
    UNCLASSIFIED = "unclassified"  # the retailer's category is not in its map: never matched

    @property
    def eligible_for_registry_match(self) -> bool:
        """Only medicines are compared with SFDA's medicine registry."""
        return self is ListingCategory.MEDICINE


class ListingStatus(StrEnum):
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"  # the page exists and says it cannot be bought
    MISSING = "missing"  # absent from two complete runs in a row; nothing is deleted
    DISCONTINUED = "discontinued"  # the retailer's own URL says it is gone


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    POSSIBLE = "possible"  # shown only as "possible match, ask a pharmacist"
    NEEDS_REVIEW = "needs_review"  # ambiguous or self-contradicting: a person decides, never shown
    NO_MATCH = "no_match"
    NOT_APPLICABLE = "not_applicable"  # cosmetics, devices, anything that is not a medicine


class JobType(StrEnum):
    DISCOVER = "discover"
    UPDATE = "update"
    PRICE = "price"
    AVAILABILITY = "availability"


class RunStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class RetailerStatus(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    RETIRED = "retired"
