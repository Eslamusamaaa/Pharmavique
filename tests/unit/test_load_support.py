"""The load tests' fake assistant server answers like the real contract, with no model."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

LOAD = Path(__file__).resolve().parents[1] / "load"


@pytest.fixture(scope="module")
def fake():
    spec = importlib.util.spec_from_file_location(
        "fake_assistant_server", LOAD / "fake_assistant_server.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_assistant_server"] = module
    spec.loader.exec_module(module)
    return module


async def test_the_fake_runner_answers_with_a_citation_and_never_calls_a_model(fake) -> None:
    runner = fake.FakeRunner(delay=0)

    run = await runner.run("ما استخدامات هذا الدواء؟", "patient", None)

    assert "[1]" in run.text
    assert run.citations == (fake.CITATION,)
    assert run.model == "fake-load-test-model"
    assert runner.calls == 1


async def test_the_app_swaps_only_the_assistant_after_the_real_wiring(fake) -> None:
    app = fake.build_app()
    assert isinstance(app, FastAPI)

    async with app.router.lifespan_context(app):
        assert type(app.state.assistant).__name__ == "AskAssistant"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health")).status_code == 200
