"""The picture endpoint: real pictures from the media folder, 404 otherwise, never outside it."""

from pathlib import Path

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.api_pictures import picture_key, resolve_picture_file
from pharmavique.catalog.infrastructure.persistence.pictures import StoredPicture

JPEG = b"\xff\xd8\xff" + b"x" * 100


class FakePictures:
    def __init__(self, rows: dict[str, StoredPicture]) -> None:
        self.rows = rows

    async def find(self, market: str, register_number: str) -> StoredPicture | None:
        return self.rows.get(register_number)


def media(tmp_path: Path) -> Path:
    target = tmp_path / "images" / "products" / "SA" / "1" / "a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(JPEG)
    return tmp_path


def test_windows_paths_written_by_the_mapping_resolve_inside_the_media_folder(
    tmp_path: Path,
) -> None:
    root = media(tmp_path)

    found = resolve_picture_file(root, r"data\media\images\products\SA\1\a.jpg")

    assert found == (root / "images" / "products" / "SA" / "1" / "a.jpg").resolve()


@pytest.mark.parametrize(
    "stored",
    ["data/media/images/../../secret.txt", "/etc/passwd", "images/products/SA/1/missing.jpg", ""],
)
def test_paths_outside_the_folder_or_missing_files_do_not_resolve(
    tmp_path: Path, stored: str
) -> None:
    assert resolve_picture_file(media(tmp_path), stored) is None


async def test_a_real_picture_is_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHARMAVIQUE_MEDIA_DIR", str(media(tmp_path)))
    from pharmavique.bootstrap.settings import get_settings

    get_settings.cache_clear()
    row = StoredPicture("real", "products/SA/1/a.jpg", "image/jpeg", "matched")
    app = create_app(pictures=FakePictures({"1": row}))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/products/1/picture")

    get_settings.cache_clear()
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-picture-status"] == "matched"


@pytest.mark.parametrize(
    ("stored", "key"),
    [
        (r"data\media\images\products\SA\1\a.jpg", "products/SA/1/a.jpg"),
        ("products/SA/1/a.jpg", "products/SA/1/a.jpg"),
        ("data/media/images/../../secret.txt", None),
        ("/etc/passwd", None),
        ("", None),
    ],
)
def test_the_bucket_key_is_the_path_after_images(stored: str, key: str | None) -> None:
    assert picture_key(stored) == key


async def test_with_a_bucket_the_picture_is_a_redirect_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # nothing is read from the disk: on a host without the media folder the bucket holds the files
    monkeypatch.setenv("PHARMAVIQUE_MEDIA_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("PHARMAVIQUE_PICTURE_BASE_URL", "https://bucket.example/pics/")
    from pharmavique.bootstrap.settings import get_settings

    get_settings.cache_clear()
    row = StoredPicture("real", r"data\media\images\products\SA\1\a.jpg", "image/jpeg", "matched")
    app = create_app(pictures=FakePictures({"1": row}))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/products/1/picture", follow_redirects=False)

    get_settings.cache_clear()
    assert response.status_code == 307
    assert response.headers["location"] == "https://bucket.example/pics/products/SA/1/a.jpg"
    assert response.headers["cache-control"] == "public, max-age=86400"


async def test_a_generated_card_or_unknown_product_has_no_picture() -> None:
    row = StoredPicture("generated", "placeholders/x.svg", "image/svg+xml", None)
    app = create_app(pictures=FakePictures({"2": row}))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.get("/v1/products/2/picture")
        unknown = await client.get("/v1/products/9/picture")

    assert generated.status_code == 404
    assert unknown.status_code == 404
