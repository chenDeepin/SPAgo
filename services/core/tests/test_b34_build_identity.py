"""B-34 — /healthz carries a packaging-time build identity, not just api_version.

`api_version` comes from `__version__` and many builds share it, so a recorded
result or defect could not be related to the build actually served. The identity
is injected at packaging time (docker build arg → image env → SPAGO_BUILD_ID);
the running container has no .git directory, so nothing is read from a checkout.

These tests pin the served contract through the real application and route:
two injected identities are distinguishable, a missing one is reported
explicitly as unknown with its source, and the API version is never promoted
into the identity slot (`AGENTS.md` §36: a run at one configuration cannot be
validated at another).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from spago_core import __version__
from spago_core.config import get_settings
from spago_core.main import create_app


def _served_health(monkeypatch, injected: str | None) -> dict:
    """The /healthz JSON a build with `injected` as SPAGO_BUILD_ID serves.

    `get_settings` is cached, so the cache is cleared around each build — the
    same pattern the auth tests use — or every app would silently share the
    first environment read. No database is attached: a down database is
    /healthz's degraded state, not a reason to hide the identity under test.
    """
    if injected is None:
        monkeypatch.delenv("SPAGO_BUILD_ID", raising=False)
    else:
        monkeypatch.setenv("SPAGO_BUILD_ID", injected)
    get_settings.cache_clear()
    try:
        app = create_app()
    finally:
        get_settings.cache_clear()
    app.state.engine = None
    return TestClient(app).get("/healthz").json()


class TestInjectedIdentities:
    def test_two_builds_are_distinguishable(self, monkeypatch):
        first = _served_health(monkeypatch, "efb1357")
        second = _served_health(monkeypatch, "a1b2c3d-dirty")

        assert first["build_id"] == "efb1357"
        assert second["build_id"] == "a1b2c3d-dirty"
        assert first["build_id"] != second["build_id"]
        # The shared api_version is exactly what made these builds
        # indistinguishable before; it stays what it is.
        assert first["api_version"] == second["api_version"] == __version__

    def test_an_injected_identity_states_where_it_came_from(self, monkeypatch):
        body = _served_health(monkeypatch, "efb1357-dirty")
        assert body["build_source"] == "env"

    def test_a_dirty_build_is_carried_verbatim(self, monkeypatch):
        """The dirty marker distinguishes a checkout with local changes."""
        body = _served_health(monkeypatch, "efb1357-dirty")
        assert body["build_id"] == "efb1357-dirty"


class TestMissingIdentity:
    def test_a_missing_identity_is_explicitly_unknown(self, monkeypatch):
        body = _served_health(monkeypatch, None)
        assert body["build_id"] == "unknown"
        assert body["build_source"] == "unknown"

    def test_the_api_version_is_never_promoted_to_a_build_identity(self, monkeypatch):
        """`0.1.0` would be a guess, and many builds share it."""
        body = _served_health(monkeypatch, None)
        assert __version__ == "0.1.0"
        assert body["build_id"] != body["api_version"]

    def test_a_blank_identity_is_treated_as_missing(self, monkeypatch):
        body = _served_health(monkeypatch, "   ")
        assert body["build_id"] == "unknown"
        assert body["build_source"] == "unknown"
