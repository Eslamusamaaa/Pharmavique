"""The medicine history as memory: a new drug against what the person takes now."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.interactions.contracts.queries import (
    Finding,
    InteractionReport,
    ProductIngredients,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.domain.model import Alert, Allergy, MedicineStatus, SavedMedicine


class Store:
    def __init__(self) -> None:
        self.meds: dict[UUID, dict[str, SavedMedicine]] = {}
        self.alg: dict[UUID, dict[str, Allergy]] = {}

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
        found = self.meds.get(user_id, {}).get(register_number)
        if found is None:
            return False
        self.meds[user_id][register_number] = SavedMedicine(
            register_number, found.added_at, status, at
        )
        return True

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        return self.meds.get(user_id, {}).pop(register_number, None) is not None

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        return list(self.meds.get(user_id, {}).values())

    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        self.alg.setdefault(user_id, {})[allergy.key] = allergy
        return True

    async def remove_allergy(self, user_id: UUID, key: str) -> bool:
        return self.alg.get(user_id, {}).pop(key, None) is not None

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        return list(self.alg.get(user_id, {}).values())

    async def holders_of(self, register_number: str) -> list[UUID]:
        return []

    async def add_alert(self, alert: Alert) -> bool:
        return True

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]:
        return []

    async def unread_count(self, user_id: UUID) -> int:
        return 0

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        return 0

    async def forget(self, user_id: UUID) -> None:
        self.meds.pop(user_id, None)


def card(number: str, name: str, *ingredients: str) -> ProductCard:
    return ProductCard(
        market=Market.SA, register_number=number, trade_name_en=name, trade_name_ar=None,
        ingredient_names=ingredients, dosage_form_en="Tablet", dosage_form_ar=None,
        marketing_company="ACME", manufacturers=(), atc_codes=(), listing_status="listed",
        authorization_status=None, marketing_status=None,
    )  # fmt: skip


CARDS = {
    "1": card("1", "WARFARIN 5", "WARFARIN"),
    "2": card("2", "ASPIRIN 100", "ASPIRIN"),
    "3": card("3", "METFORMIN 500", "METFORMIN"),
    "4": card("4", "AMOXIL", "AMOXICILLIN TRIHYDRATE"),
    "5": card("5", "ASPIRIN EXTRA", "ASPIRIN", "CAFFEINE"),
}
# the source records these pairs, whatever order the products come in
PAIRS = {frozenset({"WARFARIN", "ASPIRIN"}): ("major", "ddinter")}


class Catalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(CARDS[n] for n in register_numbers if n in CARDS)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


class Interactions:
    async def run(self, products: Sequence[ProductIngredients]) -> InteractionReport:
        findings: list[Finding] = []
        for i, a in enumerate(products):
            for b in products[i + 1 :]:
                registers = (a.register_number, b.register_number)
                for x in a.ingredients:
                    for y in b.ingredients:
                        if x == y:
                            findings.append(
                                Finding("duplicate_ingredient", None, registers, (x, y), None)
                            )
                        rated = PAIRS.get(frozenset({x, y}))
                        if rated:
                            findings.append(
                                Finding("interaction", rated[0], registers, (x, y), rated[1])
                            )
        unmatched = tuple(
            (p.register_number, i) for p in products for i in p.ingredients if i == "CAFFEINE"
        )
        return InteractionReport(tuple(findings), unmatched, complete=False)


class Ingredients:
    names = ("AMOXICILLIN", "AMOXICILLIN TRIHYDRATE", "ASPIRIN", "WARFARIN")

    async def find_ingredients(self, market: Market, prefix: str, limit: int) -> tuple[str, ...]:
        return tuple(n for n in self.names if n.startswith(prefix.upper()))[:limit]

    async def is_ingredient(self, market: Market, name: str) -> bool:
        return name.upper() in self.names


TOKENS = JwtAccessTokens("k" * 40)


def headers(user: UUID) -> dict[str, str]:
    token, _ = TOKENS.issue(Principal(user, None, frozenset({Role.PATIENT})), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        catalog=Catalog(),
        watchlist=WatchlistService(Store(), SystemClock()),
        ingredients=Ingredients(),
        interactions=Interactions(),
        token_verifier=TOKENS,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def save(client: httpx.AsyncClient, me: dict[str, str], *numbers: str) -> None:
    for number in numbers:
        assert (await client.put(f"/v1/me/medicines/{number}", headers=me)).status_code == 204


async def test_the_history_check_needs_a_signed_in_caller(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/me/history/check/2")).status_code == 401
    assert (await client.get("/v1/me/history/interactions")).status_code == 401


async def test_a_new_drug_is_compared_with_what_i_take_now(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())
    await save(client, me, "1", "3")  # warfarin and metformin

    body = (await client.get("/v1/me/history/check/2", headers=me)).json()  # aspirin

    assert [m["register_number"] for m in body["compared_with"]] == ["1", "3"]
    (finding,) = body["findings"]
    assert finding["kind"] == "interaction"
    assert finding["severity"] == "major"
    assert finding["with_name"] == "WARFARIN 5"
    assert finding["ingredients"] == ["ASPIRIN", "WARFARIN"]  # this drug's ingredient first
    assert finding["source"] == "ddinter"
    assert body["complete"] is False
    assert "safe" in body["note_en"]
    assert "no" in body["note_en"].lower()


async def test_it_says_nothing_found_is_not_safe_even_with_no_findings(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "3")
    body = (await client.get("/v1/me/history/check/4", headers=me)).json()
    assert body["findings"] == []
    assert body["complete"] is False
    assert "does not mean" in body["note_en"]


async def test_a_medicine_i_stopped_is_not_compared(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())
    await save(client, me, "1")
    assert (
        await client.put("/v1/me/medicines/1/status", json={"status": "past"}, headers=me)
    ).status_code == 204

    body = (await client.get("/v1/me/history/check/2", headers=me)).json()

    assert body["compared_with"] == []
    assert body["findings"] == []


async def test_it_does_not_compare_a_drug_with_itself_and_says_i_already_take_it(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "2", "3")
    body = (await client.get("/v1/me/history/check/2", headers=me)).json()
    assert body["already_taken"] is True
    assert [m["register_number"] for m in body["compared_with"]] == ["3"]
    assert body["findings"] == []


async def test_an_interaction_between_two_other_medicines_is_not_reported_for_the_new_drug(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "1", "2")  # warfarin and aspirin interact with each other
    body = (await client.get("/v1/me/history/check/4", headers=me)).json()  # amoxicillin
    assert body["findings"] == []


async def test_the_same_ingredient_in_two_medicines_is_reported_as_a_duplicate(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "2")
    body = (await client.get("/v1/me/history/check/5", headers=me)).json()  # aspirin extra
    kinds = {f["kind"] for f in body["findings"]}
    assert "duplicate_ingredient" in kinds
    assert body["unmatched_ingredients"] == ["CAFFEINE"]


async def test_my_recorded_allergy_shows_up_in_the_check(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())
    await client.put("/v1/me/allergies", json={"ingredient": "amoxicillin"}, headers=me)
    body = (await client.get("/v1/me/history/check/4", headers=me)).json()
    assert body["allergy_matches"] == [
        {"allergy": "AMOXICILLIN", "ingredient": "AMOXICILLIN TRIHYDRATE"}
    ]


async def test_an_unknown_drug_is_404(client: httpx.AsyncClient) -> None:
    assert (
        await client.get("/v1/me/history/check/999", headers=headers(uuid4()))
    ).status_code == 404


async def test_one_persons_history_never_shows_in_anothers_check(
    client: httpx.AsyncClient,
) -> None:
    a, b = headers(uuid4()), headers(uuid4())
    await save(client, a, "1")
    body = (await client.get("/v1/me/history/check/2", headers=b)).json()
    assert body["compared_with"] == []
    assert body["findings"] == []


async def test_recorded_interactions_among_the_medicines_i_take_now(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "1", "2", "3")
    body = (await client.get("/v1/me/history/interactions", headers=me)).json()
    assert [m["register_number"] for m in body["medicines"]] == ["1", "2", "3"]
    (finding,) = body["findings"]
    assert {finding["about_register_number"], finding["with_register_number"]} == {"1", "2"}
    assert body["complete"] is False


async def test_with_fewer_than_two_current_medicines_there_is_nothing_to_compare(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "1")
    body = (await client.get("/v1/me/history/interactions", headers=me)).json()
    assert body["findings"] == []


async def test_the_list_shows_each_medicines_status_and_a_past_one_can_come_back(
    client: httpx.AsyncClient,
) -> None:
    me = headers(uuid4())
    await save(client, me, "1")
    await client.put("/v1/me/medicines/1/status", json={"status": "past"}, headers=me)
    item = (await client.get("/v1/me/medicines", headers=me)).json()["items"][0]
    assert item["status"] == "past"
    assert item["status_changed_at"] is not None

    await client.put("/v1/me/medicines/1", headers=me)  # saving again makes it current
    item = (await client.get("/v1/me/medicines", headers=me)).json()["items"][0]
    assert item["status"] == "current"


async def test_the_status_of_a_medicine_i_never_saved_is_404(client: httpx.AsyncClient) -> None:
    response = await client.put(
        "/v1/me/medicines/1/status", json={"status": "past"}, headers=headers(uuid4())
    )
    assert response.status_code == 404


async def test_a_status_other_than_current_or_past_is_refused(client: httpx.AsyncClient) -> None:
    me = headers(uuid4())
    await save(client, me, "1")
    response = await client.put("/v1/me/medicines/1/status", json={"status": "stop"}, headers=me)
    assert response.status_code == 422


class Runner:
    """Records everything the language model side is given."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None, int]] = []

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
        guidance: str = "",
    ) -> AgentRun:
        self.seen.append((question, register_number, len(history)))
        return AgentRun("المادة الفعالة هي الأسبرين.", (), ())


@pytest.fixture
async def assistant_client() -> AsyncIterator[tuple[httpx.AsyncClient, Runner]]:
    runner = Runner()
    app = create_app(
        catalog=Catalog(),
        watchlist=WatchlistService(Store(), SystemClock()),
        interactions=Interactions(),
        assistant=AskAssistant(runner),
        token_verifier=TOKENS,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, runner


async def test_the_assistant_can_attach_the_check_against_my_medicines(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, runner = assistant_client
    me = headers(uuid4())
    await save(client, me, "1")

    response = await client.post(
        "/v1/assistant/ask",
        json={"question": "ايه ده؟", "register_number": "2", "use_history": True},
        headers=me,
    )

    body = response.json()
    assert response.status_code == 200
    assert body["history_check"]["findings"][0]["severity"] == "major"
    assert body["history_check"]["complete"] is False
    # the model side got the question and the drug, never the person's medicines
    assert runner.seen == [("ايه ده؟", "2", 0)]
    assert "WARFARIN" not in str(runner.seen)


async def test_without_asking_the_assistant_attaches_nothing(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, _ = assistant_client
    me = headers(uuid4())
    await save(client, me, "1")
    response = await client.post(
        "/v1/assistant/ask", json={"question": "x", "register_number": "2"}, headers=me
    )
    assert response.json()["history_check"] is None


async def test_asking_to_use_my_medicines_without_signing_in_is_refused(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, runner = assistant_client
    response = await client.post(
        "/v1/assistant/ask", json={"question": "x", "register_number": "2", "use_history": True}
    )
    assert response.status_code == 401
    assert runner.seen == []


async def test_using_my_medicines_needs_a_named_drug(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, _ = assistant_client
    response = await client.post(
        "/v1/assistant/ask",
        json={"question": "x", "use_history": True},
        headers=headers(uuid4()),
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("ai_open_to_guests")
async def test_an_anonymous_question_still_works_without_any_account_setup(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, _ = assistant_client
    response = await client.post("/v1/assistant/ask", json={"question": "x"})
    assert response.status_code == 200


async def test_a_bad_token_is_a_401_not_an_anonymous_question(
    assistant_client: tuple[httpx.AsyncClient, Runner],
) -> None:
    client, _ = assistant_client
    response = await client.post(
        "/v1/assistant/ask", json={"question": "x"}, headers={"Authorization": "Bearer nonsense"}
    )
    assert response.status_code == 401
