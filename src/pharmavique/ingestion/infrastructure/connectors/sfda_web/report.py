"""Human and machine readable reports of what changed between two runs."""

from collections.abc import Mapping
from typing import Any

from pharmavique.ingestion.domain.records import ChangeSet, FieldChange

_PRICE_FIELDS = frozenset({"list.price", "en.Price", "ar.السعر"})


def _name(names: Mapping[str, str], key: str) -> str:
    return names.get(key, "")


def changes_to_json(
    result: ChangeSet, names: Mapping[str, str], *, old_run: str, new_run: str
) -> dict[str, Any]:
    return {
        "old_run": old_run,
        "new_run": new_run,
        "counts": result.counts(),
        "added": [{"key": r.key, "trade_name": _name(names, r.key)} for r in result.added],
        "removed": [{"key": r.key, "trade_name": _name(names, r.key)} for r in result.removed],
        "changed": [
            {
                "key": c.key,
                "trade_name": _name(names, c.key),
                "changes": [{"field": f.field, "old": f.old, "new": f.new} for f in c.changes],
            }
            for c in result.changed
        ],
    }


def _is_price(change: FieldChange) -> bool:
    return change.field in _PRICE_FIELDS


def render_markdown(
    result: ChangeSet,
    names: Mapping[str, str],
    *,
    old_run: str,
    new_run: str,
    limit: int = 200,
) -> str:
    lines = [f"# SFDA changes: {old_run} -> {new_run}", ""]
    counts = result.counts()
    if result.is_empty:
        lines.append("No changes.")
        return "\n".join(lines) + "\n"

    lines.append(
        f"{counts['added']} added, {counts['removed']} removed, {counts['changed']} changed."
    )

    def section(title: str, rows: list[str]) -> None:
        if not rows:
            return
        lines.extend(["", f"## {title} ({len(rows)})", ""])
        lines.extend(rows[:limit])
        if len(rows) > limit:
            lines.append(f"... and {len(rows) - limit} more (see changes.json)")

    price_rows = []
    for change in result.changed:
        for item in change.changes:
            if _is_price(item) and item.field == "list.price":
                label = f"- {change.key} {_name(names, change.key)}: {item.old} -> {item.new}"
                price_rows.append(label)
    section("Price changes", price_rows)
    section("Added", [f"- {r.key} {_name(names, r.key)}" for r in result.added])
    section("Removed from the list", [f"- {r.key} {_name(names, r.key)}" for r in result.removed])

    other_rows = []
    for change in result.changed:
        details = "; ".join(
            f"{item.field}: {item.old!r} -> {item.new!r}"
            for item in change.changes
            if item.field != "list.price"
        )
        if details:
            other_rows.append(f"- {change.key} {_name(names, change.key)}: {details}")
    section("Other field changes", other_rows)
    return "\n".join(lines) + "\n"
