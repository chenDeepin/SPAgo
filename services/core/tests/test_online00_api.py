"""ONLINE-00 API contract: target resolution, discovery, candidates, coverage.

The routes are exercised through the real FastAPI app with the source adapters
replaced by recorded-payload stubs, so what is asserted is the HTTP contract the
UI depends on: status codes, pagination limits, the labelled modality filter, the
measured-evidence scope, and the save path for a candidate with no patent
mapping.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.db import run_migrations
from spago_core.main import create_app
from spago_core.services.discovery import TargetDiscoveryService
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_online_tables(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_route(call):
    """Answer the UniProt search for the TSLP fixture only.

    The stub must respect the query, otherwise a "no such gene" assertion would
    pass for the wrong reason: the resolver reads the response, not the request.
    """
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


@pytest.fixture()
def client(online_engine):
    app = create_app()
    app.state.engine = online_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    app.state.discovery_service = TargetDiscoveryService(
        chembl=ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_Q969D9.json"),
                    "activity.json": load_fixture("chembl_activities_TSLP.json"),
                }
            )
        ),
        bindingdb=BindingDBRestAdapter(
            client=StubSourceClient({"getLigandsByUniprot": load_fixture("bindingdb_P05231.json")})
        ),
        pubchem=PubChemAdapter(
            client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
        ),
    )
    return TestClient(app)


@pytest.fixture()
def resolved(client) -> dict:
    response = client.post("/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def investigated(client, resolved) -> dict:
    response = client.post(
        "/api/v1/targets/discover", json={"target_id": resolved["target_id"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestResolutionRoute:
    def test_resolution_returns_reviewed_scope_and_related_members(self, resolved):
        assert resolved["status"] == "resolved"
        assert resolved["uniprot_accession"] == "Q969D9"
        assert resolved["scope_kind"] == "ligand"
        roles = {c["gene_symbol"]: c["role"] for c in resolved["components"]}
        assert "TSLP" not in roles  # the requested target is not listed as related
        assert roles.get("CRLF2") == "receptor"

    def test_second_resolution_reuses_the_stored_scope(self, client, resolved):
        again = client.post("/api/v1/targets/resolve", json={"query": "q969d9", "species": "human"})
        assert again.status_code == 200
        assert again.json()["target_id"] == resolved["target_id"]
        assert any("already-resolved" in note for note in again.json()["notes"])

    def test_target_detail_and_list(self, client, resolved):
        detail = client.get(f"/api/v1/targets/{resolved['target_id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["resolution"]["query"] == "TSLP"
        listed = client.get("/api/v1/targets")
        assert [t["id"] for t in listed.json()] == [resolved["target_id"]]

    def test_unknown_target_is_not_found_not_an_error(self, client):
        response = client.post("/api/v1/targets/resolve", json={"query": "NOSUCHGENE", "species": "human"})
        assert response.status_code == 200
        assert response.json()["status"] == "not_found"
        assert response.json()["target_id"] is None

    def test_unsupported_species_is_reported_with_reason(self, client):
        response = client.post("/api/v1/targets/resolve", json={"query": "TSLP", "species": "unicorn"})
        assert response.status_code == 200
        assert response.json()["status"] == "not_queried"
        assert "Unsupported species" in " ".join(response.json()["notes"])

    def test_empty_query_is_rejected_by_the_contract(self, client):
        assert client.post("/api/v1/targets/resolve", json={"query": ""}).status_code == 422


class TestDiscoveryRoute:
    def test_every_source_reports_its_outcome(self, investigated):
        statuses = {s["source_name"]: s["status"] for s in investigated["sources"]}
        assert set(statuses) == {"chembl", "bindingdb", "pubchem"}
        assert all(status in {"complete", "partial", "empty", "failed", "not_queried"} for status in statuses.values())
        assert investigated["coverage_note"]
        assert any("not queried" in s["status"] or True for s in investigated["sources"])

    def test_coverage_note_prevents_an_empty_result_reading_as_no_inhibitors(self, investigated):
        assert "do not demonstrate that no inhibitors exist" in investigated["coverage_note"]

    def test_unknown_and_unsupported_sources_are_refused(self, client, resolved):
        bad = client.post(
            "/api/v1/targets/discover",
            json={"target_id": resolved["target_id"], "sources": ["chembl", "espacenet"]},
        )
        assert bad.status_code == 422
        assert "espacenet" in bad.json()["detail"]

    def test_unknown_target_is_404(self, client):
        response = client.post(
            "/api/v1/targets/discover", json={"target_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    def test_coverage_matrix_route_returns_per_source_rows(self, client, investigated, resolved):
        rows = client.get("/api/v1/targets/coverage/matrix").json()
        mine = [r for r in rows if r["target_id"] == resolved["target_id"]]
        assert {r["source_name"] for r in mine} == {"chembl", "bindingdb", "pubchem"}
        for row in mine:
            assert row["uniprot_accession"] == "Q969D9"
            assert row["query"]
            assert row["retrieved_at"]


class TestCandidateRoute:
    def test_candidates_default_to_a_labelled_modality_filter(self, client, investigated, resolved):
        body = client.get(f"/api/v1/targets/{resolved['target_id']}/candidates").json()
        assert body["default_filter"] == "small molecules and unclassified entities"
        assert body["modality_breakdown"]
        assert all(i["modality"] in {"small_molecule", "unclassified"} for i in body["items"])
        assert body["total"] == len(body["items"])
        assert all(i["patent_occurrences"] == 0 for i in body["items"])

    def test_all_modalities_can_be_requested_explicitly(self, client, investigated, resolved):
        filtered = client.get(f"/api/v1/targets/{resolved['target_id']}/candidates").json()
        every = client.get(
            f"/api/v1/targets/{resolved['target_id']}/candidates",
            params={"include_all_modalities": True},
        ).json()
        assert every["total"] >= filtered["total"]
        assert every["default_filter"] == "all modalities"
        modalities = {i["modality"] for i in every["items"]}
        assert modalities - {"small_molecule", "unclassified"}  # peptides are visible when asked

    def test_pagination_is_bounded_and_reports_totals(self, client, investigated, resolved):
        body = client.get(
            f"/api/v1/targets/{resolved['target_id']}/candidates",
            params={"include_all_modalities": True, "limit": 1, "offset": 0},
        ).json()
        assert len(body["items"]) == 1
        assert body["limit"] == 1
        assert body["total"] == sum(body["modality_breakdown"].values())
        # The ordinary maximum is enforced by the shared page clamp.
        capped = client.get(
            f"/api/v1/targets/{resolved['target_id']}/candidates",
            params={"include_all_modalities": True, "limit": 10_000},
        ).json()
        assert capped["limit"] <= 500

    def test_every_candidate_carries_its_classification_rule(self, client, investigated, resolved):
        body = client.get(
            f"/api/v1/targets/{resolved['target_id']}/candidates",
            params={"include_all_modalities": True},
        ).json()
        for item in body["items"]:
            assert item["modality_rule"]
            assert item["modality_source"] in {"rdkit", "source+rdkit"}
            assert item["evidence_class"]

    def test_unknown_target_is_404(self, client):
        assert client.get(f"/api/v1/targets/{uuid.uuid4()}/candidates").status_code == 404


class TestMeasurementRoute:
    def test_measurements_expose_assay_context_and_classes(self, client, investigated, resolved):
        rows = client.get(f"/api/v1/targets/{resolved['target_id']}/measurements").json()
        assert rows
        for row in rows:
            assert row["evidence_class"]
            assert row["standard_type"]
            assert row["unit"] is not None
            assert row["target_key"]
            assert row["provenance_state"] == "database_curated"
        assert {r["evidence_class"] for r in rows} >= {"measured_direct_binding", "functional_effect"}

    def test_evidence_class_filter(self, client, investigated, resolved):
        rows = client.get(
            f"/api/v1/targets/{resolved['target_id']}/measurements",
            params={"evidence_class": "functional_effect"},
        ).json()
        assert rows and all(r["evidence_class"] == "functional_effect" for r in rows)

    def test_duplicates_can_be_excluded_explicitly(self, client, investigated, resolved):
        all_rows = client.get(f"/api/v1/targets/{resolved['target_id']}/measurements").json()
        unique = client.get(
            f"/api/v1/targets/{resolved['target_id']}/measurements",
            params={"include_duplicates": False},
        ).json()
        assert len(unique) <= len(all_rows)
        assert all(not r["potential_duplicate"] for r in unique)


class TestSavingACandidateWithoutAPatent:
    def test_candidate_save_round_trip(self, client, investigated, resolved):
        candidates = client.get(f"/api/v1/targets/{resolved['target_id']}/candidates").json()
        compound_id = candidates["items"][0]["compound_id"]
        project = client.post("/api/v1/projects", json={"name": f"ONLINE-00 {uuid.uuid4()}"}).json()

        saved = client.post(
            f"/api/v1/projects/{project['id']}/candidates",
            json={"target_id": resolved["target_id"], "compound_ids": [compound_id]},
        )
        assert saved.status_code == 201, saved.text
        assert saved.json()["created_rows"] == 1
        assert saved.json()["target_key"] == resolved["target_key"]

        detail = client.get(f"/api/v1/projects/{project['id']}").json()
        item = detail["items"][0]
        assert item["family_id"] is None
        assert item["target_id"] == resolved["target_id"]
        assert item["target_key"] == resolved["target_key"]
        assert item["inchikey"] and item["canonical_smiles"]
        assert item["dataset_versions"]
        # Reopening shows it, and it is not reported as missing data.
        assert item["record_missing"] is False

    def test_out_of_scope_compound_is_refused_with_422(self, client, resolved):
        project = client.post("/api/v1/projects", json={"name": f"ONLINE-00 scope {uuid.uuid4()}"}).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/candidates",
            json={"target_id": resolved["target_id"], "compound_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 422
        assert "not recorded candidates" in response.json()["detail"]

    def test_empty_selection_is_refused(self, client, resolved):
        project = client.post("/api/v1/projects", json={"name": f"ONLINE-00 empty {uuid.uuid4()}"}).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/candidates",
            json={"target_id": resolved["target_id"], "compound_ids": []},
        )
        assert response.status_code == 422

    def test_unknown_project_is_404(self, client, resolved, investigated):
        candidates = client.get(f"/api/v1/targets/{resolved['target_id']}/candidates").json()
        response = client.post(
            f"/api/v1/projects/{uuid.uuid4()}/candidates",
            json={
                "target_id": resolved["target_id"],
                "compound_ids": [candidates["items"][0]["compound_id"]],
            },
        )
        assert response.status_code == 404


class TestCandidateExport:
    """ONLINE-00 acceptance: a candidate with no patent mapping must be
    exportable, with its target scope and evidence class preserved."""

    def test_candidate_export_scopes_to_the_target(self, client, investigated, resolved):
        candidates = client.get(
            f"/api/v1/targets/{resolved['target_id']}/candidates",
            params={"include_all_modalities": True},
        ).json()
        compound_id = candidates["items"][0]["compound_id"]
        response = client.post(
            "/api/v1/export",
            json={
                "target_id": resolved["target_id"],
                "compound_ids": [compound_id],
                "format": "csv",
            },
        )
        assert response.status_code == 200, response.text
        assert response.headers["X-Spago-Export-Rows"] == "1"
        body = response.text
        header, row = body.strip().splitlines()[0], body.strip().splitlines()[1]
        assert "target_key" in header and "evidence_class" in header and "modality" in header
        assert "TSLP" in row
        assert row.rstrip(",").endswith(("functional_effect", "measured_direct_binding", "unspecified"))
        # No patent mapping: the patent columns are empty rather than fabricated.
        fields = dict(zip(header.split(","), row.split(",")))
        assert fields["patent_numbers"] == ""
        assert fields["patent_labels"] == ""

    def test_sdf_candidate_export_carries_the_target_properties(self, client, investigated, resolved):
        response = client.post(
            "/api/v1/export",
            json={
                "target_id": resolved["target_id"],
                "format": "sdf",
                "include_all_modalities": True,
            },
        )
        assert response.status_code == 200, response.text
        # RDKit's SDWriter emits ">  <prop>  (n) " headers.
        assert "<target_key>" in response.text
        assert "<evidence_class>" in response.text
        assert "<modality>" in response.text
        assert "Thymic stromal lymphopoietin" in response.text

    def test_candidate_export_defaults_to_the_small_molecule_focus(self, client, investigated, resolved):
        focused = client.post(
            "/api/v1/export", json={"target_id": resolved["target_id"], "format": "csv"}
        )
        expanded = client.post(
            "/api/v1/export",
            json={
                "target_id": resolved["target_id"],
                "format": "csv",
                "include_all_modalities": True,
            },
        )
        assert focused.status_code == 200 and expanded.status_code == 200
        assert int(focused.headers["X-Spago-Export-Rows"]) <= int(
            expanded.headers["X-Spago-Export-Rows"]
        )

    def test_an_out_of_scope_compound_is_refused(self, client, investigated, resolved):
        response = client.post(
            "/api/v1/export",
            json={
                "target_id": resolved["target_id"],
                "compound_ids": [str(uuid.uuid4())],
                "format": "csv",
            },
        )
        assert response.status_code == 422
        assert "not candidates of this target" in response.json()["detail"]

    def test_exactly_one_scope_is_required(self, client, investigated, resolved):
        both = client.post(
            "/api/v1/export",
            json={"target_id": resolved["target_id"], "family_id": str(uuid.uuid4()), "format": "csv"},
        )
        assert both.status_code == 422
        assert "exactly one export scope" in both.json()["detail"].lower()
        neither = client.post("/api/v1/export", json={"format": "csv"})
        assert neither.status_code == 422

    def test_unknown_target_is_404(self, client):
        response = client.post(
            "/api/v1/export", json={"target_id": str(uuid.uuid4()), "format": "csv"}
        )
        assert response.status_code == 404
