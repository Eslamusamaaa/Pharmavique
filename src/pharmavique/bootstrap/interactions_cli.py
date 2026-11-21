"""`pharmavique interactions-load`: put DDInter's downloaded files into the interactions schema."""

import argparse
import asyncio
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.interactions.domain.records import ContraindicationRecord, InteractionRecord
from pharmavique.interactions.infrastructure.ddinter import SOURCE, read_ddinter
from pharmavique.interactions.infrastructure.medic import SOURCE as MEDIC_SOURCE
from pharmavique.interactions.infrastructure.medic import read_contraindications
from pharmavique.interactions.infrastructure.postgres import (
    PostgresContraindicationStore,
    PostgresInteractionStore,
)

EXIT_OK = 0
EXIT_NO_DATABASE = 4
EXIT_NO_INPUT = 5
DDINTER_PAGE = "https://ddinter2.scbdd.com/download/"


def add_arguments(commands: Any) -> None:
    load = commands.add_parser(
        "interactions-load",
        help="load DDInter's downloaded interaction files into the database (safe to repeat)",
    )
    load.add_argument("--folder", default="data/interactions/ddinter")
    medic = commands.add_parser(
        "interactions-load-medic",
        help="load MeDIC's contraindication list (drug-disease) into the database (safe to repeat)",
    )
    medic.add_argument("--file", default="data/interactions/medic/contraindicationList.xlsx")


def _snapshot_id(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.glob("*.csv")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"ddinter-{digest.hexdigest()[:12]}"


def _read(folder: Path) -> tuple[list[InteractionRecord], str] | None:
    """The records and the snapshot id of the files in `folder`, or None when there are none."""
    if not any(folder.glob("*.csv")):
        return None
    return read_ddinter(folder), _snapshot_id(folder)


async def load(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    read = await asyncio.to_thread(_read, folder)
    if read is None:
        print(f"no DDInter CSV files in {folder}", file=sys.stderr)
        return EXIT_NO_INPUT
    records, snapshot_id = read
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(secret.get_secret_value())
    try:
        await PostgresInteractionStore(create_session_factory(engine)).replace_source(
            SOURCE,
            records,
            source_ref=DDINTER_PAGE,
            snapshot_id=snapshot_id,
            fetched_at=datetime.now(UTC),
            trust="unofficial_unverified",
        )
    finally:
        await engine.dispose()
    print(f"{SOURCE}: {len(records)} interaction pairs loaded")
    return EXIT_OK


MEDIC_PAGE = "https://medic.renci.org/"


def _read_medic(path: Path) -> tuple[list[ContraindicationRecord], str] | None:
    if not path.exists():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return read_contraindications(path), f"medic-{digest}"


async def load_medic(args: argparse.Namespace) -> int:
    path = Path(args.file)
    read = await asyncio.to_thread(_read_medic, path)
    if read is None:
        print(f"no MeDIC file at {path}", file=sys.stderr)
        return EXIT_NO_INPUT
    records, snapshot_id = read
    secret = get_settings().database_url
    if secret is None:
        print("set PHARMAVIQUE_DATABASE_URL (see .env.example)", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(secret.get_secret_value())
    try:
        await PostgresContraindicationStore(create_session_factory(engine)).replace_source(
            MEDIC_SOURCE,
            records,
            source_ref=MEDIC_PAGE,
            snapshot_id=snapshot_id,
            fetched_at=datetime.now(UTC),
            trust="unofficial_unverified",
        )
    finally:
        await engine.dispose()
    print(f"{MEDIC_SOURCE}: {len(records)} drug-disease contraindications loaded")
    return EXIT_OK
