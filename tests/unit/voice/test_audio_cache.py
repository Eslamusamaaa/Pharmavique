"""The short-lived audio store: one read, expiry, and a size cap."""

from pharmavique.voice.infrastructure.audio_cache import AudioCache


def test_audio_is_served_once() -> None:
    cache = AudioCache(ttl_seconds=60, now=lambda: 0.0)
    key = cache.put(b"mp3", "audio/mpeg")

    assert cache.take(key) == (b"mp3", "audio/mpeg")
    assert cache.take(key) is None


def test_expired_audio_is_gone() -> None:
    clock = [0.0]
    cache = AudioCache(ttl_seconds=60, now=lambda: clock[0])
    key = cache.put(b"mp3", "audio/mpeg")
    clock[0] = 61.0

    assert cache.take(key) is None


def test_the_oldest_entries_are_dropped_beyond_the_cap() -> None:
    cache = AudioCache(ttl_seconds=60, max_items=2, now=lambda: 0.0)
    first = cache.put(b"1", "audio/mpeg")
    cache.put(b"2", "audio/mpeg")
    cache.put(b"3", "audio/mpeg")

    assert cache.take(first) is None


def test_keys_are_long_and_random() -> None:
    cache = AudioCache(ttl_seconds=60, now=lambda: 0.0)

    keys = {cache.put(b"x", "audio/mpeg") for _ in range(50)}

    assert len(keys) == 50
    assert all(len(k) >= 32 for k in keys)
