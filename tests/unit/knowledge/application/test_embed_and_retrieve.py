"""Embedding stored chunks and retrieving cited passages (hybrid: vectors + text), with fakes."""

from collections.abc import Sequence

from pharmavique.knowledge.application.embed_chunks import EmbedChunks
from pharmavique.knowledge.application.retrieve import RetrievePassages
from pharmavique.knowledge.domain.retrieval import Passage


class FakeEmbedder:
    model = "fake-embed"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


class FakeVectors:
    def __init__(self, missing: list[tuple[str, str]]) -> None:
        self.pending = list(missing)
        self.saved: dict[str, list[float]] = {}

    async def missing(self, model: str, limit: int) -> list[tuple[str, str]]:
        return [p for p in self.pending if p[0] not in self.saved][:limit]

    async def save(self, model: str, vectors: Sequence[tuple[str, list[float]]]) -> None:
        self.saved.update(dict(vectors))


def passage(chunk_id: str, text: str = "text") -> Passage:
    return Passage(
        chunk_id=chunk_id,
        list_name="dhpc",
        title=f"title {chunk_id}",
        text=text,
        source_ref=f"https://www.sfda.gov.sa/{chunk_id}",
        published="2026-10-01",
        register_numbers=("1-1",),
        ocr=False,
    )


class FakeSearch:
    def __init__(self, by_vector: list[Passage], by_text: list[Passage]) -> None:
        self.vector_hits = by_vector
        self.text_hits = by_text
        self.filters: list[tuple[str, ...]] = []

    async def by_vector(
        self, model: str, vector: list[float], register_numbers: Sequence[str], limit: int
    ) -> list[Passage]:
        self.filters.append(tuple(register_numbers))
        return self.vector_hits[:limit]

    async def by_text(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[Passage]:
        return self.text_hits[:limit]


async def test_only_chunks_without_a_vector_for_the_model_are_embedded_in_batches() -> None:
    vectors = FakeVectors([("a", "one"), ("b", "two"), ("c", "three")])
    embedder = FakeEmbedder()

    report = await EmbedChunks(vectors, embedder, batch_size=2).run()

    assert report.embedded == 3
    assert embedder.calls == [["one", "two"], ["three"]]
    assert vectors.saved["c"] == [5.0, 1.0]


async def test_an_embedding_failure_stops_and_reports_what_was_done() -> None:
    class Failing(FakeEmbedder):
        async def embed(self, texts: Sequence[str]) -> list[list[float]]:
            if len(self.calls) == 1:
                raise RuntimeError("HTTP 504")
            return await super().embed(texts)

    vectors = FakeVectors([("a", "one"), ("b", "two")])

    report = await EmbedChunks(vectors, Failing(), batch_size=1).run()

    assert report.embedded == 1
    assert report.stopped_by == "HTTP 504"


async def test_passages_found_by_both_signals_rank_first() -> None:
    search = FakeSearch(
        by_vector=[passage("v1"), passage("both")], by_text=[passage("both"), passage("t1")]
    )

    found = await RetrievePassages(search, FakeEmbedder()).search("warning", limit=3)

    assert [p.chunk_id for p in found] == ["both", "v1", "t1"]


async def test_retrieval_works_on_text_alone_when_no_embedder_is_configured() -> None:
    search = FakeSearch(by_vector=[], by_text=[passage("t1")])

    found = await RetrievePassages(search, None).search("warning", limit=3)

    assert [p.chunk_id for p in found] == ["t1"]


async def test_a_failing_embedder_falls_back_to_text_search() -> None:
    class Down(FakeEmbedder):
        async def embed(self, texts: Sequence[str]) -> list[list[float]]:
            raise RuntimeError("down")

    search = FakeSearch(by_vector=[passage("v1")], by_text=[passage("t1")])

    found = await RetrievePassages(search, Down()).search("warning", limit=3)

    assert [p.chunk_id for p in found] == ["t1"]


async def test_passages_can_be_limited_to_a_product() -> None:
    search = FakeSearch(by_vector=[passage("v1")], by_text=[])

    await RetrievePassages(search, FakeEmbedder()).search("x", register_numbers=["1-1"], limit=2)

    assert search.filters == [("1-1",)]
