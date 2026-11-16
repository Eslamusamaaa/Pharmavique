"""On-disk snapshot of one crawl run. Plain files, written atomically, safe to resume.

Layout under `<root>/<run_id>/`:
    manifest.json                        provenance and progress of the run
    list/page-00000.json.gz              one stored list page (url, status, fetched_at, html)
    details/en/<key>.json.gz             one stored English details page
    details/ar/<key>.json.gz             one stored Arabic details page
    records.jsonl                        parsed records, built from the stored pages
"""

import gzip
import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pharmavique.ingestion.application.ports import FetchedPage


class SnapshotStore:
    def __init__(self, root: Path, run_id: str) -> None:
        self.run_id = run_id
        self.run_dir = root / run_id

    # ---- paths -------------------------------------------------------------------------------
    def list_page_path(self, page: int) -> Path:
        return self.run_dir / "list" / f"page-{page:05d}.json.gz"

    def details_path(self, language: str, key: str) -> Path:
        return self.run_dir / "details" / language / f"{quote(key, safe='')}.json.gz"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def records_path(self) -> Path:
        return self.run_dir / "records.jsonl"

    # ---- pages -------------------------------------------------------------------------------
    @staticmethod
    def has(path: Path) -> bool:
        return path.exists()

    def save_page(self, path: Path, page: FetchedPage) -> None:
        payload = {
            "url": page.url,
            "status": page.status,
            "fetched_at": page.fetched_at.isoformat(),
            "html": page.html,
        }
        self._atomic_write(path, gzip.compress(json.dumps(payload).encode("utf-8")))

    def load_page(self, path: Path) -> FetchedPage:
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        return FetchedPage(
            url=payload["url"],
            status=payload["status"],
            html=payload["html"],
            fetched_at=datetime.fromisoformat(payload["fetched_at"]),
        )

    # ---- manifest and records ----------------------------------------------------------------
    def load_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        loaded: dict[str, Any] = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return loaded

    def save_manifest(self, manifest: Mapping[str, Any]) -> None:
        text = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
        self._atomic_write(self.manifest_path, text.encode("utf-8"))

    def write_records(self, records: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        lines: list[str] = []
        for record in records:
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
            count += 1
        self._atomic_write(self.records_path, ("\n".join(lines) + "\n").encode("utf-8"))
        return count

    def read_records(self) -> list[dict[str, Any]]:
        if not self.records_path.exists():
            return []
        with self.records_path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    # ---- internals ---------------------------------------------------------------------------
    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
