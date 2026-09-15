"""ONLINE-03: invitation-only sessions and per-owner isolation (ADR-0002).

Two accounts, one server, direct API calls — no reliance on hidden buttons. The
tests use guessed UUIDs deliberately: hiding a project in the UI is not access
control, so authorization is checked where the data is read and written.

Covered: anonymous rejection in hosted mode; the local mode staying unchanged;
invitation redemption, single use, expiry and revocation; session expiry,
revocation and logout; identical project names per owner; A unable to see,
read, modify or export B's work; A's cached analysis never served to B;
unassigned legacy data unreachable from a hosted session; and a client being
unable to inject a provider endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.config import get_settings
from spago_core.main import create_app
from spago_core.services import auth as auth_svc

from conftest import RESETTABLE_TABLES


@pytest.fixture(scope="module")
def online_engine(seeded_engine):
    with seeded_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, invitations, sessions CASCADE"))
    return seeded_engine


@pytest.fixture(autouse=True)
def clean_accounts(online_engine):
    """Accounts and sessions per test; scientific rows come from seeded_engine."""
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, invitations, sessions CASCADE"))
        # Projects and analyses are per-test so ownership assertions are exact.
        for table in ("project_items", "projects", "ai_analyses"):
            conn.execute(text(f"TRUNCATE {table} CASCADE"))
    yield


def _hosted_client(online_engine, monkeypatch) -> TestClient:
    monkeypatch.setenv("SPAGO_AUTH_MODE", "required")
    get_settings.cache_clear()
    app = create_app()
    app.state.engine = online_engine
    return TestClient(app)


def _local_client(online_engine, monkeypatch) -> TestClient:
    monkeypatch.setenv("SPAGO_AUTH_MODE", "disabled")
    get_settings.cache_clear()
    app = create_app()
    app.state.engine = online_engine
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    yield
    get_settings.cache_clear()


def _invite_and_sign_in(client: TestClient, engine, email: str) -> dict:
    """Create an invitation as an operator and redeem it as the user."""
    _invitation_id, token = auth_svc.create_invitation(engine, email)
    response = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
    assert response.status_code == 200, response.text
    body = response.json()
    # The TestClient keeps the cookies set by the response.
    return {**body, "csrf": body["csrf_token"]}


def _post(client: TestClient, session: dict, path: str, json: dict):
    return client.post(path, json=json, headers={auth_svc.CSRF_HEADER: session["csrf"]})


class TestHostedGate:
    def test_anonymous_workspace_access_fails_closed(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        for path in (
            "/api/v1/projects",
            "/api/v1/datasets/info",
            "/api/v1/targets",
            "/api/v1/targets/coverage/matrix",
        ):
            response = client.get(path)
            assert response.status_code == 401, path
            assert "Sign in" in response.json()["detail"] or "session" in response.json()["detail"]

    def test_auth_status_is_public_and_honest(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        body = client.get("/api/v1/auth/status").json()
        assert body["required"] is True
        assert body["authenticated"] is False

    def test_redeeming_an_unknown_token_fails(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        response = client.post(
            "/api/v1/auth/invitations/redeem", json={"token": "not-a-real-invitation-token"}
        )
        assert response.status_code == 401
        assert "not valid" in response.json()["detail"]

    def test_an_invitation_is_single_use(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        _invitation_id, token = auth_svc.create_invitation(online_engine, "ada@example.org")
        first = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
        assert first.status_code == 200
        second = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
        assert second.status_code == 401
        assert "already been used" in second.json()["detail"]

    def test_a_revoked_invitation_cannot_be_redeemed(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        invitation_id, token = auth_svc.create_invitation(online_engine, "bob@example.org")
        assert auth_svc.revoke_invitation(online_engine, invitation_id) is True
        response = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
        assert response.status_code == 401
        assert "revoked" in response.json()["detail"]

    def test_an_expired_invitation_cannot_be_redeemed(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        _invitation_id, token = auth_svc.create_invitation(
            online_engine, "late@example.org", ttl_hours=-1
        )
        response = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_session_expiry_is_enforced_per_request(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        session = _invite_and_sign_in(client, online_engine, "expiring@example.org")
        assert client.get("/api/v1/projects").status_code == 200
        with online_engine.begin() as conn:
            conn.execute(text("UPDATE sessions SET expires_at = :past"), {"past": datetime.now(timezone.utc) - timedelta(hours=1)})
        response = client.get("/api/v1/projects")
        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_logout_revokes_the_session_immediately(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        session = _invite_and_sign_in(client, online_engine, "logout@example.org")
        assert _post(client, session, "/api/v1/auth/logout", {}).status_code == 200
        assert client.get("/api/v1/projects").status_code == 401

    def test_operator_can_revoke_every_session(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        session = _invite_and_sign_in(client, online_engine, "revoked@example.org")
        with online_engine.connect() as conn:
            user_id = conn.execute(
                text("SELECT id FROM users WHERE email = 'revoked@example.org'")
            ).scalar_one()
        assert auth_svc.revoke_user_sessions(online_engine, user_id) >= 1
        assert client.get("/api/v1/projects").status_code == 401

    def test_state_changing_requests_need_the_csrf_header(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        _invite_and_sign_in(client, online_engine, "csrf@example.org")
        missing = client.post("/api/v1/projects", json={"name": "No CSRF"})
        assert missing.status_code == 403
        assert "CSRF" in missing.json()["detail"]

    def test_a_client_cannot_inject_a_provider_endpoint(self, online_engine, monkeypatch):
        """The request schema forbids extra fields, so the operator's endpoint
        and key cannot be redirected by a caller."""
        client = _hosted_client(online_engine, monkeypatch)
        session = _invite_and_sign_in(client, online_engine, "endpoint@example.org")
        response = _post(
            client,
            session,
            "/api/v1/ai/plan",
            {
                "query": "TSLP",
                "use_llm": True,
                "llm_base_url": "https://attacker.invalid/v1",
                "llm_api_key": "steal-me",
            },
        )
        assert response.status_code == 422

    def test_local_mode_is_unchanged(self, online_engine, monkeypatch):
        """The local product must keep working with no accounts at all."""
        client = _local_client(online_engine, monkeypatch)
        status = client.get("/api/v1/auth/status").json()
        assert status["mode"] == "disabled"
        assert status["authenticated"] is True
        created = client.post("/api/v1/projects", json={"name": "Local project"})
        assert created.status_code == 201
        assert created.json()["name"] == "Local project"
        assert client.get("/api/v1/projects").status_code == 200
        with online_engine.connect() as conn:
            owner = conn.execute(
                text("SELECT owner_id FROM projects WHERE name = 'Local project'")
            ).scalar_one()
        # Local rows keep owner_id NULL, exactly as before accounts existed.
        assert owner is None


class TestTwoUserIsolation:
    @pytest.fixture()
    def two_users(self, online_engine, monkeypatch):
        client = _hosted_client(online_engine, monkeypatch)
        ada = _invite_and_sign_in(client, online_engine, "ada@example.org")
        # A second client keeps its own cookie jar, which the TestClient does.
        bob_client = _hosted_client.__wrapped__ if False else None  # clarity: same app, new client
        bob = TestClient(client.app)
        bob_session = _invite_and_sign_in(bob, online_engine, "bob@example.org")
        return {"ada": (client, ada), "bob": (bob, bob_session)}

    def test_identical_project_names_are_allowed_per_owner(self, two_users):
        (ada_client, ada) = two_users["ada"]
        (bob_client, bob) = two_users["bob"]
        a = _post(ada_client, ada, "/api/v1/projects", {"name": "TSLP screen"})
        b = _post(bob_client, bob, "/api/v1/projects", {"name": "TSLP screen"})
        assert a.status_code == 201 and b.status_code == 201
        assert a.json()["id"] != b.json()["id"]

    def test_project_lists_are_separate(self, two_users):
        (ada_client, ada) = two_users["ada"]
        (bob_client, bob) = two_users["bob"]
        _post(ada_client, ada, "/api/v1/projects", {"name": "Ada only"})
        _post(bob_client, bob, "/api/v1/projects", {"name": "Bob only"})
        assert [p["name"] for p in ada_client.get("/api/v1/projects").json()] == ["Ada only"]
        assert [p["name"] for p in bob_client.get("/api/v1/projects").json()] == ["Bob only"]

    def test_guessing_another_project_id_fails_closed(self, two_users):
        (ada_client, ada) = two_users["ada"]
        (bob_client, bob) = two_users["bob"]
        bob_project = _post(bob_client, bob, "/api/v1/projects", {"name": "Bob private"}).json()

        # Ada knows the id; every operation must still refuse.
        assert ada_client.get(f"/api/v1/projects/{bob_project['id']}").status_code == 404
        family_id = _family_id(ada_client)
        write = _post(
            ada_client,
            ada,
            f"/api/v1/projects/{bob_project['id']}/items",
            {"family_id": family_id, "compound_ids": None},
        )
        assert write.status_code == 404
        read_bob = bob_client.get(f"/api/v1/projects/{bob_project['id']}").json()
        assert read_bob["items"] == []

    def test_removing_another_users_item_fails_closed(self, two_users):
        (ada_client, ada) = two_users["ada"]
        (bob_client, bob) = two_users["bob"]
        bob_project = _post(bob_client, bob, "/api/v1/projects", {"name": "Bob saves"}).json()
        family_id = _family_id(bob_client)
        _post(
            bob_client,
            bob,
            f"/api/v1/projects/{bob_project['id']}/items",
            {"family_id": family_id, "compound_ids": None},
        )
        item_id = bob_client.get(f"/api/v1/projects/{bob_project['id']}").json()["items"][0]["id"]
        response = ada_client.delete(
            f"/api/v1/projects/{bob_project['id']}/items/{item_id}",
            headers={auth_svc.CSRF_HEADER: ada["csrf"]},
        )
        assert response.status_code == 404
        # Bob's item is still there.
        assert len(bob_client.get(f"/api/v1/projects/{bob_project['id']}").json()["items"]) == 1

    def test_cached_analyses_are_not_shared_between_owners(self, two_users):
        (ada_client, ada) = two_users["ada"]
        (bob_client, bob) = two_users["bob"]
        family_id = _family_id(ada_client)
        first = _post(ada_client, ada, f"/api/v1/families/{family_id}/summary", {"mode": "offline"})
        assert first.status_code == 200
        second = _post(bob_client, bob, f"/api/v1/families/{family_id}/summary", {"mode": "offline"})
        assert second.status_code == 200
        # Same public family, but each owner gets their own stored analysis.
        assert first.json()["analysis_id"] != second.json()["analysis_id"]
        assert first.json()["cached"] is False and second.json()["cached"] is False
        # A repeat within one owner does reuse that owner's row.
        again = _post(ada_client, ada, f"/api/v1/families/{family_id}/summary", {"mode": "offline"})
        assert again.json()["analysis_id"] == first.json()["analysis_id"]
        assert again.json()["cached"] is True

        with online_engine_owners(ada_client) as rows:
            assert len(rows) == 2
            assert len({row[0] for row in rows}) == 2

    def test_legacy_unassigned_projects_are_invisible(self, online_engine, monkeypatch, two_users):
        """A project with no owner predates accounts and belongs to nobody."""
        with online_engine.begin() as conn:
            legacy_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO projects (id, name, description, owner_id) "
                    "VALUES (:id, 'Legacy local project', NULL, NULL)"
                ),
                {"id": legacy_id},
            )
        (ada_client, _ada) = two_users["ada"]
        listed = [p["name"] for p in ada_client.get("/api/v1/projects").json()]
        assert "Legacy local project" not in listed
        assert ada_client.get(f"/api/v1/projects/{legacy_id}").status_code == 404

    def test_public_data_stays_shared(self, two_users):
        """Patent data is public: isolation applies to workspaces, not corpora."""
        (ada_client, _ada) = two_users["ada"]
        (bob_client, _bob) = two_users["bob"]
        assert ada_client.get("/api/v1/datasets/info").status_code == 200
        assert bob_client.get("/api/v1/datasets/info").status_code == 200
        assert ada_client.get("/api/v1/targets").status_code == 200


def _family_id(client: TestClient) -> str:
    """The demo family id, as the API reports it."""
    info = client.get("/api/v1/datasets/info")
    assert info.status_code == 200
    # Read the family through the patent endpoint of a seeded publication.
    family = client.get("/api/v1/patents/DEMO-PATENT-A")
    assert family.status_code == 200
    return family.json()["family"]["id"]


class online_engine_owners:
    """Small context manager reading analysis owners for an assertion."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __enter__(self):
        engine = self.client.app.state.engine
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT owner_id FROM ai_analyses ORDER BY created_at")
            ).all()

    def __exit__(self, *exc) -> None:
        return None
