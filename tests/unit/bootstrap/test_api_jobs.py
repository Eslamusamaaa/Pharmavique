"""Background jobs through the API: submit, poll, limits, and the direct endpoint's result."""

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun, AssistantBusy
from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.job_handlers import build_handlers
from pharmavique.foundation.jobs import InlineJobQueue, JobRunner
from pharmavique.foundation.kv import MemoryStore
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.domain.scans import ExtractedLine, MatchCandidate, ScanKind
from pharmavique.recognition.infrastructure.openai_vision import VisionError

pytestmark = pytest.mark.usefixtures("ai_open_to_guests")

CITE = Citation("catalog:1-1", "بانادول · سجل الأدوية (SFDA)", "https://s/1", "catalog", None)


class Reader:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        if self.fail:
            raise self.fail
        return [ExtractedLine("Panadol Extra 500mg", "Panadol Extra", "500 mg", "tab")]


class Finder:
    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        return [MatchCandidate("1-1", "بانادول اكسترا", "PANADOL EXTRA TAB", 0.8123)]


class Runner:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        if self.busy:
            raise AssistantBusy
        return AgentRun("المادة الفعالة هي الباراسيتامول [1].", (CITE,), ("drug_details",))


def make(
    *,
    reader: Reader | None = None,
    runner: Runner | None = None,
    store: MemoryStore | None = None,
    jobs_per_user_per_minute: int | None = None,
) -> tuple[httpx.AsyncClient, InlineJobQueue]:
    store = store or MemoryStore()
    handlers = build_handlers(
        ScanImage(reader or Reader(), Finder()), AskAssistant(runner or Runner())
    )
    queue = InlineJobQueue(JobRunner(store, handlers))
    app = create_app(
        jobs=queue,
        store=store,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
        jobs_per_user_per_minute=jobs_per_user_per_minute,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, queue


@pytest.fixture
async def rig() -> AsyncIterator[tuple[httpx.AsyncClient, InlineJobQueue]]:
    client, queue = make()
    async with client:
        yield client, queue


async def submit_scan(client: httpx.AsyncClient, kind: str = "prescription") -> httpx.Response:
    return await client.post(
        "/v1/jobs/scan",
        params={"kind": kind},
        files={"image": ("rx.png", b"\x89PNG....", "image/png")},
    )


async def test_a_scan_job_is_accepted_then_done_with_the_same_result_as_the_direct_endpoint(
    rig: tuple[httpx.AsyncClient, InlineJobQueue],
) -> None:
    client, queue = rig
    ticket = await submit_scan(client)
    assert ticket.status_code == 202
    body = ticket.json()
    assert body["status"] == "queued"
    assert body["poll_url"] == f"/v1/jobs/{body['job_id']}"

    await queue.drain()
    done = (await client.get(body["poll_url"])).json()

    assert done["status"] == "done"
    assert done["kind"] == "scan"
    (line,) = done["result"]["lines"]
    assert line["dose"] == "غير واضح"
    assert line["candidates"][0]["register_number"] == "1-1"
    assert done["result"]["disclaimer"]


async def test_an_assistant_job_returns_the_cited_answer(
    rig: tuple[httpx.AsyncClient, InlineJobQueue],
) -> None:
    client, queue = rig
    ticket = await client.post(
        "/v1/jobs/assistant", json={"question": "ايه ده؟", "level": "pharmacist"}
    )
    await queue.drain()
    done = (await client.get(ticket.json()["poll_url"])).json()

    assert done["status"] == "done"
    assert done["result"]["answer"] == "المادة الفعالة هي الباراسيتامول [1]."
    assert done["result"]["citations"][0]["source_id"] == "catalog:1-1"


async def test_an_unreadable_photo_fails_with_a_short_code() -> None:
    client, queue = make(reader=Reader(fail=VisionError("provider said: patient is Mr X")))
    async with client:
        ticket = await submit_scan(client)
        await queue.drain()
        done = (await client.get(ticket.json()["poll_url"])).json()

    assert done["status"] == "failed"
    assert done["error"] == "vision_unavailable"
    assert "Mr X" not in str(done)  # provider text never reaches the caller


async def test_a_busy_assistant_is_a_failed_job_with_the_busy_code() -> None:
    client, queue = make(runner=Runner(busy=True))
    async with client:
        ticket = await client.post("/v1/jobs/assistant", json={"question": "x"})
        await queue.drain()
        done = (await client.get(ticket.json()["poll_url"])).json()

    assert (done["status"], done["error"]) == ("failed", "busy")


async def test_an_unknown_job_is_404(rig: tuple[httpx.AsyncClient, InlineJobQueue]) -> None:
    client, _ = rig
    assert (await client.get("/v1/jobs/not-a-real-id")).status_code == 404


async def test_a_job_id_is_long_and_unguessable(
    rig: tuple[httpx.AsyncClient, InlineJobQueue],
) -> None:
    client, queue = rig
    first = (await submit_scan(client)).json()["job_id"]
    second = (await submit_scan(client)).json()["job_id"]
    await queue.drain()
    assert len(first) >= 32
    assert first != second


async def test_an_oversized_photo_is_refused_before_a_job_is_made(
    rig: tuple[httpx.AsyncClient, InlineJobQueue],
) -> None:
    client, _ = rig
    big = b"\x89PNG" + b"0" * (8 * 1024 * 1024 + 1)
    response = await client.post("/v1/jobs/scan", files={"image": ("big.png", big, "image/png")})
    assert response.status_code == 413


async def test_without_a_queue_jobs_say_so() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/v1/jobs/assistant", json={"question": "x"})
    assert response.status_code == 503


async def test_a_feature_without_a_handler_is_not_configured() -> None:
    store = MemoryStore()
    queue = InlineJobQueue(JobRunner(store, build_handlers(None, AskAssistant(Runner()))))
    app = create_app(
        jobs=queue, store=store, rate_limit_per_minute=0, heavy_rate_limit_per_minute=0
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await submit_scan(c)
    assert response.status_code == 503
    assert "scan" in response.json()["detail"]


async def test_each_caller_may_submit_only_a_few_jobs_a_minute() -> None:
    client, queue = make(jobs_per_user_per_minute=2)
    async with client:
        codes = [(await submit_scan(client)).status_code for _ in range(3)]
        await queue.drain()
    assert codes == [202, 202, 429]


async def test_polling_is_never_rate_limited_as_heavy_work() -> None:
    store = MemoryStore()
    handlers = build_handlers(ScanImage(Reader(), Finder()), None)
    queue = InlineJobQueue(JobRunner(store, handlers))
    app = create_app(
        jobs=queue, store=store, rate_limit_per_minute=1000, heavy_rate_limit_per_minute=1
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        job_id = (await submit_scan(c)).json()["job_id"]
        await queue.drain()
        polls = [(await c.get(f"/v1/jobs/{job_id}")).status_code for _ in range(5)]
        second_submit = await submit_scan(c)
    assert polls == [200] * 5
    assert second_submit.status_code == 429  # submitting is heavy: one a minute here


async def test_a_deep_queue_refuses_new_jobs_with_retry_after() -> None:
    class Deep(InlineJobQueue):
        async def depth(self) -> int:
            return 5

    store = MemoryStore()
    queue = Deep(JobRunner(store, build_handlers(ScanImage(Reader(), Finder()), None)))
    app = create_app(
        jobs=queue,
        store=store,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
        job_max_queue_depth=5,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await submit_scan(c)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"


async def test_my_medicines_cannot_be_used_in_a_background_job_yet(
    rig: tuple[httpx.AsyncClient, InlineJobQueue],
) -> None:
    client, _ = rig
    response = await client.post(
        "/v1/jobs/assistant", json={"question": "x", "register_number": "1", "use_history": True}
    )
    assert response.status_code == 422
