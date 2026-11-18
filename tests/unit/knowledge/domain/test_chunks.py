"""Chunks of official documents: deterministic, never mixing documents, always with provenance."""

import itertools

from pharmavique.knowledge.domain.chunks import SourceDocument, chunk_document


def doc(text: str, **changes: object) -> SourceDocument:
    base: dict[str, object] = {
        "list_name": "dhpc",
        "row_key": "/sites/a.pdf#1",
        "title": "Gilenya (fingolimod)",
        "text": text,
        "source_ref": "https://www.sfda.gov.sa/sites/a.pdf",
        "snapshot_id": "lists-1",
        "fetched_at": "2026-11-18T13:12:52+00:00",
        "trust": "official",
        "ocr": False,
        "published": "2021-01-10",
        "register_numbers": ("1234567890",),
    }
    base.update(changes)
    return SourceDocument(**base)  # type: ignore[arg-type]


def paragraph(word: str, words: int) -> str:
    return " ".join(f"{word}{i}" for i in range(words))


def test_a_short_document_is_one_chunk_with_its_provenance() -> None:
    chunks = chunk_document(doc("Dear Healthcare Professional,\n\nSummary of the risk."))
    assert len(chunks) == 1
    only = chunks[0]
    assert only.text == "Dear Healthcare Professional,\n\nSummary of the risk."
    assert only.position == 0
    assert only.list_name == "dhpc"
    assert only.source_ref == "https://www.sfda.gov.sa/sites/a.pdf"
    assert only.trust == "official"
    assert only.register_numbers == ("1234567890",)
    assert only.ocr is False


def test_an_empty_document_has_no_chunks() -> None:
    assert chunk_document(doc("  \n\n  ")) == ()


def test_whitespace_is_tidied_but_paragraphs_are_kept() -> None:
    chunks = chunk_document(doc("Line   one\n\n\n\n  Line two  \n"))
    assert chunks[0].text == "Line one\n\nLine two"


def test_a_long_document_is_cut_into_bounded_overlapping_chunks() -> None:
    text = "\n\n".join(paragraph(f"p{n}w", 60) for n in range(12))
    chunks = chunk_document(doc(text), size=500, overlap=100)
    assert len(chunks) > 3
    assert all(len(c.text) <= 500 for c in chunks)
    assert [c.position for c in chunks] == list(range(len(chunks)))
    for left, right in itertools.pairwise(chunks):
        assert left.text.split()[-1] in right.text  # the end of one chunk opens the next
    words = set(text.split())
    assert words <= {w for c in chunks for w in c.text.split()}  # nothing is lost


def test_paragraphs_that_fit_are_not_split() -> None:
    first, second = paragraph("a", 20), paragraph("b", 20)
    chunks = chunk_document(doc(f"{first}\n\n{second}"), size=200, overlap=40)
    assert any(c.text.startswith(first) or first in c.text for c in chunks)
    assert all(not (c.text.endswith("a5") or c.text.startswith("a6")) for c in chunks)


def test_chunk_ids_are_stable_and_change_with_text_or_document() -> None:
    same = chunk_document(doc("Some official text."))[0].chunk_id
    assert chunk_document(doc("Some official text."))[0].chunk_id == same
    assert chunk_document(doc("Other official text."))[0].chunk_id != same
    assert chunk_document(doc("Some official text.", row_key="other#2"))[0].chunk_id != same


def test_ocr_text_is_marked_on_every_chunk() -> None:
    text = "\n\n".join(paragraph("x", 80) for _ in range(4))
    chunks = chunk_document(doc(text, ocr=True), size=400, overlap=50)
    assert chunks
    assert all(c.ocr for c in chunks)
