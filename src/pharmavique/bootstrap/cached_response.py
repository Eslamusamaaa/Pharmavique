"""Serve a public answer through the shared read cache.

Only for answers that are the same for everyone (search, drug pages): nothing here may depend on who
asks. A 404 or any error raised while computing passes through and is never stored. Browsers and
CDNs may keep an answer for `BROWSER_SECONDS` too, which takes most repeat traffic off the API.

On Vercel there is no shared cache, and every request that reaches the function may wait for a cold
start (seconds). The edge keeps an answer for `EDGE_SECONDS` and then serves the old copy while it
fetches a new one in the background (`stale-while-revalidate`), so a page anyone opened recently
answers from the edge. The registry changes once a day, so ten minutes of age is acceptable.
"""

from collections.abc import Awaitable, Callable, Sequence

from fastapi import Request, Response
from pydantic import BaseModel

from pharmavique.foundation.read_cache import ReadCache

BROWSER_SECONDS = 60
EDGE_SECONDS = 600  # `s-maxage`: the CDN only; browsers keep `max-age`
STALE_SECONDS = 86_400  # the edge may serve an older copy while it refreshes


async def cached_json(
    request: Request,
    namespace: str,
    parts: Sequence[str],
    compute: Callable[[], Awaitable[BaseModel]],
) -> Response:
    cache: ReadCache | None = request.app.state.read_cache

    async def render() -> bytes:
        return (await compute()).model_dump_json().encode()

    if cache is None:
        return _response(await render(), None)
    body, hit = await cache.fetch(namespace, parts, render)
    return _response(body, hit)


def _response(body: bytes, hit: bool | None) -> Response:
    headers = {
        "Cache-Control": f"public, max-age={BROWSER_SECONDS}, s-maxage={EDGE_SECONDS}, "
        f"stale-while-revalidate={STALE_SECONDS}"
    }
    if hit is not None:
        headers["X-Cache"] = "hit" if hit else "miss"
    return Response(content=body, media_type="application/json", headers=headers)
