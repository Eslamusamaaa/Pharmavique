"""Scratch: recall of the in-memory index on generated misspellings of real drug names."""

import asyncio
import json
import random
from pathlib import Path

from pharmavique.media.domain.matching import core_name
from pharmavique.search.domain.documents import ProductKey, ProductToIndex, SearchDocument, build_document
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.text import normalize_text

random.seed(5)
rows = [json.loads(line) for line in open("data/media/products.jsonl", encoding="utf-8")]


def to_doc(row: dict, with_core: bool) -> SearchDocument:
    product = ProductToIndex(
        key=ProductKey(Market.SA, row["register_number"]),
        trade_name_en=row["trade_name_en"],
        trade_name_ar=row["trade_name_ar"],
        ingredient_names=tuple(i["name"] for i in row["ingredients"]),
        marketing_company=row["company"],
        withdrawn=False,
    )
    doc = build_document(product)
    if with_core:
        cores = [normalize_text(core_name(row["trade_name_en"])), normalize_text(core_name(row["trade_name_ar"]))]
        extra = tuple(c for c in cores if c and c not in doc.names)
        doc = SearchDocument(doc.key, doc.names + extra, doc.ingredients, doc.company, doc.withdrawn)
    return doc


def typo(word: str) -> str:
    kind = random.choice(["drop", "swap", "vowel"])
    if len(word) < 5:
        return word
    i = random.randrange(1, len(word) - 2)
    if kind == "drop":
        return word[:i] + word[i + 1 :]
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    vowels = "aeiou"
    return word[:i] + (random.choice([v for v in vowels if v != word[i]]) if word[i] in vowels else word[i]) + word[i + 1 :]


async def main() -> None:
    family: dict[str, set[str]] = {}
    for row in rows:
        family.setdefault(normalize_text(core_name(row["trade_name_en"])), set()).add(row["register_number"])
    sample = [r for r in rows if r["trade_name_en"] and len(normalize_text(core_name(r["trade_name_en"]))) >= 6]
    sample = random.sample(sample, 300)
    cases = []
    for r in sample:
        base = core_name(r["trade_name_en"])
        words = base.split()
        broken = " ".join(typo(w) if idx == 0 else w for idx, w in enumerate(words))
        cases.append((broken, normalize_text(base)))

    for label, with_core in (("current (full names only)", False), ("with core brand names added", True)):
        index = InMemorySearchIndex()
        await index.upsert([to_doc(r, with_core) for r in rows])
        hits = {1: 0, 3: 0, 10: 0}
        for query, core in cases:
            found = await index.find_similar(Market.SA, normalize_text(query), 10, 0.2, False)
            keys = [h.key.register_number for h in found]
            for k in hits:
                if any(key in family[core] for key in keys[:k]):
                    hits[k] += 1
        n = len(cases)
        print(f"{label}: recall@1={hits[1]/n:.0%} recall@3={hits[3]/n:.0%} recall@10={hits[10]/n:.0%} ({n} queries)")


asyncio.run(main())
