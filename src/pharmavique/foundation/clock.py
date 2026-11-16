"""Clock adapters for the `Clock` port in the shared kernel."""

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
