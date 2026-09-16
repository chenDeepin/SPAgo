"""B-10: stored analyses can be listed, reopened, checked for staleness and exported.

The contract under test is what a scientist does a day later — find the analysis
they already paid for, read it again without a model call, see whether the data
behind it has moved, and take it out of the app as a file that still says what it
is. Ownership is part of it: one owner's stored analysis is never listed, opened
or exported for another.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.config import get_settings
from spago_core.main import create_app
from spago_core.services import ai, auth as auth_svc
from spago_core.services import analyses as analyses_svc


@pytest.fixture(scope="module")
def history_engine(seeded_engine):
    return seeded_engine


@pytest.fixture(autouse=True)
def clean_analyses(history_engine):
    """Analyses per test: this module asserts on exact lists and totals."""
    with history_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai_analyses CASCADE"))
    yield
    with history_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai_analyses CASCADE"))


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """`Settings` is cached process-wide; a test that flips the auth mode must
    not leave that mode behind for the next module (this is what turned the
    export and integration suites into 401s when the hosted-auth test above
    ran first). Env restore happens before this teardown, so clearing the cache
    here is enough."""
    yield
    get_settings.cache_clear()


@pytest.fixture()
def scope_ids(history_engine):
    with history_engine.connect() as conn:
        family = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        document = conn.execute(
            text(
                "SELECT id FROM patent_documents WHERE family_id = :f ORDER BY publication_number LIMIT 1"
            ),
            {"f": family},
        ).scalar_one()
    return family, document


@pytest.fixture()
def client(history_engine, monkeypatch):
    monkeypatch.setenv("SPAGO_AUTH_MODE", "disabled")
    get_settings.cache_clear()
    app = create_app()
    app.state.engine = history_engine
    yield TestClient(app)
    get_settings.cache_clear()


def _hosted_client(engine, monkeypatch) -> TestClient:
    monkeypatch.setenv("SPAGO_AUTH_MODE", "required")
    get_settings.cache_clear()
    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def _sign_in(client: TestClient, engine, email: str) -> dict:
    _invitation_id, token = auth_svc.create_invitation(engine, email)
    response = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
    assert response.status_code == 200, response.text
    body = response.json()
    return {**body, "csrf": body["csrf_token"]}


class TestHistoryList:
    def test_a_generated_summary_appears_with_its_scope_and_label(self, client, history_engine, scope_ids):
        family_id, document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        ai.summarize_document(history_engine, document_id)

        body = client.get("/api/v1/analyses").json()
        assert body["total"] == 2
        by_scope = {item["scope"]: item for item in body["items"]}
        assert set(by_scope) == {"family", "document"}
        family_entry = by_scope["family"]
        assert family_entry["scope_label"] == "DEMO-FAMILY-1"
        assert family_entry["scope_query"], "a live scope must offer a way back to it"
        assert family_entry["mode"] == "offline"
        assert family_entry["model"] is None
        assert family_entry["provenance_state"] == "machine_extracted"
        assert family_entry["citation_count"] >= 0
        assert family_entry["stale"] is False, family_entry["stale_reasons"]

    def test_the_list_is_newest_first(self, client, history_engine, scope_ids):
        family_id, document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        ai.summarize_document(history_engine, document_id)
        items = client.get("/api/v1/analyses").json()["items"]
        assert [i["created_at"] for i in items] == sorted(
            [i["created_at"] for i in items], reverse=True
        )

    def test_scope_filter_and_label_search(self, client, history_engine, scope_ids):
        family_id, document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        ai.summarize_document(history_engine, document_id)

        only_documents = client.get("/api/v1/analyses", params={"scope": "document"}).json()
        assert [i["scope"] for i in only_documents["items"]] == ["document"]

        hit = client.get("/api/v1/analyses", params={"search": "DEMO-FAMILY"}).json()
        # A document analysis records its document's family too, so searching the
        # family key finds the family analysis and its documents' analyses —
        # which is what a person looking for "everything about this family"
        # wants. The scope label still names each one truthfully.
        assert {i["scope"] for i in hit["items"]} == {"family", "document"}
        labels = {i["scope"]: i["scope_label"] for i in hit["items"]}
        assert labels["family"] == "DEMO-FAMILY-1"
        assert labels["document"].startswith("DEMO-PATENT-")

        miss = client.get("/api/v1/analyses", params={"search": "no-such-label"}).json()
        assert miss["items"] == [] and miss["total"] == 0

    def test_a_literal_wildcard_does_not_match_everything(self, client, history_engine, scope_ids):
        family_id, _document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        body = client.get("/api/v1/analyses", params={"search": "%"}).json()
        assert body["total"] == 0, "a literal % must not act as a wildcard"

    def test_an_unknown_scope_is_refused(self, client):
        assert client.get("/api/v1/analyses", params={"scope": "patent"}).status_code == 422

    def test_the_page_is_bounded(self, client, history_engine, scope_ids):
        family_id, _document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        body = client.get("/api/v1/analyses", params={"limit": 5000}).json()
        assert body["limit"] == analyses_svc.MAX_PAGE


class TestReopening:
    def test_reading_it_back_needs_no_provider(self, client, history_engine, scope_ids):
        """The acceptance case: sign out, sign in, reopen — and no model call.

        Asserted the strong way: the LLM endpoint is left unconfigured and the
        request is a plain GET, so any provider call would fail the test.
        """
        family_id, _document_id = scope_ids
        stored = ai.summarize_family(history_engine, family_id)

        listed = client.get("/api/v1/analyses").json()["items"][0]
        detail = client.get(f"/api/v1/analyses/{listed['analysis_id']}").json()
        assert detail["analysis_id"] == str(stored["analysis_id"])
        assert detail["text"] == stored["text"]
        assert detail["citations"] == stored["citations"]
        assert detail["exact_check"]["same_inputs"] is True, detail["exact_check"]
        assert detail["stale"] is False, detail["stale_reasons"]

    def test_an_unknown_or_foreign_analysis_is_not_found(self, client):
        assert client.get(f"/api/v1/analyses/{uuid.uuid4()}").status_code == 404

    def test_the_exact_check_reports_changed_inputs_after_the_data_moves(
        self, client, history_engine, scope_ids
    ):
        """A stored analysis is a statement about the inputs it was given.

        Adding a measurement inside the family's scope changes those inputs, so
        the exact check must say the entry no longer describes the current data
        instead of presenting the old answer as current.
        """
        family_id, _document_id = scope_ids
        stored = ai.summarize_family(history_engine, family_id)

        with history_engine.begin() as conn:
            compound_id = conn.execute(
                text(
                    """
                    SELECT c.id FROM compounds c
                      JOIN compound_mentions m ON m.compound_id = c.id
                     WHERE m.document_id IN (SELECT id FROM patent_documents WHERE family_id = :f)
                     LIMIT 1
                    """
                ),
                {"f": family_id},
            ).scalar_one()
            assay_id = conn.execute(text("SELECT id FROM assays LIMIT 1")).scalar_one()
            measurement_id = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                              unit, relation, source_name, extraction_method,
                                              provenance_state, dataset_version, retrieved_at)
                    VALUES (:id, :c, :a, 'IC50', 5.0, 'nM', '=', 'reviewer_added',
                            'test_fixture', 'user_curated', 'demo-fixture-v1', now())
                    """
                ),
                {"id": measurement_id, "c": compound_id, "a": assay_id},
            )
        try:
            detail = client.get(f"/api/v1/analyses/{stored['analysis_id']}").json()
            assert detail["exact_check"]["same_inputs"] is False, detail["exact_check"]
            assert detail["stale"] is True
            assert any("inputs have changed" in reason for reason in detail["stale_reasons"])
        finally:
            with history_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM measurements WHERE id = :id"), {"id": measurement_id}
                )

    def test_a_deleted_target_leaves_the_entry_readable_and_marked(
        self, client, history_engine
    ):
        """A target that is no longer in the workspace must not look current.

        The analysis row itself survives (no cascade on `target_id`), so the
        honest state is: text still readable, scope named as gone, no navigation
        offered.
        """
        target_id = uuid.uuid4()
        with history_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, organism, source_name,
                                         dataset_version, retrieved_at)
                    VALUES (:t, :k, 'Fixture target', 'Homo sapiens', 'chembl',
                            'external:open-databases', now())
                    """
                ),
                {"t": target_id, "k": f"FIXTURE-{target_id.hex[:8]}"},
            )
        try:
            stored = ai.summarize_target(history_engine, target_id)
            listed = client.get("/api/v1/analyses").json()["items"][0]
            assert listed["scope_query"] == f"FIXTURE-{target_id.hex[:8]}"
            with history_engine.begin() as conn:
                conn.execute(text("DELETE FROM targets WHERE id = :t"), {"t": target_id})
            detail = client.get(f"/api/v1/analyses/{stored['analysis_id']}").json()
            assert detail["scope_query"] is None
            assert detail["stale"] is True
            assert any("no longer in the workspace" in r for r in detail["stale_reasons"])
            assert detail["text"], "the stored text stays readable"
        finally:
            with history_engine.begin() as conn:
                conn.execute(text("DELETE FROM targets WHERE id = :t"), {"t": target_id})

    def test_a_dataset_change_is_reported_for_patent_scopes(
        self, client, history_engine, scope_ids, monkeypatch
    ):
        family_id, _document_id = scope_ids
        ai.summarize_family(history_engine, family_id)
        monkeypatch.setattr(
            analyses_svc, "_staleness_context", lambda engine: {
                "current_dataset": "a-newer-release",
                "current_policy_version": "potency-gate-v1",
                "prompt_versions": ai.PROMPT_VERSION_BY_SCOPE,
            }
        )
        body = client.get("/api/v1/analyses").json()
        entry = body["items"][0]
        assert entry["stale"] is True
        assert any("a-newer-release" in reason for reason in entry["stale_reasons"])


class TestExport:
    def test_the_file_states_what_it_is(self, client, history_engine, scope_ids):
        family_id, _document_id = scope_ids
        stored = ai.summarize_family(history_engine, family_id)
        response = client.get(f"/api/v1/analyses/{stored['analysis_id']}/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.headers["x-spago-analysis-stale"] == "false"
        assert "spago-family-analysis-" in response.headers["content-disposition"]
        text = response.text
        assert "# SPAgo family analysis" in text
        assert f"- Analysis id: `{stored['analysis_id']}`" in text
        assert "- Provider: offline-extractive" in text
        assert "- Model: none (offline, deterministic)" in text
        assert f"- Prompt version: {ai.PROMPT_VERSION_BY_SCOPE['family']}" in text
        assert "- Provenance: machine_extracted" in text
        assert "- Dataset version at generation: demo-fixture-v1" in text
        assert "- Dataset version now: demo-fixture-v1 (unchanged)" in text
        assert "- Inputs unchanged since generation: yes" in text
        assert "## Summary" in text
        assert stored["text"] in text
        assert f"## Citations ({len(stored['citations'])})" in text
        assert "Nothing here is legal advice" in text

    def test_the_export_quotes_the_stored_text_not_a_fresh_generation(
        self, client, history_engine, scope_ids
    ):
        family_id, _document_id = scope_ids
        stored = ai.summarize_family(history_engine, family_id)
        with history_engine.begin() as conn:
            conn.execute(
                text("UPDATE ai_analyses SET text = :t WHERE id = :id"),
                {"t": "A previously stored body.", "id": stored["analysis_id"]},
            )
        response = client.get(f"/api/v1/analyses/{stored['analysis_id']}/export")
        assert "A previously stored body." in response.text

    def test_a_stale_analysis_says_so_in_the_file_and_the_header(
        self, client, history_engine, scope_ids, monkeypatch
    ):
        family_id, _document_id = scope_ids
        stored = ai.summarize_family(history_engine, family_id)
        original = analyses_svc._cheap_staleness

        def with_reason(row, **kwargs):
            return original(row, **kwargs) + ["Generated under a superseded policy."]

        monkeypatch.setattr(analyses_svc, "_cheap_staleness", with_reason)
        response = client.get(f"/api/v1/analyses/{stored['analysis_id']}/export")
        assert response.headers["x-spago-analysis-stale"] == "true"
        assert "- Staleness:" in response.text
        assert "superseded policy" in response.text

    def test_exporting_a_foreign_analysis_is_not_found(self, client):
        assert client.get(f"/api/v1/analyses/{uuid.uuid4()}/export").status_code == 404


class TestOwnership:
    def test_one_owners_analysis_is_neither_listed_nor_openable_by_another(
        self, history_engine, monkeypatch
    ):
        client = _hosted_client(history_engine, monkeypatch)
        try:
            alice = _sign_in(client, history_engine, "alice@example.test")
            with history_engine.connect() as conn:
                family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
                alice_id = conn.execute(
                    text("SELECT id FROM users WHERE email = :e"), {"e": alice["email"]}
                ).scalar_one()
            stored = ai.summarize_family(history_engine, family_id, owner_id=alice_id)
            assert len(client.get("/api/v1/analyses").json()["items"]) == 1
            assert client.get(f"/api/v1/analyses/{stored['analysis_id']}").status_code == 200

            assert (
                client.post("/api/v1/auth/logout", headers={auth_svc.CSRF_HEADER: alice["csrf"]})
            ).status_code == 200
            bob = _sign_in(client, history_engine, "bob@example.test")
            assert bob["email"] == "bob@example.test"
            body = client.get("/api/v1/analyses").json()
            assert body["items"] == [], "another owner's analysis is not listed"
            assert client.get(f"/api/v1/analyses/{stored['analysis_id']}").status_code == 404
            assert (
                client.get(f"/api/v1/analyses/{stored['analysis_id']}/export").status_code == 404
            )
        finally:
            with history_engine.begin() as conn:
                conn.execute(text("TRUNCATE users, invitations, sessions CASCADE"))
