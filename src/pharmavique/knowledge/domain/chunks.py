"""Cut official documents into chunks the assistant can retrieve and cite (ADR-006).

Deterministic: the same document always gives the same chunks and ids. A chunk never mixes two
documents, keeps whole paragraphs where they fit, and carries the document's provenance, so every
quoted sentence can be traced to its official source.
"""

import hashlib
import re
from dataclasses import dataclass

DEFAULT_SIZE = 1200
DEFAULT_OVERLAP = 200

_SPACES = re.compile("[ \\t\\u00a0]+")  # spaces, tabs and no-break spaces
_BLANK_LINES = re.compile(r"\n\s*\n+")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    list_name: str
    row_key: str
    title: str
    text: str
    source_ref: str
    snapshot_id: str
    fetched_at: str | None
    trust: str
    ocr: bool = False
    published: str | None = None
    register_numbers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    list_name: str
    row_key: str
    position: int
    title: str
    text: str
    source_ref: str
    snapshot_id: str
    fetched_at: str | None
    trust: str
    ocr: bool
    published: str | None
    register_numbers: tuple[str, ...]


def tidy(text: str) -> str:
    """Collapse runs of spaces, keep paragraph breaks, drop empty lines and outer whitespace."""
    paragraphs = []
    for block in _BLANK_LINES.split(text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [_SPACES.sub(" ", line).strip() for line in block.split("\n")]
        joined = "\n".join(line for line in lines if line)
        if joined:
            paragraphs.append(joined)
    return "\n\n".join(paragraphs)


def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Split one long paragraph at word boundaries into pieces of at most `size` characters,
    each starting with about `overlap` characters of the previous one."""
    words = text.split(" ")
    pieces: list[str] = []
    start = 0
    while start < len(words):
        end = start
        length = 0
        while end < len(words) and length + len(words[end]) + (1 if end > start else 0) <= size:
            length += len(words[end]) + (1 if end > start else 0)
            end += 1
        if end == start:  # one word longer than the window: cut it
            pieces.append(words[start][:size])
            start += 1
            continue
        pieces.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        back = end
        kept = 0
        while back > start + 1 and kept + len(words[back - 1]) + 1 <= overlap:
            kept += len(words[back - 1]) + 1
            back -= 1
        start = back if back < end else end
    return pieces


def _tail(text: str, overlap: int) -> str:
    """The last whole words of `text` that fit in `overlap` characters."""
    words = text.split()
    kept: list[str] = []
    length = 0
    for word in reversed(words):
        if length + len(word) + 1 > overlap:
            break
        kept.insert(0, word)
        length += len(word) + 1
    return " ".join(kept)


def _pieces(text: str, size: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(paragraph) > size:
            if current:
                pieces.append(current)
            windows = _windows(paragraph.replace("\n", " "), size, overlap)
            pieces.extend(windows[:-1])
            current = windows[-1]
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        pieces.append(current)
        # carry the end of the previous piece, shortened so the paragraph still fits
        room = min(overlap, size - len(paragraph) - 2)
        carried = _tail(current, room) if room > 0 else ""
        current = f"{carried}\n\n{paragraph}" if carried else paragraph
    if current:
        pieces.append(current)
    return pieces


def _chunk_id(document: SourceDocument, text: str) -> str:
    material = "\x1f".join((document.list_name, document.row_key, text))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def chunk_document(
    document: SourceDocument, size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP
) -> tuple[Chunk, ...]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("size must be positive and overlap smaller than size")
    text = tidy(document.text)
    if not text:
        return ()
    return tuple(
        Chunk(
            chunk_id=_chunk_id(document, piece),
            list_name=document.list_name,
            row_key=document.row_key,
            position=position,
            title=document.title,
            text=piece,
            source_ref=document.source_ref,
            snapshot_id=document.snapshot_id,
            fetched_at=document.fetched_at,
            trust=document.trust,
            ocr=document.ocr,
            published=document.published,
            register_numbers=document.register_numbers,
        )
        for position, piece in enumerate(_pieces(text, size, overlap))
    )
