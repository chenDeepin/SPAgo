"""B-33: target screen/export filter and potency-policy parity.

The motivating defect (reproduced in the browser on the IL6 investigation):
with the candidate table filtered to ``measured direct binding`` and the
threshold changed to 1 nM, "Current candidates (141)" exported all 157
unfiltered rows, and every row's ``reference_threshold_nM`` read 10000 — the
deployment default — instead of the policy the screen stated.

These tests pin the parity contract between the candidate screen and the
export:

- an export scoped to the current results carries the screen's evidence-class
  filter and matches that filtered candidate set exactly, across modalities;
- the threshold override is the policy behind the file's class columns, for
  both the results scope and an explicit selection;
- an explicit selection is not re-filtered (selection wins, the same contract
  modality follows), while still exporting under the stated policy;
- an unknown evidence class is refused rather than ignored.
"""
from __future__ import annotations

import csv
import io
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

EVIDENCE_CLASSES = [
    "measured_direct_binding",
    "interaction_disruption",
    "functional_effect",
    "screening_assay",
    "unspecified",
]


@pytest.fixture(scope="module")
def b33_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_tables(b33_engine):
    with b33_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


@pytest.fixture()
def client(b33_engine):
    app = create_app()
    app.state.engine = b33_engine
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
def investigated(client) -> dict:
    resolved = client.post("/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"})
    assert resolved.status_code == 200, resolved.text
    response = client.post(
        "/api/v1/targets/discover", json={"target_id": resolved.json()["target_id"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _screen_keys(client, target_id: str, evidence_class: str | None) -> set[str]:
    """InChIKeys of the screen's filtered set, so export rows are compared by
    the identity the file actually carries."""
    params = {"include_all_modalities": "true", "limit": 500}
    if evidence_class:
        params["evidence_class"] = evidence_class
    page = client.get(f"/api/v1/targets/{target_id}/candidates", params=params).json()
    # Pinned outsiders are labelled, not part of the filter's scope.
    return {i["inchikey"] for i in page["items"] if not i.get("outside_filter")}


def _export_ids(client, target_id: str, **extra) -> tuple[set[str], list[dict]]:
    body = {"target_id": target_id, "include_all_modalities": True, "format": "csv", **extra}
    res = client.post("/api/v1/export", json=body)
    assert res.status_code == 200, res.text
    rows = list(csv.DictReader(io.StringIO(res.text)))
    return {r["inchikey"] for r in rows}, rows


class TestResultsScopeParity:
    def test_filtered_export_equals_the_filtered_screen_set(self, client, investigated):
        """For every class the stored data actually has, the file's compound
        set equals the screen's filtered set — the whole point of B-33."""
        target_id = investigated["target_id"]
        for evidence_class in EVIDENCE_CLASSES:
            screen = _screen_keys(client, target_id, evidence_class)
            exported, _rows = _export_ids(
                client, target_id, evidence_class=evidence_class
            )
            assert exported == screen, f"export != screen for {evidence_class}"

    def test_the_filter_narrows_the_exported_scope(self, client, investigated, b33_engine):
        """The fixture must discriminate: at least one class's set is a strict
        subset of the unfiltered scope, and the filtered export drops exactly
        those rows. Without this, parity above could pass on an empty filter."""
        target_id = investigated["target_id"]
        unfiltered_screen = _screen_keys(client, target_id, None)
        subsets = [
            c
            for c in EVIDENCE_CLASSES
            if _screen_keys(client, target_id, c) < unfiltered_screen
        ]
        if not subsets:
            pytest.fail(
                "fixture lost its discriminating power: no evidence class is a "
                "strict subset of the candidate scope"
            )
        evidence_class = subsets[0]
        exported, _rows = _export_ids(client, target_id, evidence_class=evidence_class)
        assert exported < unfiltered_screen

    def test_default_modality_focus_and_evidence_filter_combine(self, client, investigated):
        """The table's default small-molecule focus plus the evidence filter is
        one scope: the export equals that screen without `include_all_modalities`."""
        target_id = investigated["target_id"]
        params = {"limit": 500, "evidence_class": "measured_direct_binding"}
        screen = {
            i["inchikey"]
            for i in client.get(
                f"/api/v1/targets/{target_id}/candidates", params=params
            ).json()["items"]
            if not i.get("outside_filter")
        }
        res = client.post(
            "/api/v1/export",
            json={
                "target_id": target_id,
                "evidence_class": "measured_direct_binding",
                "format": "csv",
            },
        )
        assert res.status_code == 200, res.text
        rows = list(csv.DictReader(io.StringIO(res.text)))
        assert {r["inchikey"] for r in rows} == screen


class TestPolicyParity:
    def test_threshold_override_travels_to_the_file(self, client, investigated):
        """The browser defect's second half: a 1 nM workspace exported under
        the 10000 nM default. Every row must state the requested policy."""
        target_id = investigated["target_id"]
        _keys, rows = _export_ids(
            client, target_id, activity_threshold_nm=1, evidence_class=None
        )
        assert rows, "fixture produced no exportable candidates"
        assert {r["reference_threshold_nM"] for r in rows} == {"1"}
        assert {r["reference_policy_version"] for r in rows} == {"potency-gate-v1"}

    def test_default_export_keeps_the_deployment_threshold(self, client, investigated):
        _keys, rows = _export_ids(client, investigated["target_id"])
        assert rows
        assert {r["reference_threshold_nM"] for r in rows} == {"10000"}


class TestSelectionScope:
    def test_selection_is_not_refiltered_but_carries_the_policy(self, client, investigated):
        """Selection wins over the evidence-class filter — the chosen rows
        export even when the filter would exclude them — while the file's class
        columns are computed under the requested threshold."""
        target_id = investigated["target_id"]
        unfiltered = _screen_keys(client, target_id, None)
        filtered = _screen_keys(client, target_id, "measured_direct_binding")
        excluded = sorted(unfiltered - filtered)
        if not excluded:
            pytest.skip("fixture has no candidate outside measured_direct_binding")
        page = client.get(
            f"/api/v1/targets/{target_id}/candidates",
            params={"include_all_modalities": "true", "limit": 500},
        ).json()
        by_key = {i["inchikey"]: i["compound_id"] for i in page["items"]}
        chosen = by_key[excluded[0]]
        res = client.post(
            "/api/v1/export",
            json={
                "target_id": target_id,
                "compound_ids": [chosen],
                "evidence_class": "measured_direct_binding",
                "activity_threshold_nm": 1,
                "format": "csv",
            },
        )
        assert res.status_code == 200, res.text
        rows = list(csv.DictReader(io.StringIO(res.text)))
        assert len(rows) == 1
        assert rows[0]["inchikey"] == excluded[0]
        assert rows[0]["reference_threshold_nM"] == "1"


class TestContract:
    def test_unknown_evidence_class_is_refused(self, client, investigated):
        res = client.post(
            "/api/v1/export",
            json={
                "target_id": investigated["target_id"],
                "evidence_class": "totally_made_up",
                "format": "csv",
            },
        )
        assert res.status_code == 422

    def test_filter_on_a_family_scope_is_refused(self, client, investigated, b33_engine):
        """`evidence_class` is a target-candidate concept; a family export that
        sends it is a caller confusion and must not pass silently."""
        with b33_engine.begin() as conn:
            fid = conn.execute(
                text(
                    "INSERT INTO patent_families (id, family_key, source_name, dataset_version, retrieved_at, created_at) "
                    "VALUES (gen_random_uuid(), 'B33-FAMILY-1', 'b33-test', 'b33-test-v1', now(), now()) RETURNING id"
                )
            ).scalar_one()
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": str(fid),
                "evidence_class": "measured_direct_binding",
                "format": "csv",
            },
        )
        assert res.status_code == 422
