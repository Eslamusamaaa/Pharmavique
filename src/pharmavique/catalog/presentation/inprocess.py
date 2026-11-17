"""Inbound adapter: the catalog's published commands, served in-process.

Other contexts call `CatalogCommands`; today that is a direct call, later it can be an HTTP client
with the same shape (ARCHITECTURE.md section 7).
"""

from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    ApplyCatalogChangesResult,
    WithdrawProducts,
    WithdrawProductsResult,
)


class InProcessCatalogCommands:
    """Implements `CatalogCommands` by running the handlers."""

    def __init__(
        self, apply_handler: ApplyCatalogChangesHandler, withdraw_handler: WithdrawProductsHandler
    ) -> None:
        self._apply = apply_handler
        self._withdraw = withdraw_handler

    async def apply_changes(self, command: ApplyCatalogChanges) -> ApplyCatalogChangesResult:
        return await self._apply.handle(command)

    async def withdraw(self, command: WithdrawProducts) -> WithdrawProductsResult:
        return await self._withdraw.handle(command)
