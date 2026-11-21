"""Slow work as background jobs: submit a photo or a question, then poll for the result.

`POST` answers 202 with a job id at once; `GET /v1/jobs/{id}` says `queued`, `running`, `done`
(with the same JSON the synchronous endpoint returns) or `failed` (with a short code). The job id is
a long random token and is the only thing needed to read the result, which is kept for a few
minutes. The synchronous endpoints stay: they are the fallback if jobs are not available.

Limits: each caller (the signed-in account's address, else the client address) may submit a few jobs
a minute, and new jobs are refused with 503 and `Retry-After` while the queue is deep, so a burst
becomes a short wait instead of a pile of timeouts.
"""

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from pharmavique.bootstrap.api_assistant import AskIn
from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.job_handlers import ASSISTANT, SCAN
from pharmavique.bootstrap.rate_limit import client_address
from pharmavique.foundation.jobs import JobQueue
from pharmavique.foundation.kv import KeyValueStore, StoreUnavailable
from pharmavique.recognition.application.scan import MAX_IMAGE_BYTES
from pharmavique.recognition.domain.scans import ScanKind

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@dataclass(frozen=True, slots=True)
class JobLimits:
    per_user_per_minute: int  # submissions per caller; 0 turns the limit off
    max_queue_depth: int  # new jobs are refused while this many are waiting
    trusted_proxy_hops: int


RETRY_AFTER_SECONDS = "5"
FAILURE_STATUS = {"worker_unavailable": 503, "busy": 429}


class TicketOut(BaseModel):
    job_id: str
    status: Literal["queued"] = "queued"
    poll_url: str
    disclaimer: str = DISCLAIMER


class JobOut(BaseModel):
    job_id: str
    kind: str
    status: Literal["queued", "running", "done", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None  # a short code, never text from the photo or the question


def get_jobs(request: Request) -> JobQueue:
    jobs: JobQueue | None = request.app.state.jobs
    if jobs is None:
        raise HTTPException(status_code=503, detail="background jobs are not available")
    return jobs


Jobs = Annotated[JobQueue, Depends(get_jobs)]


async def _admit(request: Request, jobs: JobQueue) -> None:
    limits: JobLimits = request.app.state.job_limits
    store: KeyValueStore | None = request.app.state.kv
    try:
        if await jobs.depth() >= limits.max_queue_depth:
            raise HTTPException(
                status_code=503,
                detail="too many jobs are waiting, try again shortly",
                headers={"Retry-After": RETRY_AFTER_SECONDS},
            )
        if store is not None and limits.per_user_per_minute > 0:
            owner = client_address(request, limits.trusted_proxy_hops)
            count, left = await store.window_hit(f"pv:jobs:{owner}", 60)
            if count > limits.per_user_per_minute:
                raise HTTPException(
                    status_code=429,
                    detail="too many jobs submitted, try again shortly",
                    headers={"Retry-After": str(left)},
                )
    except StoreUnavailable:
        raise HTTPException(status_code=503, detail="background jobs are not available") from None


async def _submit(
    request: Request, jobs: JobQueue, kind: str, meta: dict[str, Any], data: bytes
) -> TicketOut:
    await _admit(request, jobs)
    try:
        job_id = await jobs.submit(kind, meta, data)
    except ValueError:  # no handler: that feature is not configured here
        raise HTTPException(status_code=503, detail=f"{kind} jobs are not configured") from None
    except StoreUnavailable:
        raise HTTPException(status_code=503, detail="background jobs are not available") from None
    return TicketOut(job_id=job_id, poll_url=f"/v1/jobs/{job_id}")


@router.post(
    "/scan", response_model=TicketOut, status_code=202, summary="Read a photo in the background"
)
async def submit_scan(
    request: Request,
    image: Annotated[UploadFile, File(description="a JPEG, PNG or WebP photo, up to 8 MB")],
    jobs: Jobs,
    kind: ScanKind = ScanKind.BOX,
) -> TicketOut:
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="the photo is larger than 8 MB")
    meta = {"kind": kind.value, "content_type": image.content_type or ""}
    return await _submit(request, jobs, SCAN, meta, data)


@router.post(
    "/assistant", response_model=TicketOut, status_code=202, summary="Ask in the background"
)
async def submit_question(request: Request, body: AskIn, jobs: Jobs) -> TicketOut:
    return await _submit(
        request, jobs, ASSISTANT, {}, json.dumps(body.model_dump(mode="json")).encode()
    )


@router.get("/{job_id}", response_model=JobOut, summary="The state and result of a job")
async def job_status(job_id: str, jobs: Jobs) -> JobOut:
    try:
        found = await jobs.status(job_id)
    except StoreUnavailable:
        raise HTTPException(status_code=503, detail="background jobs are not available") from None
    if found is None:
        raise HTTPException(status_code=404, detail="no such job, or its result has expired")
    return JobOut(
        job_id=found.job_id,
        kind=found.kind,
        status=found.state,
        result=dict(found.result) if found.result is not None else None,
        error=found.error,
    )
