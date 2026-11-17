"""The polite web adapters, on httpx's mock transport: nothing touches the network."""

import httpx

from pharmavique.foundation.http.throttle import Throttle
from pharmavique.media.infrastructure.web import HttpImageDownloader, PoliteWeb, WebPageReader

JPEG = b"\xff\xd8\xff" + b"x" * 2000

PAGE = """<html><head><title>Panadol Extra 24S | Shop</title>
<meta property="og:image" content="/img/panadol.jpg">
<meta name="description" content="Paracetamol 500mg Caffeine 65mg tablets">
</head><body><h1>Panadol Extra</h1><script>var x = "ignore me";</script>
<p>Fast pain relief. Made by GlaxoSmithKline.</p></body></html>"""


class Site:
    """A scripted website: path -> (status, content type, body); counts requests per path."""

    def __init__(self, routes: dict[str, tuple[int, str, bytes]]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        status, content_type, body = self.routes.get(path, (404, "text/plain", b""))
        return httpx.Response(status, headers={"content-type": content_type}, content=body)


def web(site: Site) -> PoliteWeb:
    client = httpx.AsyncClient(transport=httpx.MockTransport(site))
    return PoliteWeb(client, lambda: Throttle(0.0), user_agent="test-agent")


def html(body: str, status: int = 200) -> tuple[int, str, bytes]:
    return status, "text/html", body.encode()


async def test_a_page_is_read_into_a_candidate_with_its_image_and_text() -> None:
    site = Site({"/robots.txt": (404, "text/plain", b""), "/p/panadol": html(PAGE)})

    candidate = await WebPageReader(web(site)).read("https://shop.example.sa/p/panadol")

    assert candidate is not None
    assert candidate.image_url == "https://shop.example.sa/img/panadol.jpg"
    assert candidate.page_url == "https://shop.example.sa/p/panadol"
    assert "Panadol Extra 24S" in candidate.title
    assert candidate.alt_text == "Panadol Extra"
    assert "500mg" in candidate.page_text
    assert "GlaxoSmithKline" in candidate.page_text
    assert "ignore me" not in candidate.page_text


async def test_a_page_robots_txt_disallows_is_never_requested() -> None:
    site = Site(
        {
            "/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /p/\n"),
            "/p/panadol": html(PAGE),
        }
    )

    candidate = await WebPageReader(web(site)).read("https://shop.example.sa/p/panadol")

    assert candidate is None
    assert "/p/panadol" not in site.requests


async def test_a_403_marks_the_site_blocked_and_it_is_not_asked_again() -> None:
    site = Site({"/robots.txt": (404, "text/plain", b""), "/p/a": html("denied", 403)})
    polite = web(site)
    reader = WebPageReader(polite)

    first = await reader.read("https://shop.example.sa/p/a")
    second = await reader.read("https://shop.example.sa/p/b")

    assert first is None
    assert second is None
    assert polite.blocked_hosts == {"shop.example.sa"}
    assert site.requests.count("/p/b") == 0


async def test_a_bot_check_page_counts_as_a_block_even_with_status_200() -> None:
    site = Site(
        {
            "/robots.txt": (404, "text/plain", b""),
            "/p/a": html("<html><title>Just a moment...</title></html>"),
        }
    )
    polite = web(site)

    assert await WebPageReader(polite).read("https://shop.example.sa/p/a") is None
    assert "shop.example.sa" in polite.blocked_hosts


async def test_a_blocked_robots_txt_blocks_the_site_without_reading_pages() -> None:
    site = Site({"/robots.txt": (403, "text/html", b"denied"), "/p/a": html(PAGE)})
    polite = web(site)

    assert await WebPageReader(polite).read("https://shop.example.sa/p/a") is None
    assert "/p/a" not in site.requests


async def test_a_page_without_an_image_gives_nothing() -> None:
    site = Site(
        {"/robots.txt": (404, "text/plain", b""), "/p/a": html("<html><title>x</title></html>")}
    )

    assert await WebPageReader(web(site)).read("https://shop.example.sa/p/a") is None


async def test_a_real_image_is_downloaded_with_its_type() -> None:
    site = Site({"/robots.txt": (404, "text/plain", b""), "/i.jpg": (200, "image/jpeg", JPEG)})

    image = await HttpImageDownloader(web(site)).download("https://cdn.example.sa/i.jpg")

    assert image is not None
    assert image.content_type == "image/jpeg"
    assert image.data == JPEG


async def test_something_that_is_not_an_image_is_refused_whatever_it_claims() -> None:
    site = Site(
        {
            "/robots.txt": (404, "text/plain", b""),
            "/liar.jpg": (200, "image/jpeg", b"<html>not an image at all" + b"x" * 2000),
            "/page": (200, "text/html", b"<html>hello</html>" + b"x" * 2000),
        }
    )
    downloader = HttpImageDownloader(web(site))

    assert await downloader.download("https://cdn.example.sa/liar.jpg") is None
    assert await downloader.download("https://cdn.example.sa/page") is None


async def test_an_oversized_download_is_refused() -> None:
    site = Site(
        {
            "/robots.txt": (404, "text/plain", b""),
            "/big.jpg": (200, "image/jpeg", b"\xff\xd8\xff" + b"x" * 6_000_000),
        }
    )

    assert await HttpImageDownloader(web(site)).download("https://cdn.example.sa/big.jpg") is None


async def test_an_image_host_without_a_readable_robots_txt_still_serves_the_picture() -> None:
    # CDN buckets often answer 403 for robots.txt while serving files normally
    site = Site({"/robots.txt": (403, "text/html", b"denied"), "/i.jpg": (200, "image/jpeg", JPEG)})
    polite = web(site)

    image = await HttpImageDownloader(polite).download("https://cdn.example.net/i.jpg")

    assert image is not None
    assert polite.blocked_hosts == set()


async def test_an_image_host_that_refuses_the_picture_itself_is_still_marked_blocked() -> None:
    site = Site({"/robots.txt": (403, "text/html", b"denied"), "/i.jpg": (403, "text/html", b"no")})
    polite = web(site)

    assert await HttpImageDownloader(polite).download("https://cdn.example.net/i.jpg") is None
    assert polite.blocked_hosts == {"cdn.example.net"}


async def test_an_image_host_whose_robots_txt_forbids_the_picture_is_obeyed() -> None:
    site = Site(
        {
            "/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /i.jpg\n"),
            "/i.jpg": (200, "image/jpeg", JPEG),
        }
    )

    assert await HttpImageDownloader(web(site)).download("https://cdn.example.net/i.jpg") is None
    assert "/i.jpg" not in site.requests


async def test_each_host_has_its_own_pace_so_different_sites_never_wait_for_each_other() -> None:
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    clock = {"now": 100.0}
    site = Site({"/robots.txt": (404, "text/plain", b""), "/p": html("<html></html>")})
    client = httpx.AsyncClient(transport=httpx.MockTransport(site))
    polite = PoliteWeb(
        client,
        lambda: Throttle(2.0, now=lambda: clock["now"], sleep=record_sleep),
        user_agent="test-agent",
    )

    await polite.get("https://a.example.sa/p")  # robots.txt then the page: the second one waits
    waited_on_a = len(slept)
    await polite.get("https://b.example.sa/p")  # a new host starts fresh: its first request is free
    first_request_to_b = len(slept)

    assert waited_on_a == 1
    assert first_request_to_b == 2  # only b's second request (its page after robots.txt) waited
