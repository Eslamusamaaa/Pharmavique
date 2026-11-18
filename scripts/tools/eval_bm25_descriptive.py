"""Scratch: does a BM25 signal help descriptive queries ("ibuprofen tablet") over trigram alone?"""

import asyncio
import json
import math
import random
from collections import Counter, defaultdict

from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.search.domain.fusion import SignalHit, fuse
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text
from pharmavique.media.domain.placeholders import form_group

random.seed(3)
rows = [json.loads(line) for line in open("data/media/products.jsonl", encoding="utf-8")]


class Bm25:
    def __init__(self, docs: dict[str, list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = {k: Counter(v) for k, v in docs.items()}
        self.len = {k: len(v) for k, v in docs.items()}
        self.avg = sum(self.len.values()) / len(self.len)
        self.df: Counter[str] = Counter()
        for counts in self.docs.values():
            self.df.update(counts.keys())
        self.n = len(docs)
        self.postings: dict[str, list[str]] = defaultdict(list)
        for k, counts in self.docs.items():
            for t in counts:
                self.postings[t].append(k)

    def search(self, query: list[str], limit: int) -> list[tuple[str, float]]:
        scores: Counter[str] = Counter()
        for t in set(query):
            if t not in self.df:
                continue
            idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            for k in self.postings[t]:
                tf = self.docs[k][t]
                scores[k] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.len[k] / self.avg))
        return scores.most_common(limit)


def profile(row: dict) -> list[str]:
    parts = [row["trade_name_en"] or "", row["dosage_form_en"] or "", " ".join(i["name"] for i in row["ingredients"])]
    return normalize_text(" ".join(parts)).split()


async def main() -> None:
    index = InMemorySearchIndex()
    await index.upsert(
        [
            build_document(
                ProductToIndex(ProductKey(Market.SA, r["register_number"]), r["trade_name_en"], r["trade_name_ar"], tuple(i["name"] for i in r["ingredients"]), r["company"], False)
            )
            for r in rows
        ]
    )
    bm = Bm25({r["register_number"]: profile(r) for r in rows})
    single = [r for r in rows if len(r["ingredients"]) == 1 and r["dosage_form_en"]]
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in single:
        by_key[(normalize_text(r["ingredients"][0]["name"]), form_group(r["dosage_form_en"]))].add(r["register_number"])
    form_word = {"tablet": "tablet", "capsule": "capsule", "liquid": "syrup", "injection": "injection", "topical": "cream", "drops": "drops"}
    cases = []
    for (ingredient, group), members in by_key.items():
        if group in form_word and len(members) >= 3 and len(ingredient) >= 6:
            cases.append((f"{ingredient} {form_word[group]}", members))
    random.shuffle(cases)
    cases = cases[:200]

    def score(results: list[str], relevant: set[str]) -> tuple[float, float]:
        top = results[:5]
        return (sum(1 for k in top if k in relevant) / 5, 1.0 if any(k in relevant for k in top) else 0.0)

    totals = {"trigram": [0.0, 0.0], "bm25": [0.0, 0.0], "fusion": [0.0, 0.0]}
    for query, relevant in cases:
        tri = [h.key.register_number for h in await index.find_similar(Market.SA, query, 20, 0.1, False)]
        lex = [k for k, _ in bm.search(query.split(), 20)]
        fused = [
            r.key
            for r in fuse(
                [
                    [SignalHit("fuzzy", k, i, 0.0) for i, k in enumerate(tri, 1)],
                    [SignalHit("lexical", k, i, 0.0) for i, k in enumerate(lex, 1)],
                ]
            )
        ]
        for name, res in (("trigram", tri), ("bm25", lex), ("fusion", fused)):
            p, h = score(res, relevant)
            totals[name][0] += p
            totals[name][1] += h
    n = len(cases)
    print(f"{n} descriptive queries such as {cases[0][0]!r}, {cases[1][0]!r}")
    for name, (p, h) in totals.items():
        print(f"{name:8} precision@5={p/n:.0%}  hit@5={h/n:.0%}")


asyncio.run(main())
