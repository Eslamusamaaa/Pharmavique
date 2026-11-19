"""Observability: metrics in Prometheus text, structured assistant events without health data,
and a request id on every response."""

import json
import logging

import httpx
import pytest

from pharmavique.assistant.application.ports import AssistantEvent
from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.observability import LoggingAssistantObserver, Metrics


def event(**overrides: object) -> AssistantEvent:
    values: dict[str, object] = {
        "outcome": "answered",
        "level": "patient",
        "spoken": False,
        "tool_calls": ("search_drugs", "drug_details"),
        "tool_errors": 0,
        "latency_ms": 1234,
        "model": "openai/gpt-oss-120b",
        "input_tokens": 900,
        "output_tokens": 80,
        "citations": 1,
        "question_chars": 25,
    }
    values.update(overrides)
    return AssistantEvent(**values)  # type: ignore[arg-type]


def test_counters_and_latency_render_as_prometheus_text() -> None:
    metrics = Metrics()
    metrics.inc("assistant_answers_total", {"outcome": "answered"})
    metrics.inc("assistant_answers_total", {"outcome": "answered"})
    metrics.observe("assistant_latency_seconds", 1.2)

    text = metrics.render()

    assert 'assistant_answers_total{outcome="answered"} 2' in text
    assert "assistant_latency_seconds_count 1" in text
    assert 'assistant_latency_seconds_bucket{le="2.5"} 1' in text


def test_an_assistant_event_is_logged_as_json_and_counted(caplog: pytest.LogCaptureFixture) -> None:
    metrics = Metrics()
    observer = LoggingAssistantObserver(metrics)

    with caplog.at_level(logging.INFO, logger="pharmavique.assistant"):
        observer.record(event(outcome="ungrounded", ungrounded_facts=2, tool_errors=1))

    record = json.loads(caplog.records[-1].getMessage())
    assert record["event"] == "assistant_answer"
    assert record["outcome"] == "ungrounded"
    assert record["tool_calls"] == ["search_drugs", "drug_details"]
    text = metrics.render()
    assert 'assistant_answers_total{outcome="ungrounded"} 1' in text
    assert 'assistant_guardrail_blocks_total{rule="ungrounded"} 1' in text
    assert 'assistant_tool_calls_total{tool="drug_details"} 1' in text
    assert "assistant_tool_errors_total 1" in text
    assert "assistant_tokens_total" in text


async def test_metrics_endpoint_and_request_ids() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health", headers={"X-Request-ID": "abc-123"})
        fresh = await client.get("/health")
        metrics = await client.get("/metrics")

    assert health.headers["x-request-id"] == "abc-123"
    assert len(fresh.headers["x-request-id"]) == 32
    assert metrics.status_code == 200
    assert 'http_requests_total{route="/health",status="200"} 2' in metrics.text
