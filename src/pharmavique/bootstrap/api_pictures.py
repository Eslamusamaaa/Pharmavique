"""The picture of a product, served from the stored files (see `sfda-images-restore`)."""

from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.infrastructure.persistence.pictures import StoredPicture

router = APIRouter(prefix="/v1", tags=["pictures"])


class PictureLookup(Protocol):
    async def find(self, market: str, register_number: str) -> StoredPicture | None: ...


def resolve_picture_file(root: Path, stored: str) -> Path | None:
    """The file a stored path points at, only if it exists inside `root` (the media folder).

    Paths were written on Windows (backslashes) relative to the project folder, for example
    `data\\media\\images\\products\\SA\1\a.jpg`; only the part after `images/` is kept.
    """
    relative = PurePosixPath(stored.replace("\\", "/"))
    parts = relative.parts
    if "images" in parts:
        parts = parts[parts.index("images") + 1 :]
    if not parts or relative.is_absolute() or ".." in parts:
        return None
    base = (root / "images").resolve()
    target = (base / PurePosixPath(*parts)).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target


def get_pictures(request: Request) -> PictureLookup:
    pictures: PictureLookup | None = request.app.state.pictures
    if pictures is None:
        raise HTTPException(status_code=503, detail="pictures are not configured")
    return pictures


@router.get(
    "/products/{register_number}/picture",
    response_class=FileResponse,
    summary="The product's picture (404 when there is none)",
)
async def product_picture(
    register_number: str, pictures: Annotated[PictureLookup, Depends(get_pictures)]
) -> FileResponse:
    stored = await pictures.find("SA", register_number)
    # A generated card is not the box: the app draws its own placeholder instead.
    if stored is None or stored.kind != "real":
        raise HTTPException(status_code=404, detail="no picture for this product")
    file = resolve_picture_file(Path(get_settings().media_dir), stored.file_path)
    if file is None:
        raise HTTPException(status_code=404, detail="no picture for this product")
    return FileResponse(
        file,
        media_type=stored.content_type,
        headers={"Cache-Control": "public, max-age=86400", "X-Picture-Status": stored.status or ""},
    )
