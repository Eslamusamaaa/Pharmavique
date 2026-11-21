"""Measure the read API under load and print what was measured (no targets are assumed).

    uv run python scripts/loadtest.py --base-url http://127.0.0.1:8010 --scenario mixed \
        --concurrency 50 --seconds 30

Scenarios: `search` (names people type), `page` (the drug page), `mixed` (searches and pages).
Each virtual user sends one request at a time and starts the next as soon as it gets an answer.
A short warm-up discovers real register numbers through the API and is not counted.

The numbers describe one machine, one network path and this load generator running next to the
server; they are baselines to compare against later runs, not capacity claims. Start the API with
the rate limits off (`PHARMAVIQUE_RATE_LIMIT_PER_MINUTE=0`), or the limiter answers 429.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx

SEARCH_TERMS = (
    "panadol", "paracetamol", "augmentin", "amoxicillin", "brufen", "ibuprofen", "voltaren",
    "concor", "glucophage", "metformin", "lipitor", "atorvastatin", "nexium", "omeprazole",
    "ventolin", "salbutamol", "zyrtec", "cetirizine", "aspirin", "insulin", "warfarin",
    "بانادول", "باراسيتامول", "اوجمنتين", "بروفين", "فولتارين", "جلوكوفاج", "فنتولين",
    "pana", "amox", "omepra", "cetiri",  # prefixes and half-typed names
)  # fmt: skip


@dataclass
class Result:
    latencies: list[float] = field(default_factory=list)
    statuses: Counter[str] = field(default_factory=Counter)
    cache: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)


async def discover(client: httpx.AsyncClient, base: str) -> list[str]:
    numbers: list[str] = []
    for term in SEARCH_TERMS[:12]:
        response = await client.get(f"{base}/v1/search", params={"q": term, "limit": 20})
        if response.status_code == 200:
            numbers.extend(hit["register_number"] for hit in response.json()["results"])
    return sorted(set(numbers))


def pick(scenario: str, numbers: list[str], rng: random.Random) -> tuple[str, dict[str, str]]:
    if scenario == "page" or (scenario == "mixed" and rng.random() < 0.4):
        return f"/v1/products/{rng.choice(numbers)}/details", {}
    return "/v1/search", {"q": rng.choice(SEARCH_TERMS), "limit": "10"}


async def user(
    client: httpx.AsyncClient,
    base: str,
    scenario: str,
    numbers: list[str],
    stop_at: float,
    out: Result,
    seed: int,
) -> None:
    rng = random.Random(seed)  # noqa: S311 - picks test requests, nothing secret
    while time.perf_counter() < stop_at:
        path, params = pick(scenario, numbers, rng)
        started = time.perf_counter()
        try:
            response = await client.get(f"{base}{path}", params=params)
        except httpx.HTTPError as error:
            out.errors[type(error).__name__] += 1
            continue
        out.latencies.append((time.perf_counter() - started) * 1000)
        out.statuses[str(response.status_code)] += 1
        out.cache[response.headers.get("x-cache", "none")] += 1


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, max(0, round(p / 100 * len(sorted_values)) - 1))
    return sorted_values[index]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--scenario", choices=("search", "page", "mixed"), default="mixed")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="print the result as one JSON line")
    args = parser.parse_args()

    limits = httpx.Limits(
        max_connections=args.concurrency + 5, max_keepalive_connections=args.concurrency + 5
    )
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        numbers = await discover(client, args.base_url)
        if not numbers:
            raise SystemExit("could not discover any drug: is the API up and the catalog loaded?")
        out = Result()
        stop_at = time.perf_counter() + args.seconds
        started = time.perf_counter()
        await asyncio.gather(
            *(
                user(client, args.base_url, args.scenario, numbers, stop_at, out, seed)
                for seed in range(args.concurrency)
            )
        )
        elapsed = time.perf_counter() - started

    values = sorted(out.latencies)
    summary = {
        "scenario": args.scenario,
        "concurrency": args.concurrency,
        "seconds": round(elapsed, 1),
        "requests": len(values),
        "requests_per_second": round(len(values) / elapsed, 1),
        "latency_ms": {
            "mean": round(statistics.fmean(values), 1) if values else None,
            "p50": round(percentile(values, 50), 1),
            "p95": round(percentile(values, 95), 1),
            "p99": round(percentile(values, 99), 1),
            "max": round(values[-1], 1) if values else None,
        },
        "statuses": dict(out.statuses),
        "x_cache": dict(out.cache),
        "transport_errors": dict(out.errors),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
        return
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
