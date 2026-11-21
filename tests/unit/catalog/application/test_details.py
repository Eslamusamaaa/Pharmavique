"""The catalog's detail view of one product (drug page), and products with the same ingredients."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from pharmavique.catalog.application.ports import PricePair, StoredProduct
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.domain.product import ListingStatus, ProductData
from pharmavique.catalog.domain.values import (
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
    ProductId,
)
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

FETCHED = datetime(2026, 11, 17, 7, 56, tzinfo=UTC)
PROVENANCE = Provenance(
    "sfda-drugs-list-web", "https://www.sfda.gov.sa/en/x", FETCHED, "run-1", TrustLevel.OFFICIAL
)


def stored(number: str, *ingredients: str, **data: object) -> StoredProduct:
    lines = ingredients or ("ACMEDRONE",)
    fields: dict[str, object] = {
        "trade_name": LocalizedText(f"TRADE-{number}", f"تجاري-{number}"),
        "ingredients": tuple(IngredientLine(n, Decimal("5"), "mg") for n in lines),
        "dosage_form": LocalizedText("Tablet", "قرص"),
    }
    fields.update(data)
    return StoredProduct(
        id=ProductId(Market.SA, number),
        data=ProductData(**fields),  # type: ignore[arg-type]
        listing_status=ListingStatus.LISTED,
        provenance=PROVENANCE,
    )


class FakeReader:
    def __init__(self, *products: StoredProduct) -> None:
        self.products = list(products)

    async def get_many(
        self, market: Market, register_numbers: Sequence[str]
    ) -> list[StoredProduct]:
        return [p for p in self.products if p.id.register_number in register_numbers]

    async def page(self, market: Market, after: str | None, limit: int) -> list[StoredProduct]:
        return []

    async def with_ingredient_set(
        self, market: Market, names: Sequence[str], limit: int
    ) -> list[StoredProduct]:
        wanted = sorted(n.upper() for n in names)
        return [
            p for p in self.products if sorted(i.name.upper() for i in p.data.ingredients) == wanted
        ][:limit]


async def test_details_carry_every_field_the_drug_page_shows() -> None:
    product = stored(
        "1-1",
        route=LocalizedText("Oral use", "عن طريق الفم"),
        package=Package(package_type="Blister", package_size=24),
        legal_status=CodedValue("OTC", "otc"),
        distribution_site=CodedValue("Pharmacy", "pharmacy"),
        authorization_status=CodedValue("Valid", "valid"),
        marketing_status=CodedValue("Marketed", "marketed"),
        atc_codes=(AtcCode("N02BE01"),),
        shelf_life="48",
        storage_conditions=LocalizedText("store below 30°c", "يحفظ تحت 30"),
        marketing_company=Party("ACME PHARMA", "Ireland"),
        manufacturers=(Party("MAKER LTD", "Saudi Arabia"),),
        price=Money(Decimal("7.25"), Currency.owner_assumed("SAR")),
    )
    handler = ReadProductCardsHandler(FakeReader(product))

    details = await handler.get_details(Market.SA, "1-1")

    assert details is not None
    assert details.card.register_number == "1-1"
    assert [(i.name, i.strength, i.unit) for i in details.ingredients] == [("ACMEDRONE", "5", "mg")]
    assert (details.route_en, details.route_ar) == ("Oral use", "عن طريق الفم")
    assert (details.package_type, details.package_size) == ("Blister", 24)
    assert (details.legal_status, details.distribution_site) == ("OTC", "Pharmacy")
    assert details.shelf_life == "48"  # the source states no unit, so none is added
    assert details.storage_ar == "يحفظ تحت 30"
    assert details.marketing_company_country == "Ireland"
    assert [(m.name, m.country) for m in details.manufacturers] == [("MAKER LTD", "Saudi Arabia")]
    assert details.price is not None
    assert (details.price.amount, details.price.currency_code) == (Decimal("7.25"), "SAR")
    assert details.price.currency_basis == "owner_assumption"
    assert (details.source_ref, details.fetched_at, details.trust) == (
        "https://www.sfda.gov.sa/en/x",
        FETCHED,
        "official",
    )


async def test_a_product_without_price_or_provenance_says_so() -> None:
    product = StoredProduct(
        id=ProductId(Market.SA, "1-1"),
        data=stored("1-1").data,
        listing_status=ListingStatus.LISTED,
    )
    details = await ReadProductCardsHandler(FakeReader(product)).get_details(Market.SA, "1-1")

    assert details is not None
    assert details.price is None
    assert (details.source_ref, details.fetched_at, details.trust) == (None, None, None)


async def test_an_unknown_register_number_has_no_details() -> None:
    handler = ReadProductCardsHandler(FakeReader(stored("1-1")))

    assert await handler.get_details(Market.SA, "9-9") is None


async def test_products_with_the_same_ingredient_set_exclude_the_product_itself() -> None:
    handler = ReadProductCardsHandler(
        FakeReader(
            stored("1-1", "PARACETAMOL"),
            stored("1-2", "PARACETAMOL"),
            stored("1-3", "PARACETAMOL", "CAFFEINE"),
        )
    )

    found = await handler.same_ingredients(Market.SA, "1-1", limit=10)

    assert [d.card.register_number for d in found] == ["1-2"]


async def test_same_ingredients_of_an_unknown_product_is_empty() -> None:
    handler = ReadProductCardsHandler(FakeReader())

    assert await handler.same_ingredients(Market.SA, "9-9", limit=10) == ()


class FakePriceChanges:
    def __init__(self, pair: PricePair | None) -> None:
        self.pair = pair

    async def last_change(self, market: Market, register_number: str) -> PricePair | None:
        return self.pair


async def test_a_recorded_price_change_is_part_of_the_details() -> None:
    pair = PricePair(
        Decimal("5"), "SAR", "owner_assumption", Decimal("6.5"), "SAR", "owner_assumption", FETCHED
    )
    handler = ReadProductCardsHandler(FakeReader(stored("1-1")), FakePriceChanges(pair))

    details = await handler.get_details(Market.SA, "1-1")

    assert details is not None
    assert details.price_change is not None
    assert (details.price_change.old.amount, details.price_change.new.amount) == (
        Decimal("5"),
        Decimal("6.5"),
    )
    assert details.price_change.changed_at == FETCHED


async def test_no_recorded_change_means_no_price_change_not_a_zero() -> None:
    handler = ReadProductCardsHandler(FakeReader(stored("1-1")), FakePriceChanges(None))

    details = await handler.get_details(Market.SA, "1-1")

    assert details is not None
    assert details.price_change is None


async def test_without_a_price_history_reader_the_details_still_work() -> None:
    details = await ReadProductCardsHandler(FakeReader(stored("1-1"))).get_details(Market.SA, "1-1")

    assert details is not None
    assert details.price_change is None
