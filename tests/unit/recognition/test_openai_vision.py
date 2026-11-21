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
