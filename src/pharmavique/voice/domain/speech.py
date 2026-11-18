"""What gets spoken, and in which pieces.

Citation marks and links are read on screen, not aloud. The Saudi Arabic voice takes at most 200
characters per request (Groq Orpheus documentation), so text is cut at sentence ends, or between
words when one sentence is longer than that. Nothing is reworded.
"""

import re

MAX_SEGMENT = 200

_CITATIONS = re.compile(r"\s*[\[【]\d+[\]】]")
_LINKS = re.compile(r"\s*https?://\S+")
_SPACES = re.compile(r"[ \t\u00a0\u202f]+")  # spaces, tabs, no-break and narrow spaces
_SENTENCE_END = re.compile(r"(?<=[.!?؟؛\n])\s+")


def speakable(text: str) -> str:
    """The text without citation marks, links or runs of spaces."""
    text = _LINKS.sub("", _CITATIONS.sub("", text))
    return _SPACES.sub(" ", text).strip()


def _by_words(sentence: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        current = word[:limit]  # a "word" longer than the limit (a long code) is cut
    if current:
        pieces.append(current)
    return pieces


def split_for_speech(text: str, limit: int = MAX_SEGMENT) -> list[str]:
    """Segments of at most `limit` characters, cut at sentence ends where possible."""
    segments: list[str] = []
    current = ""
    for sentence in (s.strip() for s in _SENTENCE_END.split(text.strip())):
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                segments.append(current)
                current = ""
            segments.extend(_by_words(sentence, limit))
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            segments.append(current)
            current = sentence
    if current:
        segments.append(current)
    return segments
