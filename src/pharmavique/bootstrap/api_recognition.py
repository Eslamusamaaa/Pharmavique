"""Scan endpoints (B6 box scan, C1/C2 prescription): read, match, and leave the choice to a person.

The image is read in memory and dropped with the request; nothing is stored or logged.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.recognition.application.scan import MAX_IMAGE_BYTES, ScanImage
from pharmavique.recognition.domain.scans import ScanKind
from pharmavique.recognition.infrastructure.openai_vision import VisionError

router = APIRouter(prefix="/v1/recognition", tags=["recognition"])


class CandidateOut(BaseModel):
    register_number: str
    trade_name_ar: str | None
    trade_name_en: str | None
    score: float


class LineOut(BaseModel):
    raw_text: str
    name: str
    strength: str | None
    form: str | None
    dose: str | None  # "غير واضح" on prescriptions: the pharmacist confirms; never a read value
    needs_review: bool
    candidates: list[CandidateOut]


class ScanOut(BaseModel):
    kind: ScanKind
    status: str  # "needs_review" or "nothing_read"
    lines: list[LineOut]
    disclaimer: str = DISCLAIMER


def get_scanner(request: Request) -> ScanImage:
    scanner: ScanImage | None = request.app.state.scanner
    if scanner is None:
        raise HTTPException(
            status_code=503,
            detail="scanning is not configured: set PHARMAVIQUE_OPENROUTER_API_KEY "
            "and PHARMAVIQUE_DATABASE_URL",
        )
    return scanner


@router.post("/scan", response_model=ScanOut, summary="Read a box or prescription photo")
async def scan(
    image: Annotated[UploadFile, File(description="a JPEG, PNG or WebP photo, up to 8 MB")],
    scanner: Annotated[ScanImage, Depends(get_scanner)],
    kind: ScanKind = ScanKind.BOX,
) -> ScanOut:
    data = await image.read(MAX_IMAGE_BYTES + 1)
    try:
        result = await scanner.run(data, image.content_type or "", kind)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except VisionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        del data  # the image is not kept beyond this request
    return ScanOut(
        kind=result.kind,
        status=result.status,
        lines=[
            LineOut(
                raw_text=r.line.raw_text,
                name=r.line.name,
                strength=r.line.strength,
                form=r.line.form,
                dose=r.dose,
                needs_review=r.needs_review,
                candidates=[
                    CandidateOut(
                        register_number=c.register_number,
                        trade_name_ar=c.trade_name_ar,
                        trade_name_en=c.trade_name_en,
                        score=round(c.score, 3),
                    )
                    for c in r.candidates
                ],
            )
            for r in result.lines
        ],
    )
