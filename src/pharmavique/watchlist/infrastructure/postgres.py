"""PostgreSQL store over the `watchlist` schema, under row-level security.

Every call runs in one transaction that first tells the database who is asking
(`app.user_id`), so the policies in the migration limit it to that person's rows even if a query
here forgot its own `WHERE user_id`. Event handlers that must see every holder of a medicine set
`app.system` instead; nothing reachable from an API request does.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.watchlist.domain.model import Alert, AlertKind, Allergy, SavedMedicine

_SET_USER = text("SELECT set_config('app.user_id', :user_id, true)")
_SET_SYSTEM = text("SELECT set_config('app.system', 'on', true)")


class PostgresWatchlistStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _as_user(self, user_id: UUID) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            await session.execute(_SET_USER, {"user_id": str(user_id)})
            yield session

    @asynccontextmanager
    async def _as_system(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            await session.execute(_SET_SYSTEM)
            yield session

    # ---- saved medicines ---------------------------------------------------------------
    async def add_medicine(self, user_id: UUID, medicine: SavedMedicine) -> bool:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "INSERT INTO watchlist.saved_medicines (user_id, register_number, added_at) "
                    "VALUES (:u, :r, :t) ON CONFLICT DO NOTHING RETURNING register_number"
                ),
                {"u": user_id, "r": medicine.register_number, "t": medicine.added_at},
            )
            return result.first() is not None

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM watchlist.saved_medicines "
                    "WHERE user_id = :u AND register_number = :r RETURNING register_number"
                ),
                {"u": user_id, "r": register_number},
            )
            return result.first() is not None

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        async with self._as_user(user_id) as session:
            rows = await session.execute(
                text(
                    "SELECT register_number, added_at FROM watchlist.saved_medicines "
                    "WHERE user_id = :u ORDER BY added_at DESC, register_number"
                ),
                {"u": user_id},
            )
            return [SavedMedicine(r.register_number, r.added_at) for r in rows]

    # ---- allergies ---------------------------------------------------------------------
    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "INSERT INTO watchlist.allergies (user_id, key, ingredient, added_at) "
                    "VALUES (:u, :k, :i, :t) ON CONFLICT DO NOTHING RETURNING key"
                ),
                {"u": user_id, "k": allergy.key, "i": allergy.ingredient, "t": allergy.added_at},
            )
            return result.first() is not None

    async def remove_allergy(self, user_id: UUID, key: str) -> bool:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM watchlist.allergies WHERE user_id = :u AND key = :k RETURNING key"
                ),
                {"u": user_id, "k": key},
            )
            return result.first() is not None

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        async with self._as_user(user_id) as session:
            rows = await session.execute(
                text(
                    "SELECT ingredient, key, added_at FROM watchlist.allergies "
                    "WHERE user_id = :u ORDER BY added_at, key"
                ),
                {"u": user_id},
            )
            return [Allergy(r.ingredient, r.key, r.added_at) for r in rows]

    # ---- alerts ------------------------------------------------------------------------
    async def holders_of(self, register_number: str) -> list[UUID]:
        async with self._as_system() as session:
            rows = await session.execute(
                text("SELECT user_id FROM watchlist.saved_medicines WHERE register_number = :r"),
                {"r": register_number},
            )
            return [r.user_id for r in rows]

    async def add_alert(self, alert: Alert) -> bool:
        async with self._as_user(alert.user_id) as session:
            result = await session.execute(
                text(
                    "INSERT INTO watchlist.alerts (id, user_id, kind, register_number, event_id, "
                    "occurred_at, details, created_at) "
                    "VALUES (:id, :u, :k, :r, :e, :o, CAST(:d AS jsonb), :c) "
                    "ON CONFLICT (user_id, event_id) DO NOTHING RETURNING id"
                ),
                {
                    "id": alert.id,
                    "u": alert.user_id,
                    "k": alert.kind.value,
                    "r": alert.register_number,
                    "e": alert.event_id,
                    "o": alert.occurred_at,
                    "d": json.dumps(dict(alert.details)),
                    "c": alert.created_at,
                },
            )
            return result.first() is not None

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]:
        async with self._as_user(user_id) as session:
            rows = await session.execute(
                text(
                    "SELECT id, user_id, kind, register_number, event_id, occurred_at, details, "
                    "created_at, read_at FROM watchlist.alerts "
                    "WHERE user_id = :u AND (NOT :unread OR read_at IS NULL) "
                    "ORDER BY occurred_at DESC, id LIMIT :n"
                ),
                {"u": user_id, "unread": unread_only, "n": limit},
            )
            return [
                Alert(
                    id=r.id,
                    user_id=r.user_id,
                    kind=AlertKind(r.kind),
                    register_number=r.register_number,
                    event_id=r.event_id,
                    occurred_at=r.occurred_at,
                    details=r.details,
                    created_at=r.created_at,
                    read_at=r.read_at,
                )
                for r in rows
            ]

    async def unread_count(self, user_id: UUID) -> int:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "SELECT count(*) FROM watchlist.alerts WHERE user_id = :u AND read_at IS NULL"
                ),
                {"u": user_id},
            )
            return int(result.scalar_one())

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "UPDATE watchlist.alerts SET read_at = now() "
                    "WHERE user_id = :u AND read_at IS NULL "
                    "AND (CAST(:a AS uuid) IS NULL OR id = :a) "
                    "RETURNING id"
                ),
                {"u": user_id, "a": alert_id},
            )
            return len(result.all())

    async def forget(self, user_id: UUID) -> None:
        async with self._as_user(user_id) as session:
            for table in ("saved_medicines", "allergies", "alerts"):
                await session.execute(
                    text(f"DELETE FROM watchlist.{table} WHERE user_id = :u"),  # noqa: S608
                    {"u": user_id},
                )
