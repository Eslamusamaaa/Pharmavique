"""Translation between the published language and the domain (both directions).

The catalog's contracts speak in plain values; the domain speaks in validated value objects.
Anything the domain refuses surfaces as `InvariantViolation`, which the handlers report as a
rejected snapshot instead of failing the whole batch.
"""

from collections.abc import Mapping, Sequence

from pharmavique.catalog.contracts import events as published
from pharmavique.catalog.contracts.commands import PartyDto, ProductSnapshot
from pharmavique.catalog.domain import events as domain
from pharmavique.catalog.domain.product import ProductData
from pharmavique.catalog.domain.values import (
    AUTHORIZATION_STATUS,
    DISTRIBUTION_SITE,
    LEGAL_STATUS,
    MARKETING_STATUS,
    PRODUCT_CONTROL,
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
)
from pharmavique.shared_kernel.events import DomainEvent, IntegrationEvent


def _text(en: str | None, ar: str | None) -> LocalizedText | None:
    if not (en and en.strip()) and not (ar and ar.strip()):
        return None
    return LocalizedText(en, ar)


def _coded(raw: str | None, vocabulary: Mapping[str, str]) -> CodedValue | None:
    if raw is None or not raw.strip():
        return None
    return CodedValue.of(raw, vocabulary)


def _party(dto: PartyDto | None) -> Party | None:
    return Party(dto.name, dto.country) if dto is not None else None


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def snapshot_to_data(snapshot: ProductSnapshot) -> ProductData:
    """Build the domain's product data. Manufacturers and agents are sorted so that the source
    listing the same parties in a different order is not reported as a change."""
    manufacturers = sorted(
        (Party(m.name, m.country) for m in snapshot.manufacturers),
        key=lambda p: (p.name, p.country or ""),
    )
    agents = sorted({a.strip() for a in snapshot.agents if a.strip()})
    return ProductData(
        trade_name=LocalizedText(snapshot.trade_name_en, snapshot.trade_name_ar),
        ingredients=tuple(IngredientLine(i.name, i.strength, i.unit) for i in snapshot.ingredients),
        dosage_form=LocalizedText(snapshot.dosage_form_en, snapshot.dosage_form_ar),
        route=_text(snapshot.route_en, snapshot.route_ar),
        package=Package(
            snapshot.package_size,
            snapshot.package_size_unit,
            snapshot.package_type,
            snapshot.package_count,
        ),
        legal_status=_coded(snapshot.legal_status, LEGAL_STATUS),
        product_control=_coded(snapshot.product_control, PRODUCT_CONTROL),
        distribution_site=_coded(snapshot.distribution_site, DISTRIBUTION_SITE),
        authorization_status=_coded(snapshot.authorization_status, AUTHORIZATION_STATUS),
        marketing_status=_coded(snapshot.marketing_status, MARKETING_STATUS),
        atc_codes=tuple(AtcCode(code) for code in snapshot.atc_codes),
        shelf_life=_clean(snapshot.shelf_life),
        storage_conditions=_text(snapshot.storage_conditions_en, snapshot.storage_conditions_ar),
        manufacturers=tuple(manufacturers),
        marketing_company=_party(snapshot.marketing_company),
        agents=tuple(agents),
        description_code=_clean(snapshot.description_code),
        price=snapshot.price,
    )


def to_integration_events(events: Sequence[DomainEvent]) -> list[IntegrationEvent]:
    """Domain events to published events. The published event reuses the domain event's id, so
    one fact has one id on both sides."""
    out: list[IntegrationEvent] = []
    for event in events:
        if isinstance(event, domain.ProductAdded):
            out.append(
                published.ProductAdded(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    market=event.product_id.market,
                    register_number=event.product_id.register_number,
                    price=event.price,
                )
            )
        elif isinstance(event, domain.ProductRelisted):
            out.append(
                published.ProductRelisted(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    market=event.product_id.market,
                    register_number=event.product_id.register_number,
                )
            )
        elif isinstance(event, domain.ProductWithdrawn):
            out.append(
                published.ProductWithdrawn(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    market=event.product_id.market,
                    register_number=event.product_id.register_number,
                )
            )
        elif isinstance(event, domain.PriceChanged):
            out.append(
                published.PriceChanged(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    market=event.product_id.market,
                    register_number=event.product_id.register_number,
                    old_price=event.old_price,
                    new_price=event.new_price,
                )
            )
        elif isinstance(event, domain.ProductDetailsChanged):
            out.append(
                published.ProductDetailsChanged(
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    market=event.product_id.market,
                    register_number=event.product_id.register_number,
                    changed_fields=event.changed_fields,
                )
            )
    return out
