"""Serve the website (the Expo web export) from the API itself.

The app and the API then share one address, so there is no CORS, no http/https mixing and one
thing to add to a phone's home screen. The app is a single page with its own router: an address that
is not a file (a screen such as `/drug/1-1`) gets the app shell, so a reload opens the same screen.
An address with a file extension that does not exist, and anything under `/v1`, stays a 404.
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SinglePageStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            is_screen = error.status_code == 404 and "." not in Path(path).name
            if is_screen and not path.startswith(("v1/", "v1")):
                return await super().get_response("index.html", scope)
            raise


def mount_web_app(app: FastAPI, directory: Path) -> bool:
    """Mount the exported website at `/` (after every API route, so those win). Returns whether a
    website was found; without one the API is unchanged."""
    if not (directory / "index.html").is_file():
        return False
    app.mount("/", SinglePageStaticFiles(directory=directory, html=True), name="web")
    return True
