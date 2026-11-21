"""Company views and the operator board: who may call them, and what they answer."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.domain.market import IngredientLine, MarketProduct
from pharmavique.analytics.domain.radar import (
    ChangeKind,
    MarketEvent,
    ProjectionStatus,
    RadarItem,
)
from pharmavique.analytics.infrastructure.refresh_files import FileRefreshHistory
from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CatalogQualityStats, ListQuality
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role

NOW = datetime.now(UTC)


def product(number: str, strength: str, company: str, form: str = "TABLET") -> MarketProduct:
    return MarketProduct(
        "SA", number, f"DRUG {number}", None, (IngredientLine("PARACETAMOL", strength, "MG"),),
        form, company, "listed", Decimal("10"), "SAR", "source_stated",
    )  # fmt: skip


ROWS = [
    product("1", "500", "A"),
    product("2", "500", "B"),
    product("3", "500", "C"),
    product("4", "1000", "A"),
    product("5", "120", "A", form="SYRUP"),
]


class Store:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def replace_products(
        self, market: str, products: Sequence[MarketProduct], built_at: datetime
    ) -> None: ...

    async def products_with_ingredient(
        self, market: str, ingredient: str, limit: int
    ) -> list[MarketProduct]:
        self.asked.append(ingredient)
        return [p for p in ROWS if ingredient in p.combination]

    async def add_event(self, event: MarketEvent) -> bool:
        return True

    async def radar(
        self, market: str, ingredient: str | None, since: datetime, limit: int
    ) -> list[RadarItem]:
        event = MarketEvent(
            UUID(int=1), "SA", ChangeKind.PRICE_CHANGED, "1", NOW - timedelta(days=1),
            "10", "12", "SAR", "source_stated",
        )  # fmt: skip
        return [RadarItem(event, "DRUG 1", None, "A", ("PARACETAMOL",))]

    async def first_built_at(self, market: str) -> datetime | None:
        return NOW

    async def status(self, market: str, now: datetime) -> ProjectionStatus:
        return ProjectionStatus(5, NOW, NOW, 1)


class Source:
    async def pages(self, market: Market, size: int) -> AsyncIterator[Sequence[MarketProduct]]:
        yield ROWS


class Quality:
    async def quality_stats(self, market: Market) -> CatalogQualityStats:
        return CatalogQualityStats(
            market=market, products=10, listed=9, withdrawn=1, listed_without_price=2,
            listed_without_ingredients=0, listed_with_missing_strength=3,
            listed_without_manufacturer=1, listed_with_real_picture=4,
            listed_with_generated_picture=3, listed_without_picture=2,
            lists=(ListQuality("drug-shortage", 20, 12, 3, 5, NOW),),
        )  # fmt: skip


TOKENS = JwtAccessTokens("k" * 40)


def headers(role: Role) -> dict[str, str]:
    token, _ = TOKENS.issue(Principal(uuid4(), uuid4(), frozenset({role})), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def refresh_dir(tmp_path: Path) -> Path:
    today = NOW.strftime("%Y%m%d")
    folder = tmp_path / today
    folder.mkdir()
    (folder / "summary.md").write_text(
        "| step | result | time |\n|---|---|---|\n| drugs-update | exit 3 | 2.0 min |\n",
        encoding="utf-8",
    )
    (folder / "drugs-load.log").write_text(
        "loaded 9 drugs in 1 batches: added=0\nskipped (no usable details)=1 rejected=2 x\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
async def client(refresh_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        analytics=AnalyticsService(Store(), Source(), SystemClock()),
        quality=Quality(),
        refresh_history=FileRefreshHistory(refresh_dir),
        token_verifier=TOKENS,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


COMPANY_PATHS = (
    "/v1/company/market?ingredient=paracetamol",
    "/v1/company/gaps?ingredient=paracetamol",
    "/v1/company/radar",
)


async def test_company_views_need_a_signed_in_caller(client: httpx.AsyncClient) -> None:
    for path in COMPANY_PATHS:
        assert (await client.get(path)).status_code == 401


async def test_patients_and_pharmacists_cannot_use_company_views(client: httpx.AsyncClient) -> None:
    for role in (Role.PATIENT, Role.PHARMACIST):
        for path in COMPANY_PATHS:
            assert (await client.get(path, headers=headers(role))).status_code == 403


async def test_the_market_map(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/company/market?ingredient=paracetamol", headers=headers(Role.COMPANY)
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["listed"], body["makers"]) == (5, 3)
    assert body["groups"][0]["price_ranges"][0]["currency_basis"] == "source_stated"
    assert "not sales" in body["note"]
    assert body["disclaimer"]


async def test_the_gaps_say_thin_not_demand(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/company/gaps?ingredient=paracetamol&thin_at=1", headers=headers(Role.COMPANY)
    )
    body = response.json()
    assert body["thin_at"] == 1
    thin = {c["strength"] for c in body["cells"] if c["thin"]}
    assert "PARACETAMOL 1000 MG" in thin
    assert any(m["dosage_form"] == "SYRUP" for m in body["missing"])
    assert "demand" in body["note"]


async def test_the_radar_lists_changes(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/company/radar?ingredient=paracetamol&days=7", headers=headers(Role.COMPANY)
    )
    item = response.json()["items"][0]
    assert (item["kind"], item["old_price"], item["new_price"]) == ("price_changed", "10", "12")


async def test_a_one_letter_ingredient_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/company/market?ingredient=a", headers=headers(Role.COMPANY))
    assert response.status_code == 422


async def test_the_operator_may_use_company_views_too(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/company/radar", headers=headers(Role.OPERATOR))
    assert response.status_code == 200


async def test_the_quality_board_is_for_operators_only(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/operator/quality")).status_code == 401
    for role in (Role.PATIENT, Role.PHARMACIST, Role.COMPANY):
        assert (await client.get("/v1/operator/quality", headers=headers(role))).status_code == 403


async def test_the_quality_board_reports_counts_the_refresh_and_the_read_model(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/operator/quality", headers=headers(Role.OPERATOR))
    body = response.json()
    assert response.status_code == 200
    assert body["catalog"]["listed_without_price"] == 2
    assert body["catalog"]["lists"][0]["linked_matched"] == 12
    refresh = body["refresh"]
    assert refresh["available"] is True
    assert refresh["overdue"] is False
    assert refresh["days"][0]["failed_steps"] == ["drugs-update"]
    assert refresh["days"][0]["load"]["rejected"] == 2
    assert body["analytics"]["products"] == 5


async def test_without_a_refresh_folder_the_board_says_unknown(tmp_path: Path) -> None:
    app = create_app(
        quality=Quality(),
        refresh_history=FileRefreshHistory(tmp_path / "absent"),
        token_verifier=TOKENS,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = (await c.get("/v1/operator/quality", headers=headers(Role.OPERATOR))).json()
    assert body["refresh"] == {
        "available": False, "last_day": None, "days_since_last": None, "overdue": None, "days": [],
    }  # fmt: skip
    assert body["analytics"] is None


async def test_company_views_say_503_when_the_read_model_is_not_configured() -> None:
    app = create_app(token_verifier=TOKENS)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.get("/v1/company/radar", headers=headers(Role.COMPANY))
    assert response.status_code == 503
