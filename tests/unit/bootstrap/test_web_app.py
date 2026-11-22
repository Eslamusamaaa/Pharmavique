"""The website (the Expo web export) served by the API itself, so the app and its API share one
address: no CORS, no http/https mixing, one thing to put on the phone's home screen."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.web_app import mount_web_app


@pytest.fixture
def site(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>app shell</html>", encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text('{"name": "Pharmavique"}', encoding="utf-8")
    (tmp_path / "_expo" / "static").mkdir(parents=True)
    (tmp_path / "_expo" / "static" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def client(site: Path) -> TestClient:
    app = create_app(cors_origins=[], rate_limit_per_minute=1000)
    mount_web_app(app, site)
    return TestClient(app)


def test_the_root_and_a_file_are_served(site: Path) -> None:
    web = client(site)

    assert "app shell" in web.get("/").text
    assert web.get("/manifest.webmanifest").json() == {"name": "Pharmavique"}
    assert web.get("/_expo/static/app.js").text == "console.log(1)"


def test_a_screen_address_falls_back_to_the_app_shell(site: Path) -> None:
    # the app has its own router: /drug/1-1 is a screen, not a file, and a reload must open it
    web = client(site)

    response = web.get("/drug/1-1")

    assert response.status_code == 200
    assert "app shell" in response.text


def test_the_api_keeps_its_own_routes_and_its_own_404s(site: Path) -> None:
    web = client(site)

    assert web.get("/health").json()["status"] == "ok"
    missing = web.get("/v1/nothing-here")
    assert missing.status_code == 404
    assert "app shell" not in missing.text


def test_a_missing_file_with_an_extension_is_a_404_not_the_shell(site: Path) -> None:
    web = client(site)

    assert web.get("/_expo/static/missing.js").status_code == 404
    assert web.get("/icon-nobody-made.png").status_code == 404


def test_a_missing_folder_leaves_the_api_alone(tmp_path: Path) -> None:
    app = create_app(cors_origins=[], rate_limit_per_minute=1000)

    mount_web_app(app, tmp_path / "does-not-exist")

    assert TestClient(app).get("/health").status_code == 200
    assert TestClient(app).get("/").status_code == 404
