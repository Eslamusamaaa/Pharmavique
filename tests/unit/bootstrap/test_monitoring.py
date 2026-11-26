"""Error and latency monitoring (Sentry, owner's decision 2026-11-25): on only with a DSN, and it
never carries what a person typed or sent (health data is sensitive, CLAUDE.md)."""

from typing import Any

import pytest
from pharmavique.bootstrap.monitoring import init_monitoring, scrub_event
from pydantic import SecretStr

from pharmavique.bootstrap.settings import Settings


def settings(dsn: str | None, **extra: Any) -> Settings:
    return Settings(_env_file=None, sentry_dsn=SecretStr(dsn) if dsn else None, **extra)


def test_without_a_dsn_nothing_is_started() -> None:
    calls: list[dict[str, Any]] = []

    started = init_monitoring(settings(None), init=lambda **kw: calls.append(kw))

    assert started is False
    assert calls == []


def test_with_a_dsn_it_starts_once_with_privacy_switches_on() -> None:
    calls: list[dict[str, Any]] = []

    started = init_monitoring(
        settings("https://key@o1.ingest.sentry.io/2", environment="prod"),
        init=lambda **kw: calls.append(kw),
    )

    assert started is True
    (call,) = calls
    assert call["dsn"] == "https://key@o1.ingest.sentry.io/2"
    assert call["environment"] == "prod"
    assert call["send_default_pii"] is False
    assert call["include_local_variables"] is False
    assert call["max_request_body_size"] == "never"
    assert call["before_send"] is scrub_event
    assert call["before_send_transaction"] is scrub_event
    assert 0 <= call["traces_sample_rate"] <= 1


def test_the_sampling_rate_comes_from_settings() -> None:
    calls: list[dict[str, Any]] = []

    init_monitoring(
        settings("https://key@o1.ingest.sentry.io/2", sentry_traces_sample_rate=0.25),
        init=lambda **kw: calls.append(kw),
    )

    assert calls[0]["traces_sample_rate"] == 0.25


def test_an_empty_dsn_variable_means_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHARMAVIQUE_SENTRY_DSN", "")
    assert Settings(_env_file=None).sentry_dsn is None


@pytest.mark.parametrize("value", ["-0.1", "1.5"])
def test_a_sampling_rate_outside_zero_to_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PHARMAVIQUE_SENTRY_TRACES_SAMPLE_RATE", value)
    with pytest.raises(ValueError, match="sentry_traces_sample_rate"):
        Settings(_env_file=None)


def event() -> dict[str, Any]:
    return {
        "message": "boom",
        "user": {"id": "u1", "email": "a@example.com", "ip_address": "1.2.3.4"},
        "request": {
            "method": "GET",
            "url": "https://pharmavique.vercel.app/v1/search?q=warfarin%20pregnancy",
            "query_string": "q=warfarin pregnancy",
            "data": {"question": "هل أقدر آخذ الدواء مع الحمل؟"},
            "headers": {"Authorization": "Bearer secret-token", "Cookie": "a=b"},
            "cookies": {"a": "b"},
            "env": {"REMOTE_ADDR": "1.2.3.4"},
        },
        "breadcrumbs": {"values": [{"message": "GET https://api.example/?q=x"}]},
        "exception": {
            "values": [
                {"stacktrace": {"frames": [{"function": "ask", "vars": {"question": "private"}}]}}
            ]
        },
        "spans": [{"description": "SELECT 1", "data": {"db.params": ["private"]}}],
    }


def test_scrubbing_removes_everything_a_person_typed_or_sent() -> None:
    cleaned = scrub_event(event(), {})

    assert cleaned is not None
    assert "user" not in cleaned
    assert "breadcrumbs" not in cleaned
    request = cleaned["request"]
    for key in ("query_string", "data", "headers", "cookies", "env"):
        assert key not in request
    frame = cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert "data" not in cleaned["spans"][0]
    assert "private" not in str(cleaned)
    assert "secret-token" not in str(cleaned)
    assert "warfarin" not in str(cleaned)


def test_scrubbing_keeps_what_helps_to_find_the_bug() -> None:
    cleaned = scrub_event(event(), {})

    assert cleaned is not None
    assert cleaned["message"] == "boom"
    assert cleaned["request"]["method"] == "GET"
    assert cleaned["request"]["url"] == "https://pharmavique.vercel.app/v1/search"
    assert cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]["function"] == "ask"
    assert cleaned["spans"][0]["description"] == "SELECT 1"


def test_scrubbing_an_event_without_those_parts_is_harmless() -> None:
    assert scrub_event({"message": "x"}, {}) == {"message": "x"}
