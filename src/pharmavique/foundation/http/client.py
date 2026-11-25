"""HTTP clients that share one TLS context.

Each `httpx.AsyncClient` loads the certificate bundle again when it is created: 0.18 s each, and the
API makes a dozen of them at startup (model, voice, vision, embedding and search providers), which
was 2.1 s of every cold start. One context, built once, is shared by all of them.
"""

import functools
import ssl
from typing import Any

import httpx


@functools.cache
def tls_context() -> ssl.SSLContext:
    return httpx.create_ssl_context()


def async_client(**options: Any) -> httpx.AsyncClient:
    """`httpx.AsyncClient(**options)` with the shared TLS context."""
    return httpx.AsyncClient(verify=tls_context(), **options)
