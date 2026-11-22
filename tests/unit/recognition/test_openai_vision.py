"""The vision reader against a fake endpoint, and how its JSON answer is read."""

import json

import httpx
import pytest

from pharmavique.recognition.domain.scans import ScanKind
from pharmavique.recognition.infrastructure.openai_vision import (
    OpenAICompatibleVisionReader,
    VisionError,
    parse_lines,
)


def test_json_inside_prose_or_a_code_fence_is_read() -> None:
    content = (
        'Here:\n```json\n{"lines": [{"name": "Panadol Extra", '
        '"strength": "500 mg", "form": null}]}\n```'
    )

    (line,) = parse_lines(content)

    assert (line.name, line.strength, line.form, line.raw_text) == (
        "Panadol Extra",
        "500 mg",
        None,
        "Panadol Extra",
    )


@pytest.mark.parametrize(
    "content",
    ["", "no json here", "{broken", '{"lines": "x"}', '{"lines": [{"name": " "}, 5]}'],
)
def test_anything_unreadable_gives_no_lines(content: str) -> None:
    assert parse_lines(content) == []


async def test_the_image_goes_as_a_data_url_with_the_kind_prompt() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        answer = '{"lines": [{"name": "بنادول", "strength": null, "form": "قرص"}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reader = OpenAICompatibleVisionReader("https://or.test/api/v1", "k", "vision-1", client)

    (line,) = await reader.read(b"IMG", "image/png", ScanKind.PRESCRIPTION)

    assert line.name == "بنادول"
    assert seen["url"] == "https://or.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "vision-1"
    text_part, image_part = body["messages"][0]["content"]
    assert "Do NOT read doses" in text_part["text"]
    assert image_part["image_url"]["url"] == "data:image/png;base64,SU1H"


async def test_a_provider_error_is_a_vision_error_without_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reader = OpenAICompatibleVisionReader("https://or.test", "secret", "m", client)

    with pytest.raises(VisionError, match="HTTP 429") as raised:
        await reader.read(b"IMG", "image/png", ScanKind.BOX)
    assert "secret" not in str(raised.value)


async def test_the_next_model_is_tried_when_one_is_busy() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import FallbackVisionReader

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "busy":
            return httpx.Response(429)
        answer = '{"lines": [{"name": "Panadol"}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    readers = [
        OpenAICompatibleVisionReader("https://or.test", "k", m, client) for m in ("busy", "ok")
    ]

    (line,) = await FallbackVisionReader(readers).read(b"IMG", "image/png", ScanKind.BOX)

    assert line.name == "Panadol"
    assert calls == ["busy", "ok"]


async def test_a_connection_dropped_in_the_middle_of_an_answer_tries_the_next_model() -> None:
    # seen live on 2026-11-22: the provider cut the connection while the answer was being read
    # (httpx.ReadError) and the whole scan came back as HTTP 500
    from pharmavique.recognition.infrastructure.openai_vision import FallbackVisionReader

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] == "dropped":
            raise httpx.ReadError("connection closed", request=request)
        answer = '{"lines": [{"name": "Panadol"}]}'
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    readers = [
        OpenAICompatibleVisionReader("https://or.test", "k", m, client) for m in ("dropped", "ok")
    ]

    (line,) = await FallbackVisionReader(readers).read(b"IMG", "image/png", ScanKind.BOX)

    assert line.name == "Panadol"


async def test_when_every_connection_drops_the_scan_fails_as_a_vision_error() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import FallbackVisionReader

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    readers = [OpenAICompatibleVisionReader("https://or.test", "k", m, client) for m in ("a", "b")]

    with pytest.raises(VisionError):
        await FallbackVisionReader(readers).read(b"IMG", "image/png", ScanKind.BOX)


async def test_an_answer_that_is_not_json_is_a_vision_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    )
    reader = OpenAICompatibleVisionReader("https://or.test", "k", "m", client)

    with pytest.raises(VisionError):
        await reader.read(b"IMG", "image/png", ScanKind.BOX)


async def test_when_every_model_fails_the_last_error_is_raised() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import FallbackVisionReader

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    readers = [OpenAICompatibleVisionReader("https://or.test", "k", m, client) for m in ("a", "b")]

    with pytest.raises(VisionError, match="HTTP 503"):
        await FallbackVisionReader(readers).read(b"IMG", "image/png", ScanKind.BOX)


def test_the_shelf_prompt_asks_for_every_legible_box_and_never_for_counts_or_guesses() -> None:
    from pharmavique.recognition.domain.scans import ScanKind
    from pharmavique.recognition.infrastructure.openai_vision import _FORMAT, _PROMPTS

    prompt = (_PROMPTS[ScanKind.SHELF] + _FORMAT).lower()
    assert "shelf" in prompt
    assert "every" in prompt
    assert "count" in prompt  # told not to count units
    assert "never guess" in prompt


def _png(width: int, height: int) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_large_photo_is_shrunk_to_a_jpeg_before_it_goes_to_the_provider() -> None:
    import io

    from PIL import Image

    from pharmavique.recognition.infrastructure.openai_vision import shrink

    data, media_type = shrink(_png(4000, 3000), "image/png")

    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(data)) as shrunk:
        assert max(shrunk.size) <= 1600
        assert shrunk.size[0] / shrunk.size[1] == pytest.approx(4 / 3, rel=0.01)


def test_a_small_picture_is_left_exactly_as_it_is() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import shrink

    original = _png(640, 320)

    assert shrink(original, "image/png") == (original, "image/png")


def test_bytes_that_are_not_an_image_are_passed_on_unchanged() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import shrink

    assert shrink(b"IMG", "image/png") == (b"IMG", "image/png")


async def test_when_every_model_fails_the_error_names_each_model_and_status() -> None:
    from pharmavique.recognition.infrastructure.openai_vision import FallbackVisionReader

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429 if json.loads(request.content)["model"] == "first" else 503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    readers = [
        OpenAICompatibleVisionReader("https://or.test", "k", m, client) for m in ("first", "second")
    ]

    with pytest.raises(VisionError) as raised:
        await FallbackVisionReader(readers).read(b"IMG", "image/png", ScanKind.BOX)

    message = str(raised.value)
    assert "first" in message
    assert "429" in message
    assert "second" in message
    assert "503" in message
