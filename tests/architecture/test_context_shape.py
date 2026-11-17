"""Shape tests: rules import-linter cannot express (see docs/REPOSITORY_STRUCTURE.md section 3)."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "pharmavique"

CONTEXTS = {
    "catalog",
    "ingestion",
    "search",
    "substitution",
    "recognition",
    "knowledge",
    "media",
    "identity",
    "watchlist",
    "analytics",
}
NON_CONTEXT_PACKAGES = {"shared_kernel", "foundation", "bootstrap"}
CONTEXT_PACKAGES = {"contracts", "domain", "application", "infrastructure", "presentation"}


def _package_dirs() -> set[str]:
    return {p.name for p in PACKAGE.iterdir() if p.is_dir() and (p / "__init__.py").exists()}


def test_top_level_packages_are_exactly_contexts_plus_technical_packages() -> None:
    assert _package_dirs() == CONTEXTS | NON_CONTEXT_PACKAGES


@pytest.mark.parametrize("context", sorted(CONTEXTS))
def test_every_context_has_the_same_five_packages(context: str) -> None:
    present = {
        p.name for p in (PACKAGE / context).iterdir() if p.is_dir() and (p / "__init__.py").exists()
    }
    assert present == CONTEXT_PACKAGES


def test_every_context_is_covered_by_the_layers_and_independence_contracts() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = {c["id"]: c for c in config["tool"]["importlinter"]["contracts"]}
    expected = {f"pharmavique.{c}" for c in CONTEXTS}

    assert set(contracts["onion-layers"]["containers"]) == expected
    assert set(contracts["context-independence"]["modules"]) == expected
