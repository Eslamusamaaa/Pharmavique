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

# The export names every script, font and picture after its content, so those never change under
# one address and can be kept for a year. Everything else (the page shell, the manifest, the home
# screen icons) can change under the same address: a browser never keeps it, but the edge of a host
# may for an hour. On Vercel every request the edge cannot answer runs the Python function, which
# may be a cold start of seconds before the app shows; Vercel clears its edge cache with every
# deployment, so the shell there never outlives the scripts it names.
_HASHED_FOLDERS = ("_expo/static/", "assets/")
_IMMUTABLE = "public, max-age=31536000, immutable"
_SHELL = "public, max-age=0, must-revalidate, s-maxage=3600"
_CONDITIONAL = (b"if-none-match", b"if-modified-since")


def _without_conditional_headers(scope: Scope) -> Scope:
    """A copy of the request that never asks "has it changed?". The answer is computed from the
    file's date and size, and some hosts (Vercel) give every file the same date: a new page of the
    same size then looked unchanged, the browser kept the old one, and the old page asked for
    scripts that no longer existed (a blank screen after each deployment)."""
    headers = [(name, value) for name, value in scope["headers"] if name not in _CONDITIONAL]
    return {**scope, "headers": headers}


class SinglePageStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        # Starlette hands over the path with the separator of the operating system
        hashed = path.replace("\\", "/").startswith(_HASHED_FOLDERS)
        if not hashed:
            scope = _without_conditional_headers(scope)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            is_screen = error.status_code == 404 and "." not in Path(path).name
            if is_screen and not path.startswith(("v1/", "v1")):
                response = await super().get_response("index.html", scope)
            else:
                raise
        if hashed:
            response.headers["Cache-Control"] = _IMMUTABLE
        else:
            response.headers["Cache-Control"] = _SHELL
            # No validators: a host's edge compares If-None-Match with the ETag of a response
            # and answers 304 on its own, even when the application sent the full file.
            for validator in ("etag", "last-modified"):
                if validator in response.headers:
                    del response.headers[validator]
        return response


def mount_web_app(app: FastAPI, directory: Path) -> bool:
    """Mount the exported website at `/` (after every API route, so those win). Returns whether a
    website was found; without one the API is unchanged."""
    if not (directory / "index.html").is_file():
        return False
    app.mount("/", SinglePageStaticFiles(directory=directory, html=True), name="web")
    return True
