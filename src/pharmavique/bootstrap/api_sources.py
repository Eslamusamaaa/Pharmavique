"""The public "last update and sources" page: every source, its trust grade and its last update.

Open to everyone (it is the answer to "where does this come from"). A figure the database cannot
give (no database here, a source that was never read) is null, never zero and never "now".
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.features import require_feature
from pharmavique.bootstrap.sources_status import SourceStat, SourceStatusReader
from pharmavique.bootstrap.trust import (
    GRADE_LABEL_AR,
    GRADE_LABEL_EN,
    GRADE_MEANING_AR,
    SOURCES,
    TrustGrade,
)

router = APIRouter(prefix="/v1", tags=["sources"])
_log = logging.getLogger(__name__)


class GradeOut(BaseModel):
    grade: TrustGrade
    label_ar: str
    label_en: str
    meaning_ar: str


class SourceOut(BaseModel):
    id: str
    name_ar: str
    name_en: str
    grade: TrustGrade
    grade_label_ar: str
    cadence_ar: str
    used_for_ar: str
    url: str | None
    records: int | None
    last_updated: datetime | None


class SourcesOut(BaseModel):
    generated_at: datetime
    grades: list[GradeOut]
    sources: list[SourceOut]
    disclaimer: str = DISCLAIMER


@router.get(
    "/sources",
    response_model=SourcesOut,
    summary="Data sources, their trust grade and when each was last updated",
    dependencies=[Depends(require_feature("sources_page"))],
)
async def sources(request: Request) -> SourcesOut:
    reader: SourceStatusReader | None = request.app.state.source_status
    stats: dict[str, SourceStat] = {}
    if reader is not None:
        try:
            stats = await reader.read()
        except Exception as error:  # the page must answer even when the database is slow or down
            _log.warning("source status could not be read (%s)", type(error).__name__)
    return SourcesOut(
        generated_at=datetime.now(UTC),
        grades=[
            GradeOut(
                grade=g,
                label_ar=GRADE_LABEL_AR[g],
                label_en=GRADE_LABEL_EN[g],
                meaning_ar=GRADE_MEANING_AR[g],
            )
            for g in TrustGrade
        ],
        sources=[
            SourceOut(
                id=s.id,
                name_ar=s.name_ar,
                name_en=s.name_en,
                grade=s.grade,
                grade_label_ar=GRADE_LABEL_AR[s.grade],
                cadence_ar=s.cadence_ar,
                used_for_ar=s.used_for_ar,
                url=s.url,
                records=stats[s.id].records if s.id in stats else None,
                last_updated=stats[s.id].last_updated if s.id in stats else None,
            )
            for s in SOURCES
        ],
    )
