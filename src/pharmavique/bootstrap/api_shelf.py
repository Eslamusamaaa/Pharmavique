"""A pharmacist's shelf list (which optional features are on: `bootstrap.features`).

The shelf scan only proposes boxes; a medicine joins the list when the pharmacist confirms it. The
list says which medicines they shelve: no counts, nothing about stock. For pharmacist accounts only.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from pharmavique.bootstrap.api_auth import require_roles
from pharmavique.bootstrap.api_drugs import DISCLAIMER, ProductOut, _product, get_catalog
from pharmavique.catalog.contracts.queries import CatalogQueries
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role
from pharmavique.watchlist.application.shelf import ShelfService

router = APIRouter(tags=["shelf"])

MAX_CONFIRM = 100
Pharmacist = Annotated[Principal, Depends(require_roles(Role.PHARMACIST, Role.OPERATOR))]


def get_shelf(request: Request) -> ShelfService:
    service: ShelfService | None = request.app.state.shelf
    if service is None:
        raise HTTPException(status_code=503, detail="the shelf list is not configured")
    return service


Shelf = Annotated[ShelfService, Depends(get_shelf)]


class ConfirmIn(BaseModel):
    register_numbers: list[str] = Field(min_length=1, max_length=MAX_CONFIRM)


class ConfirmOut(BaseModel):
    added: int
    already_on_the_shelf: int
    unknown: list[str]  # register numbers the catalog does not have: not added


class ShelfItemOut(BaseModel):
    register_number: str
    added_at: str
    product: ProductOut | None


class ShelfOut(BaseModel):
    count: int
    items: list[ShelfItemOut]
    note: str = (
        "The medicines you confirmed after scanning your shelf. It holds no counts and says "
        "nothing about stock."
    )
    disclaimer: str = DISCLAIMER


@router.get("/v1/me/shelf", response_model=ShelfOut, summary="My shelf list (pharmacists)")
async def my_shelf(
    me: Pharmacist, shelf: Shelf, catalog: Annotated[CatalogQueries, Depends(get_catalog)]
) -> ShelfOut:
    items = await shelf.items(me.user_id)
    cards = {
        c.register_number: c
        for c in await catalog.get_cards(Market.SA, [i.register_number for i in items])
    }
    return ShelfOut(
        count=len(items),
        items=[
            ShelfItemOut(
                register_number=i.register_number,
                added_at=i.added_at.isoformat(),
                product=_product(cards[i.register_number]) if i.register_number in cards else None,
            )
            for i in items
        ],
    )


@router.post(
    "/v1/me/shelf", response_model=ConfirmOut, summary="Confirm medicines found on my shelf"
)
async def confirm_shelf(
    body: ConfirmIn,
    me: Pharmacist,
    shelf: Shelf,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
) -> ConfirmOut:
    wanted = list(dict.fromkeys(r.strip() for r in body.register_numbers if r.strip()))
    known = {c.register_number for c in await catalog.get_cards(Market.SA, wanted)}
    unknown = [r for r in wanted if r not in known]
    to_add = [r for r in wanted if r in known]
    if not to_add:
        return ConfirmOut(added=0, already_on_the_shelf=0, unknown=unknown)
    try:
        added = await shelf.confirm(me.user_id, to_add)
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return ConfirmOut(added=added, already_on_the_shelf=len(to_add) - added, unknown=unknown)


@router.delete(
    "/v1/me/shelf/{register_number}", status_code=204, summary="Take a medicine off my shelf list"
)
async def remove_from_shelf(register_number: str, me: Pharmacist, shelf: Shelf) -> Response:
    await shelf.remove(me.user_id, register_number)
    return Response(status_code=204)
