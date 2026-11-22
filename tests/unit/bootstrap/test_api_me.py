"""Saved medicines, allergies, alerts and the digest: one person's data, behind a token."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.domain.model import Alert, Allergy, MedicineStatus, SavedMedicine


class Store:
    def __init__(self) -> None:
        self.meds: dict[UUID, dict[str, SavedMedicine]] = {}
        self.alg: dict[UUID, dict[str, Allergy]] = {}
        self.alert_rows: list[Alert] = []

    async def add_medicine(self, user_id: UUID, medicine: SavedMedicine) -> bool:
        mine = self.meds.setdefault(user_id, {})
        existing = mine.get(medicine.register_number)
        if existing is not None and existing.status is MedicineStatus.CURRENT:
            return False
        mine[medicine.register_number] = medicine
        return True

    async def set_medicine_status(
        self, user_id: UUID, register_number: str, status: MedicineStatus, at: datetime
    ) -> bool:
        mine = self.meds.get(user_id, {})
        found = mine.get(register_number)
        if found is None:
            return False
        mine[register_number] = SavedMedicine(register_number, found.added_at, status, at)
        return True

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        return self.meds.get(user_id, {}).pop(register_number, None) is not None

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        return list(self.meds.get(user_id, {}).values())

    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        mine = self.alg.setdefault(user_id, {})
        if allergy.key in mine:
            return False
        mine[allergy.key] = allergy
        return True

    async def remove_allergy(self, user_id: UUID, key: str) -> bool:
        return self.alg.get(user_id, {}).pop(key, None) is not None

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        return list(self.alg.get(user_id, {}).values())

    async def holders_of(self, register_number: str) -> list[UUID]:
        return [
            u
            for u, m in self.meds.items()
            if register_number in m and m[register_number].status is MedicineStatus.CURRENT
        ]

    async def add_alert(self, alert: Alert) -> bool:
        if any(
            a.user_id == alert.user_id and a.event_id == alert.event_id for a in self.alert_rows
        ):
            return False
        self.alert_rows.append(alert)
        return True

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]:
        rows = [a for a in self.alert_rows if a.user_id == user_id]
        return [a for a in rows if not unread_only or a.read_at is None][:limit]

    async def unread_count(self, user_id: UUID) -> int:
        return len([a for a in self.alert_rows if a.user_id == user_id and a.read_at is None])

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        count = 0
        for index, a in enumerate(self.alert_rows):
            if a.user_id == user_id and a.read_at is None and alert_id in (None, a.id):
                self.alert_rows[index] = Alert(
                    a.id, a.user_id, a.kind, a.register_number, a.event_id, a.occurred_at,
                    a.details, a.created_at, datetime.now(UTC),
                )  # fmt: skip
                count += 1
        return count

    async def forget(self, user_id: UUID) -> None:
        self.meds.pop(user_id, None)
        self.alg.pop(user_id, None)
        self.alert_rows = [a for a in self.alert_rows if a.user_id != user_id]


def card(number: str, *ingredients: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG {number}",
        trade_name_ar=None,
        ingredient_names=ingredients,
        dosage_form_en="Tablet",
        dosage_form_ar=None,
        marketing_company="ACME",
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


CARDS = {
    "1": card("1", "PARACETAMOL"),
    "2": card("2", "AMOXICILLIN TRIHYDRATE", "CLAVULANIC ACID"),
}


class Catalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(CARDS[n] for n in register_numbers if n in CARDS)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


class Ingredients:
    names = ("AMOXICILLIN", "AMOXICILLIN TRIHYDRATE", "PARACETAMOL")

    async def find_ingredients(self, market: Market, prefix: str, limit: int) -> tuple[str, ...]:
        return tuple(n for n in self.names if n.startswith(prefix.upper()))[:limit]

    async def is_ingredient(self, market: Market, name: str) -> bool:
        return name.upper() in self.names


TOKENS = JwtAccessTokens("k" * 40)


def headers(user: UUID) -> dict[str, str]:
    token, _ = TOKENS.issue(Principal(user, None, frozenset({Role.PATIENT})), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
async def client(store: Store) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        catalog=Catalog(),
        watchlist=WatchlistService(store, SystemClock()),
        ingredients=Ingredients(),
        token_verifier=TOKENS,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_everything_here_needs_a_signed_in_caller(client: httpx.AsyncClient) -> None:
    for path in ("/v1/me/medicines", "/v1/me/allergies", "/v1/me/alerts", "/v1/me/digest"):
        assert (await client.get(path)).status_code == 401


async def test_a_medicine_is_saved_listed_and_removed(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())

    assert (await client.put("/v1/me/medicines/1", headers=me)).status_code == 204
    body = (await client.get("/v1/me/medicines", headers=me)).json()
    assert body["count"] == 1
    assert body["items"][0]["product"]["trade_name_en"] == "DRUG 1"
    assert (await client.delete("/v1/me/medicines/1", headers=me)).status_code == 204
    assert (await client.get("/v1/me/medicines", headers=me)).json()["count"] == 0


async def test_an_unknown_drug_cannot_be_saved(client: httpx.AsyncClient) -> None:
    assert (await client.put("/v1/me/medicines/999", headers=headers(uuid4()))).status_code == 404


async def test_one_person_never_sees_another_persons_list(client: httpx.AsyncClient) -> None:
    a, b = headers(uuid4()), headers(uuid4())
    await client.put("/v1/me/medicines/1", headers=a)

    assert (await client.get("/v1/me/medicines", headers=b)).json()["count"] == 0


async def test_an_allergy_must_be_an_ingredient_from_the_catalog(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())

    bad = await client.put("/v1/me/allergies", json={"ingredient": "moonbeam"}, headers=me)
    good = await client.put("/v1/me/allergies", json={"ingredient": "amoxicillin"}, headers=me)

    assert bad.status_code == 422
    assert good.status_code == 204
    assert (await client.get("/v1/me/allergies", headers=me)).json()["items"] == [
        {"ingredient": "AMOXICILLIN"}
    ]


async def test_the_ingredient_picker_is_public_and_matches_the_start_of_a_name(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/ingredients", params={"q": "amox"})).json()

    assert body["items"] == ["AMOXICILLIN", "AMOXICILLIN TRIHYDRATE"]


async def test_the_allergy_check_matches_by_name_and_never_claims_safety(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await client.put("/v1/me/allergies", json={"ingredient": "AMOXICILLIN"}, headers=me)

    hit = (await client.get("/v1/me/allergy-check/2", headers=me)).json()
    miss = (await client.get("/v1/me/allergy-check/1", headers=me)).json()

    assert hit["matches"] == [{"allergy": "AMOXICILLIN", "ingredient": "AMOXICILLIN TRIHYDRATE"}]
    assert miss["matches"] == []
    assert "no match is not a clearance" in miss["note"]
    assert "ask your pharmacist" in miss["note"].lower()


async def test_saved_medicines_carry_their_allergy_matches(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())
    await client.put("/v1/me/allergies", json={"ingredient": "AMOXICILLIN"}, headers=me)
    await client.put("/v1/me/medicines/2", headers=me)

    item = (await client.get("/v1/me/medicines", headers=me)).json()["items"][0]

    assert item["allergy_matches"][0]["allergy"] == "AMOXICILLIN"


async def test_an_event_becomes_an_alert_that_can_be_read(
    client: httpx.AsyncClient, store: Store
) -> None:
    user = uuid4()
    me = headers(user)
    await client.put("/v1/me/medicines/1", headers=me)
    service = WatchlistService(store, SystemClock())
    await service.on_event(
        StoredEvent(
            uuid4(),
            "catalog.PriceChanged",
            1,
            datetime.now(UTC),
            {
                "market": "SA",
                "register_number": "1",
                "old_price": {"amount": "5", "currency_code": "SAR", "currency_basis": "x"},
                "new_price": {"amount": "6", "currency_code": "SAR", "currency_basis": "x"},
            },
        )
    )

    body = (await client.get("/v1/me/alerts", headers=me)).json()
    assert body["unread"] == 1
    assert body["items"][0]["kind"] == "price_changed"
    assert body["items"][0]["product"]["trade_name_en"] == "DRUG 1"
    assert body["items"][0]["details"]["new_price"] == "6"

    marked = await client.post("/v1/me/alerts/read", json={}, headers=me)
    assert marked.json() == {"marked": 1}
    assert (await client.get("/v1/me/alerts", headers=me)).json()["unread"] == 0

    digest = (await client.get("/v1/me/digest", headers=me)).json()
    assert digest["counts"]["price_changed"] == 1
    assert "1 تغيير سعر" in digest["summary"]


async def test_an_empty_digest_says_nothing_changed(client: httpx.AsyncClient) -> None:
    digest = (await client.get("/v1/me/digest", headers=headers(uuid4()))).json()

    assert digest["items"] == []
    assert "ما فيه تغييرات" in digest["summary"]


async def test_without_the_database_these_endpoints_say_so() -> None:
    app = create_app(token_verifier=TOKENS)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/me/medicines", headers=headers(uuid4()))).status_code == 503
