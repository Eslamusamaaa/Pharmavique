"""Trigram similarity, computed the way PostgreSQL's pg_trgm does it.

Having it in plain Python lets ranking be tested, tuned and evaluated without a database, and it
is the reference the Postgres adapter is checked against (spike 001 measured 0.70 for
panadol/panadool and 0.50 for the Arabic pair). Input is expected to be normalized text
(`shared_kernel.text.normalize_text`), so words are separated by single spaces.
"""


def trigrams(text: str) -> frozenset[str]:
    """Each word is padded with two spaces before and one after, then cut into 3-letter pieces."""
    found: set[str] = set()
    for word in text.split():
        padded = f"  {word} "
        found.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return frozenset(found)


def similarity(a: str, b: str) -> float:
    """Shared trigrams over all trigrams: 1.0 for identical text, 0.0 for nothing in common."""
    first, second = trigrams(a), trigrams(b)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)
