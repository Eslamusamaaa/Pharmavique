"""`pharmavique knowledge-labels`: US label interaction text for our ingredients, as cited chunks.

For every ingredient of our catalog that the interaction source knows, ask openFDA for the
drug-interactions section of one single-ingredient label, keep the answer under
`data/knowledge/openfda-interactions/` and cut it into chunks the assistant can quote with the
DailyMed page as its source. Safe to repeat: ingredients already saved are not asked again.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.interactions.domain.names import base_key, candidate_keys
from pharmavique.interactions.infrastructure.postgres import PostgresInteractionStore
from pharmavique.knowledge.domain.chunks import SourceDocument, chunk_document
from pharmavique.knowledge.infrastructure.openfda import OpenFdaLabels
from pharmavique.knowledge.infrastructure.postgres import PostgresChunkStore
from pharmavique.shared_kernel.market import Market

EXIT_OK = 0
EXIT_NO_DATABASE = 4
LABELS_LIST = "us-labels"
OLD_LABELS_LIST = "label-interactions"
USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled)"

SECTION_TITLES = {
    "drug_interactions": "drug interactions",
    "contraindications": "contraindications",
    "pregnancy": "pregnancy",
    "nursing_mothers": "nursing mothers",
    "lactation": "lactation",
    "information_for_patients": "information for patients",
}

Registers = dict[str, tuple[str, set[str]]]  # base key -> (a registry spelling, register numbers)


def add_arguments(commands: Any) -> None:
    labels = commands.add_parser(
        "knowledge-labels",
        help="fetch US label interaction text for our ingredients and chunk it (safe to repeat)",
    )
    labels.add_argument("--out", default="data/knowledge/openfda-labels")
    labels.add_argument("--delay", type=float, default=0.6, help="seconds between requests")
    labels.add_argument("--limit", type=int, help="fetch at most N ingredients (for a trial)")


async def _ingredient_registers(engine: Any) -> Registers:
    reader = ReadProductCardsHandler(SqlAlchemyProductReader(create_session_factory(engine)))
    found: Registers = {}
    after: str | None = None
    while True:
        page = await reader.export_cards(Market.SA, after, 5_000)
        for card in page.cards:
            for name in card.ingredient_names:
                key = base_key(name)
                if key:
                    found.setdefault(key, (name, set()))[1].add(card.register_number)
        if page.next_after is None:
            return found
        after = page.next_after


def _cache_path(folder: Path, key: str) -> Path:
    return folder / (key.replace(" ", "-") + ".json")


def _documents(folder: Path, by_key: Registers) -> list[SourceDocument]:
    documents = []
    for path in sorted(folder.glob("*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        label = saved["label"]
        if label is None or saved["key"] not in by_key:
            continue
        parts = {"drug_interactions": label["text"], **label.get("sections", {})}
        for field, body in parts.items():
            documents.append(
                SourceDocument(
                    list_name=LABELS_LIST,
                    row_key=f"{saved['key']}:{field}",
                    title=f"{label['generic_name']}: {SECTION_TITLES[field]} (US label, DailyMed)",
                    text=body,
                    source_ref=label["source_ref"],
                    snapshot_id=f"openfda-{label['effective_time'] or label['set_id']}",
                    fetched_at=label["fetched_at"],
                    trust="unofficial_unverified",
                    published=label["effective_time"],
                    register_numbers=tuple(sorted(by_key[saved["key"]][1])),
                )
            )
    return documents


async def _fetch_missing(wanted: list[str], folder: Path, delay: float) -> int:
    fetched = 0
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=60) as client:
        source = OpenFdaLabels(client, delay)
        for key in wanted:
            path = _cache_path(folder, key)
            if path.exists():
                continue
            label = await source.interactions_for(key)
            record = (
                None
                if label is None
                else {
                    "generic_name": label.generic_name,
                    "set_id": label.set_id,
                    "effective_time": label.effective_time,
                    "text": label.text,
                    "sections": dict(label.sections),
                    "source_ref": label.source_ref,
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
            )
            body = json.dumps({"key": key, "label": record}, ensure_ascii=False)
            await asyncio.to_thread(path.write_text, body, "utf-8")
            fetched += 1
    return fetched


async def labels(args: argparse.Namespace) -> int:
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    folder = Path(args.out)
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    engine = create_engine(secret.get_secret_value())
    try:
        session_factory = create_session_factory(engine)
        by_key = await _ingredient_registers(engine)
        every_candidate = {c for name, _ in by_key.values() for c in candidate_keys(name)}
        known = await PostgresInteractionStore(session_factory).known(every_candidate)
        wanted = sorted(k for k in by_key if set(candidate_keys(by_key[k][0])) & known)
        if args.limit:
            wanted = wanted[: args.limit]
        fetched = await _fetch_missing(wanted, folder, args.delay)
        documents = await asyncio.to_thread(_documents, folder, by_key)
        chunks = [chunk for document in documents for chunk in chunk_document(document)]
        chunk_store = PostgresChunkStore(session_factory)
        await chunk_store.replace(OLD_LABELS_LIST, [])  # the interactions-only chunks of before
        await chunk_store.replace(LABELS_LIST, chunks)
    finally:
        await engine.dispose()
    print(
        f"{len(wanted)} ingredients wanted, {fetched} fetched now, {len(documents)} labels with "
        f"an interactions section, {len(chunks)} chunks"
    )
    return EXIT_OK
