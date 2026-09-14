"""M2 structure-search tests: chemistry correctness against the cartridge.

Covers the AGENTS.md §28 regression classes: identical molecule, stereo
isomers, substructure positive/negative, high/low similarity pairs, malformed
query, and stereo-preserving substructure matching.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.db import run_migrations
from spago_core.chemistry import StructureParseError
from spago_core.seed import seed
from spago_core.services import structure_search as ss
from conftest import _family_id

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
ASPIRIN_ALT = "O=C(O)c1ccccc1OC(C)=O"
SALICYLIC = "O=C(O)c1ccccc1O"
S_IBU = "CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O"
S_IBU_INVERTED = "CC(C)Cc1ccc(cc1)[C@H](C)C(=O)O"
RAC_IBU = "CC(C)Cc1ccc(cc1)C(C)C(=O)O"
CAFFEINE = "Cn1c(=O)c2c(ncn2C)n(C)c1=O"
THIOPHENE = "c1ccsc1"


@pytest.fixture(scope="module")
def m2_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


def _search(engine, smiles: str, mode: str, **kw):
    fid = _family_id(engine)
    return ss.search_family_structures(engine, fid, smiles, ss.SearchMode(mode), **kw)


class TestExactSearch:
    def test_identical_molecule_via_alternate_smiles(self, m2_engine):
        res = _search(m2_engine, ASPIRIN_ALT, "exact")
        assert res.total == 1
        assert [r["inchikey"] for r in res.rows] == ["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"]

    def test_stereo_query_matches_only_same_stereoisomer(self, m2_engine):
        res = _search(m2_engine, S_IBU, "exact")
        assert res.total == 1
        assert res.rows[0]["inchikey"] == "HEFNNWSXXWATRW-SNVBAGLBSA-N"

    def test_racemic_query_excludes_stereo_specified(self, m2_engine):
        res = _search(m2_engine, RAC_IBU, "exact")
        assert res.total == 1
        assert res.rows[0]["inchikey"] == "HEFNNWSXXWATRW-UHFFFAOYSA-N"

    def test_malformed_query_raises(self, m2_engine):
        with pytest.raises(StructureParseError):
            _search(m2_engine, "N=C(N)not-a-molecule", "exact")

    def test_empty_query_raises(self, m2_engine):
        with pytest.raises(StructureParseError):
            _search(m2_engine, "   ", "exact")


class TestSubstructureSearch:
    def test_positive_carboxylic_acid(self, m2_engine):
        res = _search(m2_engine, "C(=O)O", "substructure")
        keys = {r["inchikey"] for r in res.rows}
        # aspirin, racemic + S ibuprofen, naproxen, salicylic acid
        assert "BSYNRYMUTXBXSQ-UHFFFAOYSA-N" in keys
        assert "HEFNNWSXXWATRW-UHFFFAOYSA-N" in keys
        assert "CMWTZPSULFXXJA-SECBINFHSA-N" in keys
        assert "YGSDEFSMJLZEOE-UHFFFAOYSA-N" in keys
        # caffeine has no carboxylic acid
        assert "RYYVLZVUVIJVGH-UHFFFAOYSA-N" not in keys

    def test_negative_no_match(self, m2_engine):
        res = _search(m2_engine, THIOPHENE, "substructure")
        assert res.total == 0
        assert res.rows == []

    def test_stereo_preserved_where_specified(self, m2_engine):
        # Same connectivity, inverted chirality: must NOT match the fixture's
        # [C@@H] stereocenter once chirality-aware re-check applies.
        res = _search(m2_engine, S_IBU_INVERTED, "substructure")
        keys = {r["inchikey"] for r in res.rows}
        assert "HEFNNWSXXWATRW-SNVBAGLBSA-N" not in keys

        # The correctly specified query does match its stereoisomer.
        res_ok = _search(m2_engine, S_IBU, "substructure")
        assert "HEFNNWSXXWATRW-SNVBAGLBSA-N" in {r["inchikey"] for r in res_ok.rows}

    def test_molecule_filters_apply(self, m2_engine):
        res = _search(m2_engine, "C(=O)O", "substructure", filters=ss.MoleculeFilters(mw_max=200))
        assert all(r["molecular_weight"] <= 200 for r in res.rows)

    def test_document_scope_narrows(self, m2_engine):
        fid = _family_id(m2_engine)
        overview = ss_get_overview(m2_engine, fid)
        doc_a = next(d for d in overview.documents if d.publication_number == "DEMO-PATENT-A")
        res = ss.search_family_structures(
            m2_engine, fid, "C(=O)O", ss.SearchMode.SUBSTRUCTURE, document_id=doc_a.id
        )
        # Only compounds mentioned in document A may appear.
        assert {r["inchikey"] for r in res.rows} <= {
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",  # aspirin
            "HEFNNWSXXWATRW-UHFFFAOYSA-N",  # racemic ibuprofen
        }


def ss_get_overview(engine, fid):
    from spago_core.services import get_family_overview

    return get_family_overview(engine, fid)


class TestSimilaritySearch:
    def test_self_match_with_full_score(self, m2_engine):
        res = _search(m2_engine, ASPIRIN, "similarity", threshold=0.9)
        assert res.rows[0]["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        assert res.scores["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"] == pytest.approx(1.0)

    def test_high_similarity_pair_included_low_excluded(self, m2_engine):
        res = _search(m2_engine, ASPIRIN, "similarity", threshold=0.3)
        keys = {r["inchikey"] for r in res.rows}
        # salicylic acid (parent scaffold) is a high-similarity neighbor
        assert "YGSDEFSMJLZEOE-UHFFFAOYSA-N" in keys
        # caffeine is structurally distant from aspirin
        assert "RYYVLZVUVIJVGH-UHFFFAOYSA-N" not in keys

    def test_threshold_narrows_results(self, m2_engine):
        broad = _search(m2_engine, ASPIRIN, "similarity", threshold=0.3)
        narrow = _search(m2_engine, ASPIRIN, "similarity", threshold=0.9)
        assert narrow.total <= broad.total
        assert broad.threshold == 0.3 and narrow.threshold == 0.9

    def test_threshold_clamped_to_bounds(self, m2_engine):
        res = _search(m2_engine, ASPIRIN, "similarity", threshold=0.01)
        assert res.threshold == ss.MIN_SIMILARITY_THRESHOLD


class TestStructureSearchApi:
    def test_exact_search_endpoint(self, m2_engine):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = m2_engine
        client = TestClient(app)
        res = client.post(
            f"/api/v1/families/{_family_id(m2_engine)}/structure-search",
            json={"mode": "exact", "smiles": "O=C(O)c1ccccc1OC(C)=O"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "exact"
        assert body["total"] == 1
        assert body["items"][0]["compound"]["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        assert body["query_canonical_smiles"]  # canonicalized server-side

    def test_invalid_query_is_422_with_reason(self, m2_engine):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = m2_engine
        client = TestClient(app)
        res = client.post(
            f"/api/v1/families/{_family_id(m2_engine)}/structure-search",
            json={"mode": "substructure", "smiles": "not-a-molecule"},
        )
        assert res.status_code == 422
        assert "parse" in res.json()["detail"].lower()

    def test_unknown_family_is_404(self, m2_engine):
        from fastapi.testclient import TestClient
        import uuid as uuid_mod

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = m2_engine
        client = TestClient(app)
        res = client.post(
            f"/api/v1/families/{uuid_mod.uuid4()}/structure-search",
            json={"mode": "exact", "smiles": "CCO"},
        )
        assert res.status_code == 404
