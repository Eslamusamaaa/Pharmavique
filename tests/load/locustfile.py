"""Locust scenarios for search, the drug page and the assistant (Phase 0, item 9).

Run against the real API with the fake assistant (`fake_assistant_server.py`), never against
production, and never with a real model: a free quota is shared by everyone.

    uv run --group load locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 60s \
        --host http://127.0.0.1:8010 --csv data/loadtest/run

No target is assumed: the numbers are baselines to compare with later runs (docs/PERFORMANCE.md).
The assistant needs an account while `login_for_ai` is on, so each simulated user signs a token with
`PHARMAVIQUE_JWT_SECRET` from the environment or `.env`; a missing secret stops the run.
"""

import random
from datetime import UTC, datetime
from uuid import uuid4

from locust import HttpUser, between, events, task

from pharmavique.bootstrap.settings import get_settings
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.principal import Principal, Role

SEARCH_TERMS = (
    "panadol", "paracetamol", "augmentin", "amoxicillin", "brufen", "ibuprofen", "voltaren",
    "concor", "glucophage", "metformin", "lipitor", "atorvastatin", "nexium", "omeprazole",
    "بانادول", "باراسيتامول", "اوجمنتين", "بروفين", "pana", "amox", "omepra",
)  # fmt: skip
QUESTIONS = (
    "ما استخدامات هذا الدواء؟",
    "هل له بدائل بنفس المادة الفعالة؟",
    "ما شكل الدواء وتركيزه؟",
)

_registers: list[str] = []


def _tokens() -> JwtAccessTokens:
    secret = get_settings().jwt_secret
    if secret is None:
        raise SystemExit("set PHARMAVIQUE_JWT_SECRET: the assistant needs a signed-in user")
    return JwtAccessTokens(secret.get_secret_value())


@events.test_start.add_listener
def _check_secret(environment: object, **kwargs: object) -> None:
    _tokens()


class Reader(HttpUser):
    """People looking medicines up: mostly searches, some drug pages. No account."""

    weight = 8
    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        if not _registers:
            found = self.client.get("/v1/search", params={"q": "panadol", "limit": 20}).json()
            _registers.extend(hit["register_number"] for hit in found["results"])

    @task(5)
    def search(self) -> None:
        self.client.get(
            "/v1/search",
            params={"q": random.choice(SEARCH_TERMS), "limit": 10},  # noqa: S311
            name="/v1/search",
        )

    @task(2)
    def drug_page(self) -> None:
        if _registers:
            register = random.choice(_registers)  # noqa: S311
            self.client.get(f"/v1/products/{register}/details", name="/v1/products/{id}/details")


class Asker(HttpUser):
    """Signed-in people asking the assistant (answered by the fake model)."""

    weight = 2
    wait_time = between(2, 6)

    def on_start(self) -> None:
        principal = Principal(uuid4(), None, frozenset({Role.PATIENT}))
        token, _ = _tokens().issue(principal, datetime.now(UTC))
        self.client.headers["Authorization"] = f"Bearer {token}"

    @task
    def ask(self) -> None:
        body = {"question": random.choice(QUESTIONS), "level": "patient"}  # noqa: S311
        with self.client.post("/v1/assistant/ask", json=body, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")
            elif "error" in response.json():
                response.failure("the answer came back as a late error")
