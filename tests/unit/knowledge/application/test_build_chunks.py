"""Building the knowledge chunks of a list: replaced as a whole, safe to repeat."""

from collections.abc import Sequence

from pharmavique.knowledge.application.build_chunks import BuildChunks, ChunkReport
from pharmavique.knowledge.domain.chunks import Chunk, SourceDocument


def doc(row_key: str, text: str, ocr: bool = False) -> SourceDocument:
    return SourceDocument(
        list_name="dhpc",
        row_key=row_key,
        title=f"title {row_key}",
        text=text,
        source_ref=f"https://x/{row_key}",
        snapshot_id="lists-1",
        fetched_at=None,
        trust="official",
        ocr=ocr,
    )


class Source:
    def __init__(self, documents: list[SourceDocument]) -> None:
        self.documents_by_list = {"dhpc": documents}

    def documents(self, list_name: str) -> list[SourceDocument]:
        return self.documents_by_list.get(list_name, [])


class Store:
    def __init__(self) -> None:
        self.saved: dict[str, list[Chunk]] = {}
        self.added: dict[str, list[Chunk]] = {}

    async def replace(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        self.saved[list_name] = list(chunks)

    async def add(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        self.added.setdefault(list_name, []).extend(chunks)

    async def row_keys(self, list_name: str) -> set[str]:
        return {c.row_key for c in self.saved.get(list_name, []) + self.added.get(list_name, [])}


async def test_every_document_of_a_list_becomes_chunks_in_the_store() -> None:
    long_text = "\n\n".join(" ".join(f"w{p}x{i}" for i in range(150)) for p in range(3))
    store = Store()
    use_case = BuildChunks(
        Source([doc("a#1", "Short letter."), doc("b#2", long_text, ocr=True)]), store
    )

    report = await use_case.run("dhpc")

    assert report == ChunkReport(
        list_name="dhpc",
        documents=2,
        empty=0,
        chunks=len(store.saved["dhpc"]),
        ocr_chunks=report.ocr_chunks,
    )
    assert report.chunks > 2
    assert report.ocr_chunks == report.chunks - 1
    assert {c.row_key for c in store.saved["dhpc"]} == {"a#1", "b#2"}


async def test_a_document_without_text_is_counted_and_skipped() -> None:
    store = Store()
    report = await BuildChunks(Source([doc("a#1", "   ")]), store).run("dhpc")
    assert report.empty == 1
    assert report.chunks == 0
    assert store.saved["dhpc"] == []  # the list is still replaced, so old chunks disappear


async def test_a_list_with_no_documents_is_replaced_by_nothing() -> None:
    store = Store()
    report = await BuildChunks(Source([]), store).run("rmm")
    assert report.documents == 0
    assert store.saved == {"rmm": []}


async def test_an_additive_build_adds_the_new_chunks_and_never_replaces_the_list() -> None:
    store = Store()
    report = await BuildChunks(Source([doc("new#1", "A new letter.")]), store).run_additive("dhpc")

    assert report.documents == 1
    assert report.chunks == 1
    assert {c.row_key for c in store.added["dhpc"]} == {"new#1"}
    assert store.saved == {}  # replace() was never called, so nothing already stored can disappear


async def test_an_additive_build_with_nothing_new_touches_nothing() -> None:
    store = Store()
    report = await BuildChunks(Source([]), store).run_additive("dhpc")

    assert report.documents == 0
    assert store.added == {}
    assert store.saved == {}
