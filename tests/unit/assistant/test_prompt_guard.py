"""Groq Prompt Guard adapter: the model answers a probability; above the threshold is an attack."""

import json

import httpx
import pytest

from pharmavique.assistant.infrastructure.prompt_guard import GroqPromptGuard


def guard(score: str, status: int = 200, threshold: float = 0.9) -> GroqPromptGuard:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "meta-llama/llama-prompt-guard-2-86m"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(status, json={"choices": [{"message": {"content": score}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GroqPromptGuard("k", "meta-llama/llama-prompt-guard-2-86m", threshold, client)


async def test_a_high_score_is_an_injection() -> None:
    assert await guard("0.9995808005332947").is_injection("hi") is True


async def test_a_low_score_is_not() -> None:
    assert await guard("0.0003982759371865541").is_injection("hi") is False


async def test_an_unreadable_answer_or_an_error_raises_so_the_rules_decide() -> None:
    with pytest.raises(ValueError, match="score"):
        await guard("not a number").is_injection("hi")
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await guard("0.1", status=503).is_injection("hi")
