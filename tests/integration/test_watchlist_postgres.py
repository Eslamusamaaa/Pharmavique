"""The watchlist tables against a real Postgres, as an ordinary role so row-level security applies.

The development database user is a superuser, and superusers skip row-level security. So these
tests create a limited role and connect as it, which is how the application must connect in
production. Isolation is checked at the database, not only in the repository's own queries.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.watchlist.domain.model import (
    Alert,
    AlertKind,
    Allergy,
    MedicineStatus,
    SavedMedicine,
)
from pharmavique.watchlist.infrastructure.postgres import PostgresWatchlistStore

pytestmark = pytest.mark.integration

ROLE = "pv_rls_test"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
async def limited(
    migrated_url: URL, engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    password = secrets.token_hex(16)
    async with engine.begin() as connection:
        if await _role_exists(connection):
            await connection.execute(text(f"DROP OWNED BY {ROLE}"))
        await connection.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))
        await connection.execute(
            text(f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'")
        )
        await connection.execute(text(f"GRANT USAGE ON SCHEMA watchlist TO {ROLE}"))
        await connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA watchlist TO {ROLE}"
            )
        )
        await connection.execute(
            text(
                "TRUNCATE watchlist.saved_medicines, watchlist.allergies, watchlist.alerts, "
                "watchlist.shelf_items"
            )
        )
    url = migrated_url.set(username=ROLE, password=password)
    limited_engine = create_engine(url.render_as_string(hide_password=False))
    yield create_session_factory(limited_engine)
    await limited_engine.dispose()


async def _role_exists(connection: AsyncConnection) -> bool:
    row = await connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": ROLE}
    )
    return row.first() is not None


def alert(user: UUID, register: str = "111", event: UUID | None = None) -> Alert:
    return Alert(
        id=uuid4(),
        user_id=user,
        kind=AlertKind.PRICE_CHANGED,
        register_number=register,
        event_id=event or uuid4(),
        occurred_at=NOW,
        details={"old_price": "5", "new_price": "6", "currency_code": "SAR", "currency_basis": "x"},
        created_at=NOW,
        read_at=None,
    )


async def test_each_person_sees_only_their_own_medicines_and_allergies(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b = uuid4(), uuid4()

    assert await store.add_medicine(a, SavedMedicine("111", NOW)) is True
    assert await store.add_medicine(a, SavedMedicine("111", NOW)) is False
    await store.add_medicine(b, SavedMedicine("222", NOW))
    await store.add_allergy(a, Allergy("AMOXICILLIN", "amoxicillin", NOW))

    assert [m.register_number for m in await store.medicines(a)] == ["111"]
    assert [m.register_number for m in await store.medicines(b)] == ["222"]
    assert [x.ingredient for x in await store.allergies(a)] == ["AMOXICILLIN"]
    assert await store.allergies(b) == []


async def test_the_database_hides_other_rows_even_from_a_query_with_no_filter(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b = uuid4(), uuid4()
    await store.add_medicine(a, SavedMedicine("111", NOW))
    await store.add_medicine(b, SavedMedicine("222", NOW))

    async with limited() as session, session.begin():
        await session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
        mine = (
            await session.execute(text("SELECT register_number FROM watchlist.saved_medicines"))
        ).all()
    async with limited() as session, session.begin():
        nobody = (
            await session.execute(text("SELECT register_number FROM watchlist.saved_medicines"))
        ).all()

    assert [r.register_number for r in mine] == [
        "111"
    ]  # a forgotten WHERE still returns only a's row
    assert nobody == []  # no identity set: fails closed


async def test_the_database_refuses_to_write_a_row_for_someone_else(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    a, b = uuid4(), uuid4()

    async def write_for_someone_else() -> None:
        async with limited() as session, session.begin():
            await session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
            await session.execute(
                text(
                    "INSERT INTO watchlist.saved_medicines (user_id, register_number, added_at) "
                    "VALUES (:u, '999', now())"
                ),
                {"u": b},
            )

    with pytest.raises(DBAPIError):
        await write_for_someone_else()


async def test_holders_are_found_across_people_for_event_handlers_only(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b, c = uuid4(), uuid4(), uuid4()
    for user, register in ((a, "111"), (b, "111"), (c, "222")):
        await store.add_medicine(user, SavedMedicine(register, NOW))

    assert sorted(await store.holders_of("111")) == sorted([a, b])


async def test_a_medicine_can_be_marked_past_and_only_current_ones_have_holders(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    me, other = uuid4(), uuid4()
    await store.add_medicine(me, SavedMedicine("111", NOW))
    await store.add_medicine(other, SavedMedicine("111", NOW))

    later = NOW + timedelta(days=1)
    assert await store.set_medicine_status(me, "111", MedicineStatus.PAST, later) is True
    assert await store.set_medicine_status(me, "999", MedicineStatus.PAST, later) is False

    (mine,) = await store.medicines(me)
    assert (mine.status, mine.status_changed_at) == (MedicineStatus.PAST, later)
    assert (await store.medicines(other))[0].status is MedicineStatus.CURRENT  # not touched
    assert await store.holders_of("111") == [other]  # a past medicine raises no alert


async def test_saving_a_past_medicine_again_makes_it_current_and_saving_a_current_one_does_not(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    me = uuid4()
    await store.add_medicine(me, SavedMedicine("111", NOW))
    assert await store.add_medicine(me, SavedMedicine("111", NOW)) is False  # already current
    await store.set_medicine_status(me, "111", MedicineStatus.PAST, NOW)

    assert await store.add_medicine(me, SavedMedicine("111", NOW + timedelta(days=2))) is True
    (saved,) = await store.medicines(me)
    assert saved.status is MedicineStatus.CURRENT


async def test_a_shelf_list_is_private_counted_in_alert_holders_and_forgotten_with_the_person(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b = uuid4(), uuid4()

    assert await store.add_shelf_items(a, ["111", "222"], NOW) == 2
    assert await store.add_shelf_items(a, ["222", "333"], NOW) == 1  # 222 was already there
    assert await store.add_shelf_items(b, ["999"], NOW) == 1

    assert sorted(i.register_number for i in await store.shelf(a)) == ["111", "222", "333"]
    assert [i.register_number for i in await store.shelf(b)] == ["999"]  # not a's

    # a pharmacist who shelves a medicine is told when it changes, like someone who takes it
    assert await store.holders_of("111") == [a]
    await store.add_medicine(b, SavedMedicine("111", NOW))
    assert sorted(await store.holders_of("111")) == sorted([a, b])

    assert await store.remove_shelf_item(a, "111") is True
    assert await store.holders_of("111") == [b]

    await store.forget(a)
    assert await store.shelf(a) == []
    assert [i.register_number for i in await store.shelf(b)] == ["999"]


async def test_the_database_refuses_to_read_or_write_another_persons_shelf_row(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b = uuid4(), uuid4()
    await store.add_shelf_items(a, ["111"], NOW)
    async with limited() as session, session.begin():
        await session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(b)})
        rows = (await session.execute(text("SELECT * FROM watchlist.shelf_items"))).all()
    assert rows == []  # a forgotten WHERE still shows b nothing of a's


async def test_alerts_waiting_for_the_email_digest_are_found_and_marked_once_handled(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    a, b = uuid4(), uuid4()
    await store.add_alert(alert(a))
    await store.add_alert(alert(b))
    (read_one,) = await store.alerts(b, unread_only=False, limit=5)
    await store.mark_read(b, read_one.id)  # b already read theirs in the app

    waiting = await store.pending_email_alerts(10)
    assert [x.user_id for x in waiting] == [a]  # a read alert is not emailed

    await store.mark_emailed([x.id for x in waiting], NOW)
    assert await store.pending_email_alerts(10) == []
    assert len(await store.alerts(a, unread_only=False, limit=5)) == 1  # the inbox keeps it


async def test_an_alert_is_stored_once_per_event_and_can_be_read(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    me, other = uuid4(), uuid4()
    event = uuid4()

    assert await store.add_alert(alert(me, event=event)) is True
    assert await store.add_alert(alert(me, event=event)) is False  # re-delivered
    assert await store.add_alert(alert(other, event=event)) is True  # another person, same event

    assert await store.unread_count(me) == 1
    mine = await store.alerts(me, unread_only=True, limit=10)
    assert len(mine) == 1
    assert mine[0].details["new_price"] == "6"
    assert await store.mark_read(me, mine[0].id) == 1
    assert await store.unread_count(me) == 0
    assert await store.unread_count(other) == 1  # reading mine did not touch theirs


async def test_forgetting_a_person_deletes_their_rows_and_only_theirs(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresWatchlistStore(limited)
    me, other = uuid4(), uuid4()
    for user in (me, other):
        await store.add_medicine(user, SavedMedicine("111", NOW))
        await store.add_allergy(user, Allergy("X", "x", NOW))
        await store.add_alert(alert(user))

    await store.forget(me)

    assert await store.medicines(me) == []
    assert await store.allergies(me) == []
    assert await store.alerts(me, False, 10) == []
    assert len(await store.medicines(other)) == 1


async def test_the_watchlist_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "watchlist@base")
    await asyncio.to_thread(command.upgrade, config, "watchlist@head")
