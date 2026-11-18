"""Download the documents that rows of an SFDA list link to (the safety alerts' PDFs).

Same rules as the other crawls: robots.txt first, a polite pace, a clear User-Agent, stop at once
on 401/403/429, never keep an answer that is not a document, and a rerun skips what is stored.
Only links to documents are followed (pdf, docx, doc, jpg, png); the files are kept as they are.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import unquote, urlparse

import httpx

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import SourceBlocked

DOCUMENT_SUFFIXES = (".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png")
MAX_BYTES = 30 * 1024 * 1024
_DOCUMENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "image/",
    "application/octet-stream",
)


def is_document_link(link: str | None) -> bool:
    return bool(link) and urlparse(link or "").path.lower().endswith(DOCUMENT_SUFFIXES)


class ListFileCrawler:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        robots: RobotsPolicy,
        throttle: Throttle,
        base_url: str,
    ) -> None:
        self._client = client
        self._robots = robots
        self._throttle = throttle
        self._base_url = base_url
        self._log = logging.getLogger("sfda.list.files")

    async def run(
        self, records: list[dict[str, Any]], folder: Path, index_path: Path
    ) -> dict[str, int]:
        """Download the document of every record that links to one. Safe to repeat."""
        done, out = _open_store(folder, index_path)
        counts = {"stored_before": len(done), "downloaded": 0, "failed": 0}
        pending = [r for r in records if is_document_link(r.get("link")) and r["key"] not in done]
        with out:
            for number, record in enumerate(pending, start=1):
                url = self._url(record["link"])
                if not self._robots.allows(url):
                    raise SourceBlocked(f"robots.txt does not allow {url}")
                await self._throttle.wait()
                try:
                    response = await self._client.get(url)
                except httpx.HTTPError as exc:
                    counts["failed"] += 1
                    self._log.warning("no file for %s: %s", record["key"], exc)
                    continue
                if response.status_code in (401, 403, 429):
                    raise SourceBlocked(f"HTTP {response.status_code} for {url}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if (
                    response.status_code != 200
                    or not content_type.startswith(_DOCUMENT_TYPES)
                    or not 0 < len(response.content) <= MAX_BYTES
                ):
                    counts["failed"] += 1
                    self._log.warning(
                        "not kept for %s: HTTP %s %s",
                        record["key"],
                        response.status_code,
                        content_type,
                    )
                    continue
                digest = hashlib.sha256(response.content).hexdigest()
                suffix = Path(unquote(urlparse(url).path)).suffix.lower()
                name = f"{digest[:16]}{suffix}"
                _write_file(folder, name, response.content)
                out.write(
                    json.dumps(
                        {
                            "key": record["key"],
                            "link": record["link"],
                            "source_ref": url,
                            "file": name,
                            "sha256": digest,
                            "bytes": len(response.content),
                            "content_type": content_type,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                out.flush()
                counts["downloaded"] += 1
                if number % 25 == 0:
                    self._log.info("files %s of %s", number, len(pending))
        return counts

    def _url(self, link: str) -> str:
        return link if link.startswith("http") else f"{self._base_url}{link}"


def _open_store(folder: Path, index_path: Path) -> tuple[set[str], TextIO]:
    folder.mkdir(parents=True, exist_ok=True)
    return _stored_keys(index_path), index_path.open("a", encoding="utf-8")


def _write_file(folder: Path, name: str, content: bytes) -> None:
    (folder / name).write_bytes(content)


def _stored_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["key"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
