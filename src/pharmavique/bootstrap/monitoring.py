"""Error and latency monitoring through Sentry (owner's decision, 2026-11-25).

Off unless `PHARMAVIQUE_SENTRY_DSN` is set (the owner creates the Sentry project and puts the DSN in
Vercel). Health data is sensitive (CLAUDE.md), so nothing a person typed or sent leaves with an
event: no request body, query string, headers (the access token), cookies, user, breadcrumbs or
local variables. What is kept is what finds a bug: the message, the stack trace's function names
and lines, the method and the path, the timings.
"""

import os
from collections.abc import Callable
from typing import Any

import sentry_sdk

from pharmavique.bootstrap.settings import Settings

_REQUEST_DROPS = ("data", "query_string", "headers", "cookies", "env")


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Remove everything a person typed or sent from an error or a transaction event."""
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    request = event.get("request")
    if isinstance(request, dict):
        for key in _REQUEST_DROPS:
            request.pop(key, None)
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = url.split("?", 1)[0]
    for value in (event.get("exception") or {}).get("values") or []:
        for frame in (value.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    for span in event.get("spans") or []:
        span.pop("data", None)
    return event


def init_monitoring(settings: Settings, init: Callable[..., Any] = sentry_sdk.init) -> bool:
    """Start Sentry when a DSN is configured; True when it was started."""
    if settings.sentry_dsn is None:
        return False
    init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        release=os.environ.get("VERCEL_GIT_COMMIT_SHA") or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
        before_send_transaction=scrub_event,
    )
    return True
