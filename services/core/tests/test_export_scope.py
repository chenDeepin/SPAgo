"""Export scope correctness (product-readiness PROD-02).

The motivating defect: with a structure filter active showing 1 result, the
"Current results" export still exported the whole family (10 rows). These
tests pin the scope contract:

- structure-query exports re-run server-side and equal the full match set
  (including matches beyond the loaded page), never the unfiltered family;
- family/document/selection exports equal their declared scope;
- mentions and evidence are aggregated within the requested scope only — a
  compound occurring in another family never exports that family's records;
- the synchronous cap is enforced during the counting phase;
- out-of-scope selected ids are rejected, not silently dropped.
"""
from __future__ import annotations

import csv as csvmod
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from spago_core.db import run_migrations
from spago_core.seed import seed
from conftest import _family_id, compound_id_by_inchikey
from test_paging_beyond_cap import N_COMPOUNDS, _build_fixture  # 601-compound family

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def scope_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    """Demo fixture + the 601-compound paging fixture in one scratch DB."""
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    seed(pg_engine, _build_fixture(), migrations_dir)
    return pg_engine


def _client(engine) -> TestClient:
    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def _demo_family(engine) -> str:
    return str(_family_id(engine))


def _cap_family(engine) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT id FROM patent_families WHERE family_key = 'CAP-FAMILY-1'")
            ).scalar_one()
        )


def _csv_rows(res) -> list[dict]:
    assert res.status_code == 200, res.text
    return list(csvmod.DictReader(io.StringIO(res.text)))


def _keys(rows: list[dict]) -> set[str]:
    return {r["inchikey"] for r in rows}


class TestStructureScope:
    def test_regression_structure_filter_export_not_whole_family(self, scope_engine):
        """The PROD-02 defect (observed in the browser): a `[Na+]` structure
        filter shows 1 result, but "Current results" exported all 10 family
        compounds. The structure-scoped export must return exactly 1 row."""
        engine = scope_engine
        client = _client(engine)
        fid = _demo_family(engine)

        search = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "[Na+]", "limit": 100},
        ).json()
        assert search["total"] == 1

        res = client.post(
            "/api/v1/export",
            json={
                "family_id": fid,
                "structure_query": {"mode": "substructure", "smiles": "[Na+]"},
                "format": "csv",
            },
        )
        rows = _csv_rows(res)
        assert res.headers["X-Spago-Export-Rows"] == "1"
        assert len(rows) == 1
        assert _keys(rows) == {i["compound"]["inchikey"] for i in search["items"]}

    def test_structure_export_covers_matches_beyond_loaded_pages(self, scope_engine):
        """601 matches, first server page is 100: the export must contain all
        601, not only what a browser has loaded."""
        engine = scope_engine
        client = _client(engine)
        fid = _cap_family(engine)

        first_page = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C(=O)O", "limit": 100},
        ).json()
        assert first_page["total"] == N_COMPOUNDS

        res = client.post(
            "/api/v1/export",
            json={
                "family_id": fid,
                "structure_query": {"mode": "substructure", "smiles": "C(=O)O"},
                "format": "csv",
            },
        )
        rows = _csv_rows(res)
        assert len(rows) == N_COMPOUNDS
        assert res.headers["X-Spago-Export-Rows"] == str(N_COMPOUNDS)
        # Every paged search key is exported, exactly once.
        assert len(_keys(rows)) == N_COMPOUNDS
        assert _keys(rows) >= {i["compound"]["inchikey"] for i in first_page["items"]}

    def test_structure_export_similarity_mode_uses_threshold(self, scope_engine):
        engine = scope_engine
        client = _client(engine)
        fid = _cap_family(engine)
        search = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "similarity", "smiles": "CC(=O)O", "threshold": 0.4, "limit": 1},
        ).json()
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": fid,
                "structure_query": {
                    "mode": "similarity",
                    "smiles": "CC(=O)O",
                    "threshold": 0.4,
                },
                "format": "csv",
            },
        )
        assert res.headers["X-Spago-Export-Rows"] == str(search["total"])

    def test_invalid_structure_query_is_422(self, scope_engine):
        engine = scope_engine
        client = _client(engine)
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": _demo_family(engine),
                "structure_query": {"mode": "exact", "smiles": "not-a-smiles!!"},
                "format": "csv",
            },
        )
        assert res.status_code == 422

    def test_sdf_structure_export_counts_match(self, scope_engine):
        engine = scope_engine
        client = _client(engine)
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": _demo_family(engine),
                "structure_query": {"mode": "substructure", "smiles": "c1ccccc1"},
                "format": "sdf",
            },
        )
        assert res.status_code == 200
        assert res.headers["X-Spago-Export-Rows"] == str(res.text.count("$$$$"))


class TestDeclaredScopes:
    def test_family_document_selection_exports_equal_their_scopes(self, scope_engine):
        engine = scope_engine
        client = _client(engine)
        fid = _demo_family(engine)
        with engine.connect() as conn:
            doc = conn.execute(
                text(
                    "SELECT id, publication_number FROM patent_documents "
                    "WHERE family_id = :f ORDER BY publication_number"
                ),
                {"f": fid},
            ).first()
            family_keys = set(
                conn.execute(
                    text(
                        """
                        SELECT DISTINCT c.inchikey FROM compounds c
                        JOIN compound_mentions m ON m.compound_id = c.id
                        JOIN patent_documents d ON d.id = m.document_id
                        WHERE d.family_id = :f
                        """
                    ),
                    {"f": fid},
                ).scalars()
            )
            doc_keys = set(
                conn.execute(
                    text(
                        """
                        SELECT DISTINCT c.inchikey FROM compounds c
                        JOIN compound_mentions m ON m.compound_id = c.id
                        WHERE m.document_id = :d
                        """
                    ),
                    {"d": doc[0]},
                ).scalars()
            )

        family_rows = _csv_rows(
            client.post("/api/v1/export", json={"family_id": fid, "format": "csv"})
        )
        assert _keys(family_rows) == family_keys

        doc_rows = _csv_rows(
            client.post(
                "/api/v1/export",
                json={"family_id": fid, "document_id": str(doc[0]), "format": "csv"},
            )
        )
        assert _keys(doc_rows) == doc_keys
        # Document scope also narrows the aggregated patent numbers.
        for row in doc_rows:
            assert doc[1] in row["patent_numbers"].split("|")

        target = sorted(family_keys)[0]
        target_id = str(compound_id_by_inchikey(engine, target))
        sel_rows = _csv_rows(
            client.post(
                "/api/v1/export",
                json={"family_id": fid, "compound_ids": [target_id], "format": "csv"},
            )
        )
        assert _keys(sel_rows) == {target}

    def test_selection_from_beyond_the_first_page_exports_fully(self, scope_engine):
        """Selected ids from server page 6 (offset 500+) export correctly."""
        engine = scope_engine
        client = _client(engine)
        fid = _cap_family(engine)
        page6 = client.get(f"/api/v1/families/{fid}/compounds?offset=500&limit=100").json()
        ids = [i["compound"]["id"] for i in page6["items"][:3]]
        keys = {i["compound"]["inchikey"] for i in page6["items"][:3]}

        res = client.post(
            "/api/v1/export",
            json={"family_id": fid, "compound_ids": ids, "format": "csv"},
        )
        rows = _csv_rows(res)
        assert _keys(rows) == keys
        assert res.headers["X-Spago-Export-Rows"] == "3"


class TestScopeIsolation:
    @pytest.fixture()
    def second_family(self, scope_engine):
        """A molecule from DEMO-FAMILY-1 also occurs in another family; the
        other family carries its own mention and evidence for it."""
        engine = scope_engine
        with engine.connect() as conn:
            cid = conn.execute(
                text(
                    "SELECT c.id, c.inchikey FROM compounds c "
                    "WHERE c.inchikey = 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N'"
                )
            ).first()
        family, doc, mention, evidence = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_families (id, family_key, title, source_name,
                                                 dataset_version, retrieved_at)
                    VALUES (:f, 'OTHER-FAMILY-9', 'Other family (synthetic)', 'fixture',
                            'demo-fixture-v1', now())
                    """
                ),
                {"f": family},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, title,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:d, :f, 'OTHER-PATENT-9', 'Other doc (synthetic)', 'fixture',
                            'demo-fixture-v1', now())
                    """
                ),
                {"d": doc, "f": family},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO compound_mentions (id, compound_id, document_id, patent_label,
                                                   source_name, dataset_version, retrieved_at)
                    VALUES (:m, :c, :d, 'Other 99', 'fixture', 'demo-fixture-v1', now())
                    """
                ),
                {"m": mention, "c": cid[0], "d": doc},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO evidence_records (id, compound_id, compound_mention_id, document_id,
                                                  source_type, raw_excerpt, extraction_method,
                                                  provenance_state, dataset_version, retrieved_at)
                    VALUES (:e, :c, :m, :d, 'claim', 'Other-family evidence (synthetic).',
                            'fixture', 'machine_extracted', 'demo-fixture-v1', now())
                    """
                ),
                {"e": evidence, "c": cid[0], "m": mention, "d": doc},
            )
        yield {"family": family, "doc": doc, "compound": cid[0], "inchikey": cid[1], "evidence": evidence}
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM patent_families WHERE id = :f"), {"f": family})

    def test_family_export_excludes_other_familys_records(self, scope_engine, second_family):
        engine = scope_engine
        client = _client(engine)
        fid = _demo_family(engine)
        rows = _csv_rows(
            client.post(
                "/api/v1/export",
                json={
                    "family_id": fid,
                    "compound_ids": [str(second_family["compound"])],
                    "format": "csv",
                },
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert "OTHER-PATENT-9" not in row["patent_numbers"]
        assert "OTHER-PATENT-9" not in row["patent_labels"]
        assert str(second_family["evidence"]) not in row["evidence_records"].split("|")

    def test_other_family_export_includes_its_own_records(self, scope_engine, second_family):
        engine = scope_engine
        client = _client(engine)
        rows = _csv_rows(
            client.post(
                "/api/v1/export",
                json={"family_id": str(second_family["family"]), "format": "csv"},
            )
        )
        assert len(rows) == 1
        assert rows[0]["patent_numbers"] == "OTHER-PATENT-9"
        assert rows[0]["patent_labels"].endswith("Other 99")
        assert rows[0]["evidence_records"]  # its own evidence is present
        # …and the demo family's documents are not attributed here.
        assert "DEMO-PATENT-A" not in rows[0]["patent_numbers"]

    def test_export_versions_follow_scoped_mentions(self, scope_engine, second_family):
        with scope_engine.begin() as conn:
            conn.execute(text("UPDATE compound_mentions SET dataset_version = 'other-source-v2' "
                              "WHERE document_id = :doc"), {"doc": second_family["doc"]})
        client = _client(scope_engine)
        rows = _csv_rows(client.post(
            "/api/v1/export", json={"family_id": str(second_family["family"]), "format": "csv"}
        ))
        assert rows[0]["dataset_version"] == "other-source-v2"
        assert json.loads(rows[0]["dataset_versions"]) == [
            {"source_name": "fixture", "dataset_version": "other-source-v2"}
        ]
        # The shared molecule's first ingestion version must not replace this source.
        assert "demo-fixture-v1" not in rows[0]["dataset_versions"]

    def test_family_and_document_rows_keep_only_scoped_mentions(self, scope_engine, second_family):
        client = _client(scope_engine)
        fid = _demo_family(scope_engine)
        response = client.get(f"/api/v1/families/{fid}/compounds")
        assert response.status_code == 200
        row = next(item for item in response.json()["items"]
                   if item["compound"]["id"] == str(second_family["compound"]))
        assert {m["publication_number"] for m in row["mentions"]} == {"DEMO-PATENT-A", "DEMO-PATENT-B"}
        doc = row["mentions"][0]["document_id"]
        response = client.get(f"/api/v1/families/{fid}/compounds", params={"document_id": doc})
        row = next(item for item in response.json()["items"]
                   if item["compound"]["id"] == str(second_family["compound"]))
        assert {m["document_id"] for m in row["mentions"]} == {doc}
        result = client.post(f"/api/v1/families/{fid}/structure-search", json={
            "mode": "exact", "smiles": row["compound"]["canonical_smiles"], "document_id": doc,
        })
        assert result.status_code == 200
        assert {m["document_id"] for m in result.json()["items"][0]["mentions"]} == {doc}

    def test_structure_hit_beyond_first_500_hydrates_only_query_scope(self, scope_engine, second_family):
        client = _client(scope_engine)
        fid = _cap_family(scope_engine)
        last = client.get(f"/api/v1/families/{fid}/compounds?offset=600&limit=1").json()["items"][0]
        target = last["compound"]
        original_doc = last["mentions"][0]["document_id"]
        extra_doc = uuid.uuid4()
        with scope_engine.begin() as conn:
            conn.execute(text("INSERT INTO patent_documents "
                              "(id, family_id, publication_number, source_name, dataset_version, retrieved_at) "
                              "VALUES (:id, :fid, :number, 'synthetic-fixture', 'synthetic-v1', now())"),
                         {"id": extra_doc, "fid": fid, "number": f"EXTRA-{extra_doc}"})
            for doc in (extra_doc, second_family["doc"]):
                conn.execute(text("INSERT INTO compound_mentions "
                                  "(id, compound_id, document_id, patent_label, source_name, dataset_version, retrieved_at) "
                                  "VALUES (:id, :cid, :doc, 'Other occurrence', 'synthetic-fixture', 'synthetic-v1', now())"),
                             {"id": uuid.uuid4(), "cid": target["id"], "doc": doc})
        try:
            result = client.post(f"/api/v1/families/{fid}/structure-search", json={
                "mode": "exact", "smiles": target["canonical_smiles"], "document_id": original_doc,
            })
            assert result.status_code == 200
            hit = result.json()["items"][0]
            assert hit["compound"]["id"] == target["id"]
            assert {m["document_id"] for m in hit["mentions"]} == {original_doc}
            family = client.post(f"/api/v1/families/{fid}/structure-search", json={
                "mode": "exact", "smiles": target["canonical_smiles"],
            })
            assert family.status_code == 200
            assert {m["document_id"] for m in family.json()["items"][0]["mentions"]} == {
                original_doc, str(extra_doc)
            }
        finally:
            with scope_engine.begin() as conn:
                conn.execute(text("DELETE FROM patent_documents WHERE id = :id"), {"id": extra_doc})


class TestLimitsAndContracts:
    def test_cap_is_enforced_in_the_counting_phase(self, scope_engine, monkeypatch):
        from spago_core.services import export as export_svc

        engine = scope_engine
        client = _client(engine)
        fid = _cap_family(engine)  # 601 compounds
        monkeypatch.setattr(export_svc, "MAX_EXPORT_ROWS", 500)
        res = client.post("/api/v1/export", json={"family_id": fid, "format": "csv"})
        assert res.status_code == 422
        assert "synchronous limit" in res.json()["detail"]
        assert "601" in res.json()["detail"]

        # Just under the cap still exports.
        monkeypatch.setattr(export_svc, "MAX_EXPORT_ROWS", 601)
        res = client.post("/api/v1/export", json={"family_id": fid, "format": "csv"})
        assert res.status_code == 200
        assert res.headers["X-Spago-Export-Rows"] == "601"

    def test_structure_query_over_cap_rejected(self, scope_engine, monkeypatch):
        from spago_core.services import export as export_svc

        engine = scope_engine
        client = _client(engine)
        fid = _cap_family(engine)
        monkeypatch.setattr(export_svc, "MAX_EXPORT_ROWS", 500)
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": fid,
                "structure_query": {"mode": "substructure", "smiles": "C(=O)O"},
                "format": "csv",
            },
        )
        assert res.status_code == 422
        assert "601" in res.json()["detail"]

    def test_out_of_scope_selection_is_rejected(self, scope_engine):
        engine = scope_engine
        client = _client(engine)
        demo_fid = _demo_family(engine)
        with engine.connect() as conn:
            other_cid = conn.execute(
                text(
                    """
                    SELECT c.id FROM compounds c
                    JOIN compound_mentions m ON m.compound_id = c.id
                    JOIN patent_documents d ON d.id = m.document_id
                    JOIN patent_families f ON f.id = d.family_id
                    WHERE f.family_key = 'CAP-FAMILY-1' LIMIT 1
                    """
                )
            ).scalar_one()
        res = client.post(
            "/api/v1/export",
            json={"family_id": demo_fid, "compound_ids": [str(other_cid)], "format": "csv"},
        )
        assert res.status_code == 422
        assert "outside the requested family scope" in res.json()["detail"]

    def test_export_requires_a_family(self, scope_engine):
        client = _client(scope_engine)
        res = client.post("/api/v1/export", json={"format": "csv"})
        assert res.status_code == 422

    def test_export_header_row_includes_source_urls_column(self, scope_engine):
        client = _client(scope_engine)
        res = client.post(
            "/api/v1/export",
            json={"family_id": _demo_family(scope_engine), "format": "csv"},
        )
        header = res.text.splitlines()[0].split(",")
        assert "evidence_source_urls" in header


    @pytest.mark.parametrize("mode,smiles", [("substructure", "C(=O)O"), ("similarity", "CC(=O)O")])
    def test_over_cap_structure_scope_does_not_fetch_candidate_rows(self, scope_engine, monkeypatch, mode, smiles):
        from spago_core.services import export as export_svc

        monkeypatch.setattr(export_svc, "MAX_EXPORT_ROWS", 1)
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if "WITH matched AS" in statement:
                statements.append(statement.strip())

        event.listen(scope_engine, "before_cursor_execute", record)
        try:
            res = _client(scope_engine).post("/api/v1/export", json={
                "family_id": _cap_family(scope_engine), "format": "csv",
                "structure_query": {"mode": mode, "smiles": smiles, "threshold": 0.3},
            })
        finally:
            event.remove(scope_engine, "before_cursor_execute", record)
        assert res.status_code == 422, res.text
        assert statements
        assert all(statement.startswith("SELECT count(*)") for statement in statements)

    def test_empty_explicit_selection_never_expands_to_family(self, scope_engine):
        res = _client(scope_engine).post("/api/v1/export", json={
            "family_id": _demo_family(scope_engine), "compound_ids": [], "format": "csv",
            "structure_query": {"mode": "substructure", "smiles": "C"},
        })
        assert _csv_rows(res) == []
        assert res.headers["X-Spago-Export-Rows"] == "0"

    def test_foreign_document_is_rejected_even_without_selection(self, scope_engine):
        res = _client(scope_engine).post("/api/v1/export", json={
            "family_id": _demo_family(scope_engine), "document_id": str(uuid.uuid4()), "format": "csv",
        })
        assert res.status_code == 422
        assert "document" in res.json()["detail"]


class TestRendering:
    def test_invalid_stored_structure_fails_sdf_instead_of_silent_omission(self):
        from spago_core.services.export import ExportRow, ExportScopeError, render_sdf

        row = ExportRow(
            compound_id=uuid.uuid4(), inchikey="synthetic-invalid", canonical_smiles="not-a-smiles!!",
            molecular_formula=None, molecular_weight=None, hbd=None, hba=None, tpsa=None, logp=None,
            patent_numbers=[], patent_labels=[], evidence_ids=[], provenance_states=[],
            evidence_source_urls=[], dataset_version="synthetic-test-v1",
        )
        with pytest.raises(ExportScopeError, match="SDF export was not created"):
            render_sdf([row])
