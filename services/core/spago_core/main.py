"""SPAgo core FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from spago_core import __version__
from spago_core.api.auth_routes import router as auth_router
from spago_core.api.routes import health_payload, router
from spago_core.config import get_settings
from spago_core.db import make_engine
from spago_core.services import auth as auth_svc


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
    # B-34: build identity is injected at packaging time (docker build arg →
    # image env → SPAGO_BUILD_ID); the container has no .git directory, so it is
    # never read from a checkout at runtime. A missing identity is reported
    # explicitly as unknown — never defaulted from `__version__`, which is a
    # package version, not a build identity.
    app.state.build_id = settings.build_id.strip() or "unknown"
    app.state.build_source = "env" if settings.build_id.strip() else "unknown"

    app.add_middleware(
        # B-15: the container *is* the supported install and it has no proxy, so the
        # assets are compressed here instead of by an ingress that may not exist —
        # above all the embedded editor's 7.8 MB bundle and 11.8 MB WASM, whose first
        # open is the one transfer cost a reader feels directly. Level 6, not 9:
        # measured on this checkout, 9 saves 48 KB of a 5.2 MB first open for twice
        # the CPU (`benchmarks/asset-compression-2026-09-16.md`). The thread
        # threshold matches the 64 KiB chunk `FileResponse` streams, so a file chunk
        # is compressed on a worker thread rather than in the event loop. Responses
        # that already carry `content-encoding`, 206 partial responses and bodies
        # under the minimum pass through untouched, which is what keeps a
        # compressing proxy in front of this process safe (`docs/runbook.md` §H2).
        # Added before CORS/gate, so it sits innermost: they wrap a compressed
        # response without touching its body.
        GZipMiddleware,
        minimum_size=500,
        compresslevel=6,
        thread_minimum_size=64 * 1024,
    )

    app.add_middleware(
        CORSMiddleware,
        # Credentials are allowed only in hosted mode, where the session cookie
        # must travel; the local product stays credential-free. Origins are
        # explicit, never "*", so a browser cannot be told to send the cookie
        # cross-origin.
        allow_origins=settings.all_cors_origins,
        allow_credentials=settings.auth_required,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_session_for_api(request, call_next):
        """Authentication gate for hosted mode (ONLINE-03, ADR-0002).

        This is the outer gate, not the authorization decision: it guarantees
        that no workspace endpoint is reachable anonymously, including routes
        added later. Per-object authorization (whose project, whose analysis)
        lives in the services, where it can see the data.

        In `disabled` mode the gate is inert, which is what keeps
        `docker compose up` a usable single-user product.
        """
        current = get_settings()
        path = request.url.path
        if (
            current.auth_required
            and path.startswith("/api/")
            and not path.startswith("/api/v1/auth/")
        ):
            try:
                auth_svc.authenticate(app.state.engine, request.cookies.get(auth_svc.SESSION_COOKIE))
            except auth_svc.AuthError as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.get("/healthz", response_model=None)
    def healthz():
        return health_payload(app)

    app.include_router(auth_router)
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
