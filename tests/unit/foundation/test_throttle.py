from pharmavique.foundation.http.throttle import Throttle


class FakeTime:
    """A clock whose sleep moves time forward, so tests never wait."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def read(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_first_call_does_not_wait() -> None:
    fake = FakeTime()
    throttle = Throttle(2.0, now=fake.read, sleep=fake.sleep)

    await throttle.wait()

    assert fake.sleeps == []


async def test_second_call_waits_for_the_remaining_interval() -> None:
    fake = FakeTime()
    throttle = Throttle(2.0, now=fake.read, sleep=fake.sleep)

    await throttle.wait()
    fake.now += 0.5  # the request itself took half a second
    await throttle.wait()

    assert fake.sleeps == [1.5]


async def test_no_wait_when_enough_time_already_passed() -> None:
    fake = FakeTime()
    throttle = Throttle(2.0, now=fake.read, sleep=fake.sleep)

    await throttle.wait()
    fake.now += 5.0
    await throttle.wait()

    assert fake.sleeps == []


async def test_jitter_adds_a_random_part_to_the_gap() -> None:
    fake = FakeTime()
    throttle = Throttle(2.0, jitter=1.0, now=fake.read, sleep=fake.sleep, rand=lambda: 0.5)

    await throttle.wait()
    await throttle.wait()

    assert fake.sleeps == [2.5]


def test_negative_settings_are_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="min_interval"):
        Throttle(-1.0)
    with pytest.raises(ValueError, match="jitter"):
        Throttle(1.0, jitter=-0.1)
