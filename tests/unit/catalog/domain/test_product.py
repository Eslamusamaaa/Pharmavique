from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pharmavique.catalog.domain.events import (
    PriceChanged,
    ProductAdded,
    ProductDetailsChanged,
    ProductRelisted,
    ProductWithdrawn,
)
from pharmavique.catalog.domain.product import ListingStatus, Product, ProductData
from pharmavique.catalog.domain.values import (
    LEGAL_STATUS,
    CodedValue,
    IngredientLine,
    LocalizedText,
    ProductId,
)
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
PID = ProductId(Market.SA, "1-111-22")
SAR = Currency.owner_assumed("SAR")


def prov(snapshot: str = "run-1", at: datetime = NOW) -> Provenance:
    return Provenance(
        "sfda-drugs-list-web", "https://example.test/p", at, snapshot, TrustLevel.OFFICIAL
    )


def price(amount: str) -> Money:
    return Money(Decimal(amount), SAR)


def data(**overrides: Any) -> ProductData:
    fields: dict[str, Any] = {
        "trade_name": LocalizedText("ACME-ONE 5MG TAB", "اكمي ون"),
        "ingredients": (IngredientLine("ACMEDRONE", Decimal("5"), "mg"),),
        "dosage_form": LocalizedText("Tablet", "اقراص"),
        "price": price("9.5"),
    }
    fields.update(overrides)
    return ProductData(**fields)


def registered(**overrides: Any) -> Product:
    product, _ = Product.register(PID, data(**overrides), prov(), NOW)
    return product


# ---- registering -------------------------------------------------------------------------------


def test_registering_a_product_emits_product_added_with_its_price() -> None:
    product, events = Product.register(PID, data(), prov(), NOW)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ProductAdded)
    assert event.product_id == PID
    assert event.price == price("9.5")
    assert event.occurred_at == NOW
    assert product.listing_status is ListingStatus.LISTED
    assert product.version == 1


def test_the_first_price_becomes_the_first_price_point() -> None:
    product = registered()

    assert [p.price for p in product.price_history] == [price("9.5")]
    assert product.price_history[0].effective_from == NOW


def test_a_product_without_a_price_has_no_price_history() -> None:
    assert registered(price=None).price_history == ()


# ---- applying a snapshot -----------------------------------------------------------------------


def test_applying_the_same_data_again_changes_nothing_and_emits_nothing() -> None:
    product = registered()
    history = product.price_history
    stored_data = product.data

    events = product.apply(data(), prov("run-2", LATER), LATER)

    assert events == []
    assert product.data == stored_data
    assert product.price_history == history
    assert product.listing_status is ListingStatus.LISTED
    assert product.version == 1
    assert product.provenance == prov()  # provenance of the data as it last changed
    assert product.last_seen_at == LATER  # but we did see it again


def test_a_new_price_emits_price_changed_and_appends_a_price_point() -> None:
    product = registered()

    events = product.apply(data(price=price("12")), prov("run-2", LATER), LATER)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, PriceChanged)
    assert (event.old_price, event.new_price) == (price("9.5"), price("12"))
    assert product.data.price == price("12")
    assert [p.price for p in product.price_history] == [price("9.5"), price("12")]
    assert product.price_history[-1].effective_from == LATER
    assert product.version == 2
    assert product.provenance == prov("run-2", LATER)


def test_the_current_price_always_equals_the_last_price_point() -> None:
    product = registered()
    product.apply(data(price=price("12")), prov(), LATER)
    product.apply(data(price=price("11")), prov(), LATER + timedelta(days=1))

    assert product.price_history[-1].price == product.data.price


def test_a_changed_detail_emits_details_changed_naming_the_fields() -> None:
    product = registered()

    events = product.apply(
        data(
            dosage_form=LocalizedText("Capsule", "كبسولات"), route=LocalizedText("Oral use", None)
        ),
        prov("run-2", LATER),
        LATER,
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ProductDetailsChanged)
    assert event.changed_fields == ("dosage_form", "route")
    assert product.price_history[-1].price == price("9.5")  # price untouched


def test_price_and_details_changing_together_emit_both_events_in_a_fixed_order() -> None:
    product = registered()

    events = product.apply(
        data(price=price("12"), legal_status=CodedValue.of("OTC", LEGAL_STATUS)),
        prov("run-2", LATER),
        LATER,
    )

    assert [type(e) for e in events] == [ProductDetailsChanged, PriceChanged]


def test_a_removed_price_is_reported_but_does_not_create_a_price_point() -> None:
    product = registered()

    events = product.apply(data(price=None), prov("run-2", LATER), LATER)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, PriceChanged)
    assert event.new_price is None
    assert product.data.price is None
    assert len(product.price_history) == 1


def test_events_carry_the_time_they_happened() -> None:
    product = registered()

    events = product.apply(data(price=price("12")), prov(), LATER)

    assert events[0].occurred_at == LATER


# ---- withdrawing and relisting -----------------------------------------------------------------


def test_withdrawing_marks_the_product_and_emits_product_withdrawn() -> None:
    product = registered()

    events = product.withdraw(prov("run-2", LATER), LATER)

    assert len(events) == 1
    assert isinstance(events[0], ProductWithdrawn)
    assert product.listing_status is ListingStatus.WITHDRAWN
    assert product.status_changed_at == LATER
    assert product.version == 2


def test_withdrawing_twice_emits_nothing_the_second_time() -> None:
    product = registered()
    product.withdraw(prov("run-2", LATER), LATER)

    assert product.withdraw(prov("run-3", LATER), LATER + timedelta(days=1)) == []
    assert product.version == 2


def test_applying_data_to_a_withdrawn_product_relists_it() -> None:
    product = registered()
    product.withdraw(prov("run-2", LATER), LATER)
    back = LATER + timedelta(days=2)

    events = product.apply(data(), prov("run-3", back), back)

    assert [type(e) for e in events] == [ProductRelisted]
    assert product.listing_status is ListingStatus.LISTED
    assert product.status_changed_at == back


def test_a_relisted_product_with_a_new_price_emits_relisted_then_price_changed() -> None:
    product = registered()
    product.withdraw(prov("run-2", LATER), LATER)

    events = product.apply(data(price=price("15")), prov("run-3", LATER), LATER)

    assert [type(e) for e in events] == [ProductRelisted, PriceChanged]


# ---- product data ------------------------------------------------------------------------------


def test_changed_fields_ignores_the_price_and_lists_names_in_declaration_order() -> None:
    old = data()
    new = data(price=price("99"), trade_name=LocalizedText("OTHER", None), agents=("AGENT",))

    assert old.changed_fields(new) == ("trade_name", "agents")


def test_product_data_needs_at_least_one_ingredient() -> None:
    import pytest

    from pharmavique.shared_kernel.errors import InvariantViolation

    with pytest.raises(InvariantViolation):
        data(ingredients=())
