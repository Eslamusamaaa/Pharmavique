"""Everything the product imports must come from the runtime dependencies, not the dev group.

A hosting platform (Vercel, the Docker image) installs only `[project].dependencies`. A package that
is imported by product code but is declared in the dev group alone imports fine on a developer's
machine and fails at start-up there (Pillow did: `ModuleNotFoundError: No module named 'PIL'`).
"""

import ast
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _runtime_closure() -> set[str]:
    """The declared runtime dependencies and everything they pull in (roots' extras included)."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pending = [Requirement(spec) for spec in pyproject["project"]["dependencies"]]
    seen: set[str] = set()
    while pending:
        requirement = pending.pop()
        name = _normal(requirement.name)
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(requirement.name) or []
        except metadata.PackageNotFoundError:
            continue
        extras = {"", *requirement.extras}
        for line in requires:
            child = Requirement(line)
            if child.marker is None or any(child.marker.evaluate({"extra": e}) for e in extras):
                pending.append(child)
    return seen


def _imported_top_level_modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for file in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], file)
    return found


def test_every_third_party_import_in_product_code_is_a_runtime_dependency() -> None:
    closure = _runtime_closure()
    distributions = metadata.packages_distributions()
    missing: list[str] = []
    for module, file in sorted(_imported_top_level_modules().items()):
        if module == "pharmavique" or module in sys.stdlib_module_names:
            continue
        providers = {_normal(name) for name in distributions.get(module, [])}
        if not providers:
            missing.append(f"{module} (imported in {file.relative_to(ROOT)}; not installed at all)")
        elif not providers & closure:
            missing.append(
                f"{module} (imported in {file.relative_to(ROOT)}; only {sorted(providers)}, "
                "which is not a runtime dependency)"
            )
    assert not missing, "add to [project].dependencies in pyproject.toml: " + "; ".join(missing)
