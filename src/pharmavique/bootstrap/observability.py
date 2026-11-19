"""Observability: metrics (Prometheus text format), structured assistant events, request ids.

Nothing here records a question, an answer, an image or audio: those can be health data
(CLAUDE.md). Events carry outcomes, tools, timings, token counts and lengths only.
"""

import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from pharmavique.assistant.application.ports import AssistantEvent

BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GUARDRAIL_OUTCOMES = {"emergency", "injection", "rule_refusal", "ungrounded"}

Labels = tuple[tuple[str, str], ...]


class Metrics:
    """A small thread-safe registry of counters and histograms, rendered for Prometheus."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, float]] = defaultdict(lambda: defaultdict(float))
        self._histograms: dict[str, dict[Labels, list[float]]] = defaultdict(dict)

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._counters[name][key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            # one slot per bucket, then the sum and the count
            series = self._histograms[name].setdefault(key, [0.0] * (len(BUCKETS) + 2))
            for i, bound in enumerate(BUCKETS):
                if value <= bound:
                    series[i] += 1
            series[-2] += value
            series[-1] += 1

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(series.items()):
                    lines.append(f"{name}{_labels(labels)} {_number(value)}")
            for name, series_h in sorted(self._histograms.items()):
                lines.append(f"# TYPE {name} histogram")
                for labels, values in sorted(series_h.items()):
                    for bound, count in zip(BUCKETS, values, strict=False):
                        bucket = (*labels, ("le", str(bound)))
                        lines.append(f"{name}_bucket{_labels(bucket)} {_number(count)}")
                    every = (*labels, ("le", "+Inf"))
                    lines.append(f"{name}_bucket{_labels(every)} {_number(values[-1])}")
                    lines.append(f"{name}_sum{_labels(labels)} {_number(values[-2])}")
                    lines.append(f"{name}_count{_labels(labels)} {_number(values[-1])}")
        return "\n".join(lines) + "\n"


def _labels(labels: Labels) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{value}"' for key, value in labels)
    return "{" + inner + "}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.6g}"


class LoggingAssistantObserver:
    """Implements `AssistantObserver`: one JSON log line and metric updates per question."""

    def __init__(self, metrics: Metrics, logger: logging.Logger | None = None) -> None:
        self._metrics = metrics
        self._log = logger or logging.getLogger("pharmavique.assistant")

    def record(self, event: AssistantEvent) -> None:
        payload = {
            "event": "assistant_answer",
            "outcome": event.outcome,
            "level": event.level,
            "spoken": event.spoken,
            "tool_calls": list(event.tool_calls),
            "tool_errors": event.tool_errors,
            "latency_ms": event.latency_ms,
            "model": event.model,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "citations": event.citations,
            "question_chars": event.question_chars,
            "ungrounded_facts": event.ungrounded_facts,
        }
        self._log.info(json.dumps(payload, ensure_ascii=False))
        m = self._metrics
        m.inc("assistant_answers_total", {"outcome": event.outcome})
        if event.outcome in GUARDRAIL_OUTCOMES:
            m.inc("assistant_guardrail_blocks_total", {"rule": event.outcome})
        for tool in event.tool_calls:
            m.inc("assistant_tool_calls_total", {"tool": tool})
        if event.tool_errors:
            m.inc("assistant_tool_errors_total", value=event.tool_errors)
        m.inc("assistant_tokens_total", {"kind": "input"}, event.input_tokens)
        m.inc("assistant_tokens_total", {"kind": "output"}, event.output_tokens)
        m.observe("assistant_latency_seconds", event.latency_ms / 1000)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Gives every request an id (kept from X-Request-ID when safe) and records HTTP metrics."""

    def __init__(self, app: object, metrics: Metrics) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._metrics = metrics

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        labels = {"route": path, "status": str(response.status_code)}
        self._metrics.inc("http_requests_total", labels)
        self._metrics.observe(
            "http_request_seconds", time.perf_counter() - started, {"route": path}
        )
        response.headers["X-Request-ID"] = request_id
        return response


router = APIRouter(tags=["operations"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    registry: Metrics = request.app.state.metrics
    return Response(registry.render(), media_type="text/plain; version=0.0.4")
