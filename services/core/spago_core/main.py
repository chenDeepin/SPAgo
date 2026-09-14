"""SPAgo core FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from spago_core import __version__
from spago_core.api.routes import health_payload, router
from spago_core.config import get_settings
from spago_core.db import make_engine


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # One shared HTTP client for outbound model calls (LLM interface plan):
        # redirects are never followed; per-request timeouts are set by the adapter.
        app.state.llm_client = httpx.Client(follow_redirects=False)
        yield
        app.state.llm_client.close()

    app = FastAPI(
        title="SPAgo Core",
        version=__version__,
        description="Structure-native patent intelligence workspace.",
        lifespan=lifespan,
    )
    app.state.engine = make_engine(settings.database_url)
    app.state.version = __version__

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/healthz", response_model=None)
    def healthz():
        return health_payload(app)

    app.include_router(router)

    _mount_web(app)

    return app


def _mount_web(app: FastAPI) -> None:
    """Serve the built frontend from the same process when a build is present.

    Looks for SPAGO_WEB_DIR, then the container path, then a local repo build.
    """
    import os

    settings = get_settings()
    candidates: list[Path] = []
    web_dir_env = os.environ.get("SPAGO_WEB_DIR")
    if web_dir_env:
        candidates.append(Path(web_dir_env))
    candidates.extend([Path("/app/web"), settings.fixture_dir.parents[1] / "apps" / "web" / "dist"])

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            app.mount("/", StaticFiles(directory=str(candidate), html=True), name="web")
            return


app = create_app()
