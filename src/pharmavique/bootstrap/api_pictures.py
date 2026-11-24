"""The picture of a product, served from the stored files (see `sfda-images-restore`)."""

from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.infrastructure.persistence.pictures import StoredPicture

router = APIRouter(prefix="/v1", tags=["pictures"])


class PictureLookup(Protocol):
    async def find(self, market: str, register_number: str) -> StoredPicture | None: ...


def picture_key(stored: str) -> str | None:
    """The path of a stored picture inside the media folder (and the name of its file in a bucket).

    Paths were written on Windows (backslashes) relative to the project folder, for example
    `data\\media\\images\\products\\SA\1\a.jpg`; only the part after `images/` is kept.
    """
    relative = PurePosixPath(stored.replace("\\", "/"))
    parts = relative.parts
    if "images" in parts:
        parts = parts[parts.index("images") + 1 :]
    if not parts or relative.is_absolute() or ".." in parts:
        return None
    return str(PurePosixPath(*parts))


def resolve_picture_file(root: Path, stored: str) -> Path | None:
    """The file a stored path points at, only if it exists inside `root` (the media folder)."""
    key = picture_key(stored)
    if key is None:
        return None
    base = (root / "images").resolve()
    target = (base / PurePosixPath(key)).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target


def get_pictures(request: Request) -> PictureLookup:
    pictures: PictureLookup | None = request.app.state.pictures
    if pictures is None:
        raise HTTPException(status_code=503, detail="pictures are not configured")
    return pictures


# the box or its shop page is another strength or variant of the brand
_NOT_THIS_PRODUCT = {"strength_conflict", "page_conflict"}


@router.get(
    "/products/{register_number}/picture",
    response_class=FileResponse,
    summary="The product's picture (404 when there is none)",
)
async def product_picture(
    register_number: str, pictures: Annotated[PictureLookup, Depends(get_pictures)]
) -> Response:
    stored = await pictures.find("SA", register_number)
    # A generated card is not the box: the app draws its own placeholder instead. Neither is a
    # box that states other strengths than the registry's: it is another product of the brand.
    if stored is None or stored.kind != "real" or stored.verification in _NOT_THIS_PRODUCT:
        raise HTTPException(status_code=404, detail="no picture for this product")
    settings = get_settings()
    if settings.picture_base_url:
        # The files live in a public bucket (a host such as Vercel has no media folder).
        key = picture_key(stored.file_path)
        if key is None:
            raise HTTPException(status_code=404, detail="no picture for this product")
        return RedirectResponse(
            f"{settings.picture_base_url.rstrip('/')}/{key}",
            status_code=307,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    file = resolve_picture_file(Path(settings.media_dir), stored.file_path)
    if file is None:
        raise HTTPException(status_code=404, detail="no picture for this product")
    return FileResponse(
        file,
        media_type=stored.content_type,
        headers={"Cache-Control": "public, max-age=86400", "X-Picture-Status": stored.status or ""},
    )
