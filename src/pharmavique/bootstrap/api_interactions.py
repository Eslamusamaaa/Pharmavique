"""Interaction check (B-phase 2): which of these products have a recorded interaction.

Informational only. A finding is a source's statement, with its severity as the source rates it;
nothing here says to stop or change a medicine, and "nothing found" is never "safe" (`complete` is
always false). The pharmacist or doctor decides.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from pharmavique.bootstrap.cached_response import cached_json
from pharmavique.catalog.contracts.queries import CatalogQueries
from pharmavique.interactions.contracts.queries import (
    ContraindicationChecks,
    InteractionChecks,
    ProductIngredients,
)
from pharmavique.shared_kernel.market import Market

router = APIRouter(prefix="/v1/interactions", tags=["interactions"])
MAX_PRODUCTS = 20
NOTE_AR = (
    "هذه معلومات من مصدر خارجي وليست نصيحة طبية. عدم ظهور تداخل لا يعني أن الجمع آمن، "
    "والصيدلي أو الطبيب هو من يقرر."
)


class CheckIn(BaseModel):
    register_numbers: list[str] = Field(min_length=2, max_length=MAX_PRODUCTS)


class ProductOut(BaseModel):
    register_number: str
    trade_name_ar: str | None
    trade_name_en: str | None
    ingredients: list[str]


class FindingOut(BaseModel):
    kind: str  # "interaction" or "duplicate_ingredient"
    severity: str | None  # as the source rates it; None for a duplicate
    registers: list[str]
    ingredients: list[str]
    source: str | None


class UnmatchedOut(BaseModel):
    register_number: str
    ingredient: str


class CheckOut(BaseModel):
    products: list[ProductOut]
    findings: list[FindingOut]
    unmatched: list[UnmatchedOut]  # ingredients the source cannot judge: not "no interaction"
    unknown_registers: list[str]
    complete: bool
    note: str


def get_checks(request: Request) -> InteractionChecks:
    backend: InteractionChecks | None = request.app.state.interactions
    if backend is None:
        raise HTTPException(status_code=503, detail="interactions are not available")
    return backend


def get_catalog(request: Request) -> CatalogQueries:
    backend: CatalogQueries | None = request.app.state.catalog
    if backend is None:
        raise HTTPException(status_code=503, detail="the catalog is not available")
    return backend


@router.post("/check", response_model=CheckOut, summary="Recorded interactions among products")
async def check(
    body: CheckIn,
    checks: Annotated[InteractionChecks, Depends(get_checks)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
) -> CheckOut:
    wanted = list(dict.fromkeys(body.register_numbers))
    order = {register: index for index, register in enumerate(wanted)}
    cards = sorted(
        await catalog.get_cards(Market.SA, wanted), key=lambda card: order[card.register_number]
    )
    found = {card.register_number for card in cards}
    report = await checks.run(
        [
            ProductIngredients(
                card.register_number,
                card.trade_name_en or card.trade_name_ar or card.register_number,
                card.ingredient_names,
            )
            for card in cards
        ]
    )
    return CheckOut(
        products=[
            ProductOut(
                register_number=card.register_number,
                trade_name_ar=card.trade_name_ar,
                trade_name_en=card.trade_name_en,
                ingredients=list(card.ingredient_names),
            )
            for card in cards
        ],
        findings=[
            FindingOut(
                kind=f.kind,
                severity=f.severity,
                registers=list(f.registers),
                ingredients=list(f.ingredients),
                source=f.source,
            )
            for f in report.findings
        ],
        unmatched=[UnmatchedOut(register_number=r, ingredient=i) for r, i in report.unmatched],
        unknown_registers=[r for r in wanted if r not in found],
        complete=report.complete,
        note=NOTE_AR,
    )


class ContraindicationOut(BaseModel):
    ingredient: str  # the registry's name
    disease: str  # as the source names the condition
    text: str  # the label text it was taken from
    source: str


class ContraindicationsOut(BaseModel):
    register_number: str
    items: list[ContraindicationOut]  # only conditions the label text itself names
    hidden_unverified: int  # source rows not shown because their text does not name the condition
    complete: bool  # always false: a missing record is never a clearance
    note: str


def get_contraindications(request: Request) -> ContraindicationChecks:
    backend: ContraindicationChecks | None = request.app.state.contraindications
    if backend is None:
        raise HTTPException(status_code=503, detail="contraindications are not available")
    return backend


@router.get(
    "/contraindications/{register_number}",
    response_model=ContraindicationsOut,
    summary="Conditions the ingredients of a product are recorded as contraindicated with",
)
async def contraindications(
    register_number: str,
    request: Request,
    checks: Annotated[ContraindicationChecks, Depends(get_contraindications)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
) -> Response:
    async def compute() -> ContraindicationsOut:
        cards = await catalog.get_cards(Market.SA, [register_number])
        if not cards:
            raise HTTPException(status_code=404, detail="no product with this register number")
        card = cards[0]
        # The route tells a cream or an eye drop from a tablet: label contraindications are about
        # the tablet or injection and are not shown for local use.
        details_backend = getattr(request.app.state, "details", None)
        details = (
            await details_backend.get_details(Market.SA, card.register_number)
            if details_backend is not None
            else None
        )
        report = await checks.run(
            [
                ProductIngredients(
                    card.register_number,
                    card.trade_name_en or card.trade_name_ar or card.register_number,
                    card.ingredient_names,
                    details.route_en if details else None,
                    card.dosage_form_en,
                )
            ]
        )
        return ContraindicationsOut(
            register_number=card.register_number,
            items=[
                ContraindicationOut(
                    ingredient=item.ingredient,
                    disease=item.disease,
                    text=item.text,
                    source=item.source,
                )
                for item in report.items
            ],
            hidden_unverified=report.hidden_unverified,
            complete=report.complete,
            note=NOTE_AR,
        )

    return await cached_json(request, "contraindications", [register_number], compute)
