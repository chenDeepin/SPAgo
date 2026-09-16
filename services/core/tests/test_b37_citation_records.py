"""B-37: a summary citation names the exact record it supports.

The typed citation contract gains the owning ids so a click can resolve:
`measurement` and `evidence` citations carry `compound_id` (None only when the
evidence's mention is no longer current), and the family citation carries
`family_id`. The target-scope `candidate`/`measurement` citations already
carried compound ids; this pins that they keep doing so. What must never
happen: a citation that names a record but cannot say which compound or scope
owns it.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services import ai

from conftest import _family_id


@pytest.fixture(scope="module")
def b37_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


class TestFamilyScopeCitations:
    def test_measurement_citations_carry_their_compound(self, b37_engine):
        result = ai.summarize_family(b37_engine, _family_id(b37_engine))
        measurement_citations = [c for c in result["citations"] if c["kind"] == "measurement"]
        assert measurement_citations
        for citation in measurement_citations:
            assert citation["compound_id"], (
                f"{citation['fact_ref']} names a record without its compound"
            )
            assert str(uuid.UUID(citation["compound_id"])) == citation["compound_id"]

    def test_measurement_compound_ids_resolve_to_real_compounds(self, b37_engine):
        result = ai.summarize_family(b37_engine, _family_id(b37_engine))
        ids = {
            c["compound_id"] for c in result["citations"] if c["kind"] == "measurement"
        }
        with b37_engine.connect() as conn:
            stored = set(
                conn.execute(
                    text("SELECT id::text FROM compounds WHERE id = ANY(:ids)"),
                    {"ids": sorted(ids)},
                ).scalars()
            )
        assert stored == ids

    def test_family_citation_carries_the_family_id(self, b37_engine):
        result = ai.summarize_family(b37_engine, _family_id(b37_engine))
        family_citation = next(c for c in result["citations"] if c["kind"] == "family")
        assert family_citation["family_id"] == str(_family_id(b37_engine))

    def test_evidence_citations_state_their_compound_or_its_absence(self, b37_engine):
        """Evidence rows are compound-tied through their mention. A current
        mention yields the compound id; a retracted one yields an explicit
        None — never another compound's id."""
        snapshot = ai.summarize_family(b37_engine, _family_id(b37_engine))["input_snapshot"]
        for entry in snapshot["evidence"]:
            assert "compound_id" in entry
            if entry["compound_id"] is not None:
                assert str(uuid.UUID(entry["compound_id"])) == entry["compound_id"]


class TestTargetScopeCitations:
    @pytest.fixture()
    def target_id(self, b37_engine):
        """A stored investigation with one candidate and one measurement,
        inserted directly — the same shape the online01 summary tests use."""
        import json as jsonmod

        tid = uuid.uuid4()
        with b37_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, organism, source_name,
                                         dataset_version, retrieved_at, uniprot_accession,
                                         gene_symbol, target_type, scope_kind)
                    VALUES (:id, 'B37TGT', 'B-37 test target', 'Homo sapiens', 'uniprot',
                            'uniprot:2026-09-16', now(), 'P37370', 'B37TGT',
                            'single_protein', 'ligand')
                    """
                ),
                {"id": tid},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO source_retrievals (id, target_id, source_name, query, status,
                                                   records_seen, records_kept, retrieved_at)
                    VALUES (:id, :tid, 'chembl', CAST(:q AS jsonb), 'complete', 1, 1, now())
                    """
                ),
                {"id": uuid.uuid4(), "tid": tid, "q": jsonmod.dumps({"uniprot": "P37370"})},
            )
            compound = conn.execute(text("SELECT id FROM compounds LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, evidence_class, modality,
                                                   dataset_version, retrieved_at)
                    VALUES (:id, :tid, :cid, 'chembl', 'b37-rec-1', 'measured_direct_binding',
                            'small_molecule', 'chembl:2026-09-16', now())
                    """
                ),
                {"id": uuid.uuid4(), "tid": tid, "cid": compound},
            )
            assay = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO assays (id, assay_key, target_id, assay_type, source_name,
                                        dataset_version, retrieved_at)
                    VALUES (:id, 'B37-ASSAY-1', :tid, 'B', 'chembl', 'chembl:2026-09-16', now())
                    """
                ),
                {"id": assay, "tid": tid},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                              unit, relation, source_record_id, source_name,
                                              extraction_method, provenance_state,
                                              dataset_version, retrieved_at, evidence_class)
                    VALUES (:id, :cid, :aid, 'Kd', 12.0, 'nM', '=', 'b37-act-1', 'chembl',
                            'chembl_webclient_discovery', 'database_curated',
                            'chembl:2026-09-16', now(), 'measured_direct_binding')
                    """
                ),
                {"id": uuid.uuid4(), "cid": compound, "aid": assay},
            )
        yield tid
        with b37_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM measurements WHERE source_record_id = 'b37-act-1'")
            )
            conn.execute(text("DELETE FROM assays WHERE assay_key = 'B37-ASSAY-1'"))
            conn.execute(
                text("DELETE FROM target_candidates WHERE source_record_id = 'b37-rec-1'")
            )
            conn.execute(
                text("DELETE FROM source_retrievals WHERE target_id = :tid"), {"tid": tid}
            )
            conn.execute(text("DELETE FROM targets WHERE id = :tid"), {"tid": tid})

    def test_candidate_and_measurement_citations_carry_their_compound(self, b37_engine, target_id):
        result = ai.summarize_target(b37_engine, target_id)
        citations = result["citations"]
        assert citations
        for citation in citations:
            if citation["kind"] in ("candidate", "measurement"):
                assert citation.get("compound_id"), (
                    f"{citation['fact_ref']} names a record without its compound"
                )
        measurement = next(c for c in citations if c["kind"] == "measurement")
        with b37_engine.connect() as conn:
            stored_compound = conn.execute(
                text(
                    "SELECT mm.compound_id::text FROM measurements mm "
                    "WHERE mm.id::text = :mid"
                ),
                {"mid": measurement["measurement_id"]},
            ).scalar_one()
        assert measurement["compound_id"] == stored_compound
