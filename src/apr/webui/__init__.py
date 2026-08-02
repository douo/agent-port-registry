"""Static hosting for the APR Web UI.

The bundle under ``static/`` is built from ``web/`` (Vite) and committed, so end
users never need Node — ``uv sync`` is enough. When the bundle is absent (a
source checkout that has not been built yet) the routes simply do not mount and
the API keeps working on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from apr.domain.errors import AprError, ErrorCode

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

#: Paths that belong to the API. The SPA fallback must not swallow them, or a
#: typo'd endpoint would answer 200 text/html instead of 404 JSON.
API_PREFIXES = ("v1/", "healthz")


def is_built() -> bool:
    """True when a built UI bundle is available to serve."""
    return INDEX_FILE.is_file()


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html so client-side routes work.

    Without this, a hard refresh on /services/SVC_ABC would 404: that path has
    no file behind it, it is a React Router route.
    """

    async def get_response(self, path: str, scope: Any) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if path.startswith(API_PREFIXES):
                # Unknown API path: answer in the API's own error envelope
                # rather than StaticFiles' text/plain "Not Found".
                return JSONResponse(
                    AprError(
                        ErrorCode.SERVICE_NOT_FOUND, f"No such endpoint: /{path}"
                    ).to_dict(),
                    status_code=404,
                )
            return await super().get_response("index.html", scope)


def webui_routes() -> list[Mount]:
    """Catch-all mount for the UI. Must be registered after the API routes."""
    if not is_built():
        return []
    return [
        Mount(
            "/",
            app=SPAStaticFiles(directory=str(STATIC_DIR), html=True),
            name="webui",
        )
    ]
