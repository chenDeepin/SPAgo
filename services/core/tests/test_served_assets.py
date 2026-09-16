"""B-15 — served assets are compressed inside the product, not only at a proxy.

The container is the supported install (`AGENTS.md` §24) and it has no proxy, so an
ingress duty is a duty with no owner there. These tests pin two things: that the app
configures the middleware with the round's measured settings, and that the settings
do what the record claims on a *real* `StaticFiles` mount — because the interesting
cases (the editor's `.wasm`, a `.png` that must not be encoded twice) are decided by
the content type Starlette computes, not by the request path.

The behaviour tests take their parameters from `create_app()` rather than restating
constants here, so a run at one configuration cannot be validated at another
(`AGENTS.md` §36).
"""
from __future__ import annotations

import asyncio
import gzip

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from spago_core.main import create_app


def _configured_gzip(app: FastAPI) -> dict:
    """The kwargs the application hands to `GZipMiddleware` (fails if absent)."""
    for middleware in app.user_middleware:
        if middleware.cls is GZipMiddleware:
            return dict(middleware.kwargs)
    raise AssertionError("the app does not configure GZipMiddleware")


def _raw_get(app: FastAPI, path: str, *, accept_encoding: str) -> dict:
    """One raw ASGI request, so the assertions see the bytes on the wire.

    A test client would decode the body and hide `content-encoding`, which is the
    exact header this round is about.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept-encoding", accept_encoding.encode())],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "extensions": {},
    }
    received: dict = {"body": b""}

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            received["status"] = message["status"]
            received["headers"] = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in message["headers"]
            }
        elif message["type"] == "http.response.body":
            received["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return received


@pytest.fixture(scope="module")
def configured_app() -> FastAPI:
    """The real application, built the way `uvicorn spago_core.main:app` builds it.

    No database is touched: creating the app only constructs an engine and reads
    settings, and everything below is about the static-asset path.
    """
    return create_app()


@pytest.fixture()
def asset_app(tmp_path, configured_app) -> FastAPI:
    """A static mount wrapped in the *application's own* compression settings."""
    app = FastAPI()
    app.add_middleware(GZipMiddleware, **_configured_gzip(configured_app))
    app.mount("/", StaticFiles(directory=str(tmp_path)), name="web")
    app.state.asset_dir = tmp_path
    return app


def _write(app: FastAPI, name: str, payload: bytes) -> bytes:
    (app.state.asset_dir / name).write_bytes(payload)
    return payload


class TestTheAppAsksForCompression:
    def test_the_middleware_is_configured_with_the_measured_settings(self, configured_app):
        settings = _configured_gzip(configured_app)
        assert settings["compresslevel"] == 6, "level 6 is the round's measured choice"
        assert settings["minimum_size"] == 500
        # `FileResponse` streams in 64 KiB chunks; a threshold above that would put
        # every file chunk on the event loop.
        assert settings["thread_minimum_size"] <= 64 * 1024

    def test_compression_sits_inside_the_cors_and_session_layers(self, configured_app):
        """Order is behaviour: the outer layers must not rewrite a compressed body."""
        order = [middleware.cls.__name__ for middleware in configured_app.user_middleware]
        assert order.index("GZipMiddleware") > order.index("CORSMiddleware")


class TestWhatReachesTheBrowser:
    def test_a_javascript_asset_is_gzipped_when_the_client_accepts_it(self, asset_app):
        payload = _write(asset_app, "bundle.js", b"const x = 1;\n" * 700)  # ~8.4 KB

        response = _raw_get(asset_app, "/bundle.js", accept_encoding="gzip, deflate")

        assert response["headers"]["content-type"].startswith("text/javascript")
        assert response["headers"]["content-encoding"] == "gzip"
        assert response["headers"]["vary"] == "Accept-Encoding"
        assert response["headers"]["content-length"] == str(len(response["body"]))
        assert gzip.decompress(response["body"]) == payload

    def test_a_client_that_does_not_accept_gzip_gets_the_bytes(self, asset_app):
        payload = _write(asset_app, "bundle.js", b"const x = 1;\n" * 700)

        response = _raw_get(asset_app, "/bundle.js", accept_encoding="identity")

        assert "content-encoding" not in response["headers"]
        assert response["body"] == payload
        # A shared cache must still key on the encoding, or it can hand a gzipped
        # body to a client that did not ask for one.
        assert response["headers"]["vary"] == "Accept-Encoding"

    def test_a_small_asset_is_left_alone(self, asset_app):
        payload = _write(asset_app, "tiny.js", b"x")

        response = _raw_get(asset_app, "/tiny.js", accept_encoding="gzip")

        assert "content-encoding" not in response["headers"]
        assert response["body"] == payload

    def test_the_editor_wasm_is_compressed(self, asset_app):
        """The 11.8 MB engine is the single biggest first-open transfer."""
        payload = _write(asset_app, "engine.wasm", b"\x00asm\x01\x00\x00\x00" + b"\x0f" * 200_000)

        response = _raw_get(asset_app, "/engine.wasm", accept_encoding="gzip")

        assert response["headers"]["content-type"].startswith("application/wasm")
        assert response["headers"]["content-encoding"] == "gzip"
        assert gzip.decompress(response["body"]) == payload

    def test_a_streamed_asset_keeps_no_stale_length(self, asset_app):
        """Above 64 KiB `FileResponse` streams, so the raw length cannot survive."""
        payload = _write(asset_app, "big.js", b"0123456789abcdef" * 20_000)  # 320 KB

        response = _raw_get(asset_app, "/big.js", accept_encoding="gzip")

        assert response["headers"]["content-encoding"] == "gzip"
        assert "content-length" not in response["headers"], (
            "a streamed response must not claim the uncompressed length"
        )
        assert gzip.decompress(response["body"]) == payload

    def test_an_already_compressed_asset_is_not_encoded_again(self, asset_app):
        """PNG is in the middleware's exclusion list; a proxy in front stays safe."""
        payload = _write(asset_app, "depiction.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 90_000)

        response = _raw_get(asset_app, "/depiction.png", accept_encoding="gzip")

        assert response["headers"]["content-type"] == "image/png"
        assert "content-encoding" not in response["headers"]
        assert response["body"] == payload
