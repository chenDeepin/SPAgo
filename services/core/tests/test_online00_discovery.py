"""ONLINE-00 B/C: discovery adapters, persistence, and the science the result
model must preserve.

All sources are driven from recorded payloads (`data/fixtures/open_sources/`),
so these tests are offline and deterministic. They pin the behaviours the plan
calls out explicitly:

- a source failure is never recorded as an empty success;
- no qualifying small molecules is distinguishable from no records;
- evidence classes stay conservative (percent inhibition is not binding);
- Kd/Ki/IC50/EC50 are never merged or ranked into one potency list;
- duplicates from a shared original reference are flagged;
- a measurement against an interaction target is attributed to that object;
- a candidate with no patent mapping is usable, savable and readable.
"""
from __future__ import annotations

from pathlib import Path

import re

import pytest
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.bioactivity_base import ActivityRecord
from spago_core.adapters.chembl_discovery import (
    ACTIVITY_FIELDS,
    ChEMBLDiscoveryAdapter,
    classify_evidence,
)
from spago_core.adapters.http import SourceUnavailableError
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.db import run_migrations
from spago_core.domain import EvidenceClass, RetrievalStatus, TargetType
from spago_core.services import projects as projects_svc
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_candidates,
    list_source_retrievals,
    list_target_measurements,
    modality_breakdown,
)
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubActivityAdapter, StubSourceClient, load_fixture

TSLP_ACCESSION = "Q969D9"


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_online_tables(online_engine):
    """Each test starts from an empty scientific state, so an assertion
    describes one investigation rather than the history of the test run."""
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture()
def stub_uniprot() -> UniProtTargetResolver:
    return UniProtTargetResolver(
        client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
    )


@pytest.fixture()
def stub_chembl() -> ChEMBLDiscoveryAdapter:
    return ChEMBLDiscoveryAdapter(
        client=StubSourceClient(
            {
                "target.json": load_fixture("chembl_targets_Q969D9.json"),
                "activity.json": load_fixture("chembl_activities_TSLP.json"),
            }
        )
    )


@pytest.fixture()
def stub_bindingdb() -> BindingDBRestAdapter:
    return BindingDBRestAdapter(
        client=StubSourceClient(
            {
                "getLigandsByUniprot": load_fixture("bindingdb_P05231.json"),
            }
        )
    )


@pytest.fixture()
def stub_pubchem() -> PubChemAdapter:
    return PubChemAdapter(
        client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
    )


@pytest.fixture()
def resolved_target(online_engine, stub_uniprot):
    service = TargetResolutionService(uniprot=stub_uniprot)
    outcome = service.resolve(online_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


# --- evidence classification ------------------------------------------------------


class TestEvidenceClassification:
    def test_affinity_on_a_protein_is_direct_binding(self):
        assert (
            classify_evidence("B", "Kd", TargetType.SINGLE_PROTEIN)
            is EvidenceClass.MEASURED_DIRECT_BINDING
        )
        assert (
            classify_evidence("B", "IC50", TargetType.SINGLE_PROTEIN)
            is EvidenceClass.MEASURED_DIRECT_BINDING
        )

    def test_affinity_on_an_interaction_is_interaction_evidence(self):
        assert (
            classify_evidence("B", "IC50", TargetType.PROTEIN_PROTEIN_INTERACTION)
            is EvidenceClass.INTERACTION_DISRUPTION
        )

    def test_percent_inhibition_is_never_promoted_to_binding(self):
        assert (
            classify_evidence("B", "Inhibition", TargetType.SINGLE_PROTEIN)
            is EvidenceClass.FUNCTIONAL_EFFECT
        )
        assert (
            classify_evidence("B", "% Ctrl", TargetType.SINGLE_PROTEIN)
            is EvidenceClass.FUNCTIONAL_EFFECT
        )

    def test_unclassified_endpoints_stay_unspecified(self):
        assert classify_evidence("A", "LogD", TargetType.SINGLE_PROTEIN) is EvidenceClass.UNSPECIFIED
        assert classify_evidence(None, None, None) is EvidenceClass.UNSPECIFIED


# --- adapter contract -------------------------------------------------------------


class TestChEMBLDiscovery:
    def test_targets_are_returned_with_their_own_types(self):
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient({"target.json": load_fixture("chembl_targets_P29965.json")})
        )
        result = adapter.targets_for_accession("P29965")
        assert result.status is RetrievalStatus.COMPLETE
        types = {e.identifier: e.target_type for e in result.entries}
        assert types["CHEMBL3580491"] is TargetType.SINGLE_PROTEIN
        assert types["CHEMBL4106122"] is TargetType.PROTEIN_PROTEIN_INTERACTION
        # The interaction target is not merged into the single-protein entry.
        assert len(types) == len(result.entries) == 3

    def test_records_missing_a_value_are_counted_not_silently_dropped(self, stub_chembl):
        result = stub_chembl.activities("CHEMBL3712931", TargetType.SINGLE_PROTEIN)
        assert result.records_seen == 4
        assert result.rejection_counts.get("missing_standard_value") == 1
        assert result.records_excluded == 1
        assert len(result.records) == 3

    def test_assay_context_and_raw_value_are_preserved(self, stub_chembl):
        result = stub_chembl.activities("CHEMBL3712931", TargetType.SINGLE_PROTEIN)
        record = next(r for r in result.records if r.evidence_class is EvidenceClass.MEASURED_DIRECT_BINDING)
        assert record.standard_type == "Kd"
        assert record.unit
        assert record.raw_value is not None
        assert record.assay_description
        assert record.document_ref
        assert record.source_url
        assert record.target_type_declared == "single_protein"

    def test_empty_activities_is_empty_not_failed(self):
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {"activity.json": {"activities": [], "page_meta": {"total_count": 0}}}
            )
        )
        result = adapter.activities("CHEMBL0000000", TargetType.SINGLE_PROTEIN)
        assert result.status == RetrievalStatus.EMPTY.value
        assert result.records == []

    def test_transport_failure_is_failed(self):
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient({"activity.json": SourceUnavailableError("chembl", "HTTP 500")})
        )
        result = adapter.activities("CHEMBL3712931", TargetType.SINGLE_PROTEIN)
        assert result.status == RetrievalStatus.FAILED.value
        assert result.warnings and "500" in result.warnings[0]

    def test_activity_requests_are_projected_to_the_mapped_fields(self):
        """Every activity request asks for the mapped subset (ONLINE-08 cost).

        Measured on the live API 2026-09-16 for two targets at `limit=200`:
        216,632 → 127,415 and 297,821 → 169,798 bytes per page (about -42 %),
        with no latency improvement — the projected pages were equal or slower
        (`benchmarks/online00-chembl-projection-2026-09-16.md`). The projection
        is only safe because it names every field the mapper reads — which is
        what the second half of this test pins down, so a new field cannot
        silently read as absent.
        """
        import inspect

        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {"activity.json": {"activities": [], "page_meta": {"total_count": 0}}}
            )
        )
        adapter.activities("CHEMBL3712931", TargetType.SINGLE_PROTEIN)
        activity_calls = [p for url, p in adapter.client.calls if "activity.json" in url]
        assert activity_calls, "no activity request was made"
        for params in activity_calls:
            assert params.get("only") == ACTIVITY_FIELDS

        mapped = set(
            re.findall(r'activity\.get\("([^"]+)"\)', inspect.getsource(ChEMBLDiscoveryAdapter._to_record))
        )
        projected = set(ACTIVITY_FIELDS.split(","))
        assert mapped <= projected, f"fields read but not projected: {sorted(mapped - projected)}"


class TestBindingDBAdapter:
    def test_affinity_values_and_the_nanomolar_convention(self, stub_bindingdb):
        result = stub_bindingdb.load("P05231")
        assert result.status == RetrievalStatus.COMPLETE.value
        assert result.records
        for record in result.records:
            assert record.unit == "nM"
            assert record.source_record_id.startswith("bindingdb:")
            assert record.raw_value is not None

    def test_zero_hits_is_empty(self):
        adapter = BindingDBRestAdapter(
            client=StubSourceClient({"getLigandsByUniprot": load_fixture("bindingdb_P29965_empty.json")})
        )
        result = adapter.load("P29965")
        assert result.status == RetrievalStatus.EMPTY.value
        assert result.records == []

    def test_an_html_response_is_a_failure_not_an_empty_result(self):
        adapter = BindingDBRestAdapter(
            client=StubSourceClient(
                {
                    "getLigandsByUniprot": SourceUnavailableError(
                        "bindingdb", "response was not JSON (HTTP 200)"
                    )
                }
            )
        )
        result = adapter.load("P08887")
        assert result.status == RetrievalStatus.FAILED.value
        assert result.records == []
        assert result.warnings


class TestPubChemAdapter:
    def test_identity_lookup_confirms_a_structure(self):
        adapter = PubChemAdapter(
            client=StubSourceClient({"property": load_fixture("pubchem_identity.json")})
        )
        identity = adapter.identify("CC(=O)Oc1ccccc1C(=O)O")
        assert identity.status == RetrievalStatus.COMPLETE.value
        assert identity.cid == 2244
        assert identity.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

    def test_screening_assays_are_bounded_and_labelled_as_screening(self):
        adapter = PubChemAdapter(
            client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
        )
        context = adapter.screening_assays_for_gene("TSLP")
        assert context.assay_ids
        assert context.status == RetrievalStatus.COMPLETE.value
        assert any("screening" in note.lower() for note in context.notes)

    def test_a_documented_404_is_empty_not_failed(self):
        adapter = PubChemAdapter(
            client=StubSourceClient(
                {"genesymbol": SourceUnavailableError("pubchem", "HTTP 404", status_code=404)}
            )
        )
        context = adapter.screening_assays_for_gene("NOPE")
        assert context.status == RetrievalStatus.EMPTY.value
        assert "not that no inhibitor exists" in " ".join(context.notes)


# --- persistence and result model --------------------------------------------------


@pytest.fixture()
def investigated(online_engine, resolved_target, stub_chembl, stub_bindingdb, stub_pubchem):
    service = TargetDiscoveryService(
        chembl=stub_chembl, bindingdb=stub_bindingdb, pubchem=stub_pubchem
    )
    report = service.investigate(online_engine, resolved_target)
    return resolved_target, report


class TestDiscoveryPersistence:
    def test_every_source_gets_a_retrieval_row(self, online_engine, investigated):
        target, _report = investigated
        retrievals = {r.source_name: r for r in list_source_retrievals(online_engine, target.id)}
        assert set(retrievals) == {"chembl", "bindingdb", "pubchem"}
        assert all(r.checksum for r in retrievals.values())

    def test_a_source_that_was_not_requested_says_so(
        self, online_engine, resolved_target, stub_chembl
    ):
        service = TargetDiscoveryService(
            chembl=stub_chembl,
            bindingdb=BindingDBRestAdapter(client=StubSourceClient({})),
            pubchem=PubChemAdapter(client=StubSourceClient({})),
        )
        report = service.investigate(online_engine, resolved_target, sources=["chembl"])
        statuses = {r.source_name: r.status for r in report.retrievals}
        assert statuses["chembl"] is RetrievalStatus.COMPLETE
        assert statuses["bindingdb"] is RetrievalStatus.NOT_QUERIED
        assert statuses["pubchem"] is RetrievalStatus.NOT_QUERIED

    def test_a_failed_source_is_recorded_as_failed(self, online_engine, resolved_target, stub_chembl):
        failing = BindingDBRestAdapter(
            client=StubSourceClient(
                {"getLigandsByUniprot": SourceUnavailableError("bindingdb", "HTTP 200 empty body")}
            )
        )
        service = TargetDiscoveryService(
            chembl=stub_chembl,
            bindingdb=failing,
            pubchem=PubChemAdapter(client=StubSourceClient({})),
        )
        report = service.investigate(online_engine, resolved_target)
        by_source = {r.source_name: r for r in report.retrievals}
        assert by_source["bindingdb"].status is RetrievalStatus.FAILED
        assert any("not a statement that no measurements exist" in w for w in by_source["bindingdb"].warnings)

    def test_chemistry_is_normalized_and_descriptors_are_present(self, online_engine, investigated):
        target, _report = investigated
        _total, items = list_candidates(online_engine, target.id, include_all_modalities=True)
        assert items
        with online_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT inchikey, canonical_smiles, molecular_formula, molecular_weight,
                           hbd, hba, tpsa, logp, modality, m
                    FROM compounds WHERE inchikey = ANY(:keys)
                    """
                ),
                {"keys": [i.inchikey for i in items]},
            ).mappings().all()
        assert rows
        for row in rows:
            assert row["molecular_formula"], row["inchikey"]
            assert row["molecular_weight"] is not None
            assert row["m"] is not None
            assert row["modality"] in {"small_molecule", "peptide", "oligonucleotide", "biologic", "unclassified"}

    def test_external_compounds_carry_rdkit_descriptors_not_defaults(self, online_engine, investigated):
        """Regression: an earlier revision stored `has_stereo = false` for every
        externally discovered compound, so a peptide with specified
        stereocentres was reported as having none. The ONLINE-05 evaluation
        caught it by re-deriving the flag from the stored structure."""
        from spago_core.chemistry import normalize

        target, _report = investigated
        _total, rows = list_candidates(online_engine, target.id, include_all_modalities=True)
        assert rows
        with online_engine.connect() as conn:
            stored = conn.execute(
                text(
                    """
                    SELECT inchikey, canonical_smiles, has_stereo, is_multi_component,
                           molecular_formula, molecular_weight, inchi
                    FROM compounds WHERE inchikey = ANY(:keys)
                    """
                ),
                {"keys": [r.inchikey for r in rows]},
            ).mappings().all()
        assert stored
        for row in stored:
            renorm = normalize(row["canonical_smiles"])
            assert row["has_stereo"] == renorm.has_stereo, row["inchikey"]
            assert row["is_multi_component"] == renorm.is_multi_component, row["inchikey"]
            # Descriptors are populated, not left NULL for external rows.
            assert row["molecular_formula"] and row["molecular_weight"] is not None
            assert row["inchi"]
        # At least one recorded peptide really does have specified stereo, so the
        # assertion above is not vacuous.
        assert any(row["has_stereo"] for row in stored)

    def test_modality_filter_is_labelled_and_counted(self, online_engine, investigated):
        target, _report = investigated
        breakdown = modality_breakdown(online_engine, target.id)
        assert "peptide" in breakdown  # the recorded TSLP payload contains peptides
        small_total, small_items = list_candidates(online_engine, target.id)
        all_total, all_items = list_candidates(online_engine, target.id, include_all_modalities=True)
        assert small_total <= all_total
        assert all(i.modality.value in {"small_molecule", "unclassified"} for i in small_items)
        assert all_total == sum(breakdown.values())
        assert all_items

    def test_measurements_keep_their_endpoint_and_class(self, online_engine, investigated):
        target, _report = investigated
        measurements = list_target_measurements(online_engine, target.id, limit=200)
        assert measurements
        classes = {m["evidence_class"] for m in measurements}
        assert EvidenceClass.MEASURED_DIRECT_BINDING.value in classes
        assert EvidenceClass.FUNCTIONAL_EFFECT.value in classes
        # Values stay as reported: no merge of Kd into IC50, and relations survive.
        endpoints = {m["standard_type"] for m in measurements}
        assert "Kd" in endpoints
        for m in measurements:
            assert m["unit"] is not None
            assert m["relation"] in {"=", "<", ">", "~", "<=", ">="}

    def test_shared_original_reference_duplicates_are_flagged(self, online_engine, resolved_target):
        """One upstream experiment recorded in two databases must not read as
        independent corroboration (ONLINE-00 C)."""
        smiles = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
        shared = dict(
            compound_source_id=smiles,
            target_key="CHEMBL_STUB",
            assay_key="STUB:ASSAY:1",
            assay_type="B",
            standard_type="IC50",
            value=120.0,
            unit="nM",
            relation="=",
            evidence_class=EvidenceClass.MEASURED_DIRECT_BINDING,
            document_ref="SHARED-DOC-1",
            raw_smiles=smiles,
        )
        first = ActivityRecord(source_record_id="src-a:1", source_molecule_id="A", **shared)
        second = ActivityRecord(source_record_id="src-b:1", source_molecule_id="B", **shared)
        # A genuinely different experiment: same compound and document, other value.
        other = ActivityRecord(
            source_record_id="src-b:2",
            source_molecule_id="B",
            **{**shared, "value": 2600.0, "assay_key": "STUB:ASSAY:2"},
        )
        service = TargetDiscoveryService(
            chembl=StubActivityAdapter([first]),
            bindingdb=StubActivityAdapter([second, other]),
            pubchem=PubChemAdapter(client=StubSourceClient({})),
        )
        service.investigate(online_engine, resolved_target, sources=["chembl", "bindingdb"])
        measurements = list_target_measurements(online_engine, resolved_target.id, limit=200)
        by_record = {m["source_record_id"]: m for m in measurements}
        assert len(by_record) == 3
        flagged = [m for m in measurements if m["potential_duplicate"]]
        assert len(flagged) == 1
        assert flagged[0]["value"] == 120.0
        assert "not independent corroboration" in (flagged[0]["validity_comment"] or "")
        # A different value from the same document is a different measurement.
        assert by_record["src-b:2"]["potential_duplicate"] is False
        # ... and the copy that was kept first is not itself flagged.
        assert by_record["src-a:1"]["potential_duplicate"] is False
        # Neither value was averaged into the other.
        assert {by_record["src-a:1"]["value"], by_record["src-b:2"]["value"]} == {120.0, 2600.0}

        deduped = list_target_measurements(
            online_engine, resolved_target.id, limit=200, include_duplicates=False
        )
        assert len(deduped) == 2
        assert all(not m["potential_duplicate"] for m in deduped)

    def test_measurement_against_an_interaction_is_attributed_to_that_object(
        self, online_engine
    ):
        """For CD40L the therapeutic object is the CD40L-CD40 interaction. Its
        measurements must be labelled as interaction evidence and attached to
        the interaction target, not to the ligand's own binding site."""
        interaction_activity = {
            "activity_id": 9000001,
            "molecule_chembl_id": "CHEMBL_STUB_1",
            "assay_chembl_id": "CHEMBL_ASSAY_PPI",
            "assay_type": "B",
            "assay_description": "Inhibition of CD40L-CD40 interaction",
            "standard_type": "IC50",
            "standard_relation": "=",
            "standard_value": "120.0",
            "standard_units": "nM",
            "target_chembl_id": "CHEMBL4106122",
            "target_pref_name": "CD40-CD40L",
            "target_organism": "Homo sapiens",
            "canonical_smiles": "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1",
            "document_chembl_id": "CHEMBL_DOC_1",
            "pchembl_value": "6.92",
            "potential_duplicate": 0,
        }
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_P29965.json"),
                    # The same payload is returned for every target id, which is
                    # what makes this a targeted test of attribution: the record
                    # arrives through the interaction target's query.
                    "activity.json": {"activities": [interaction_activity], "page_meta": {"total_count": 1}},
                }
            ),
            max_activities=10,
        )
        found = adapter.targets_for_accession("P29965")
        assert {e.identifier for e in found.entries} >= {"CHEMBL3580491", "CHEMBL4106122"}

        uniprot = UniProtTargetResolver(
            client=StubSourceClient(
                {
                    "uniprotkb/search": {
                        "results": [
                            {
                                "primaryAccession": "P29965",
                                "uniProtkbId": "CD40L_HUMAN",
                                "entryType": "UniProtKB reviewed (Swiss-Prot)",
                                "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                                "genes": [{"geneName": {"value": "CD40LG"}}],
                                "proteinDescription": {
                                    "recommendedName": {"fullName": {"value": "CD40 ligand"}}
                                },
                            }
                        ],
                        "totalResults": 1,
                    }
                }
            )
        )
        target = TargetResolutionService(uniprot=uniprot).resolve(online_engine, "CD40LG", "human").target
        assert target is not None
        service = TargetDiscoveryService(
            chembl=adapter,
            bindingdb=BindingDBRestAdapter(client=StubSourceClient({})),
            pubchem=PubChemAdapter(client=StubSourceClient({})),
        )
        report = service.investigate(online_engine, target, sources=["chembl"])
        retrievals = {r.source_name: r for r in report.retrievals}
        assert "CHEMBL4106122" in retrievals["chembl"].query.get("target_chembl_ids", [])
        assert retrievals["chembl"].status is RetrievalStatus.COMPLETE

        measurements = list_target_measurements(online_engine, target.id, limit=50)
        interaction = [m for m in measurements if m["target_key"] == "CHEMBL4106122"]
        assert interaction, "the interaction measurement must be in the investigation scope"
        assert interaction[0]["evidence_class"] == EvidenceClass.INTERACTION_DISRUPTION.value
        assert interaction[0]["target_type"] == "protein_protein_interaction"
        # The investigated target keeps its own single-protein identity, so the
        # record never claims a binding site on the ligand when the source
        # measured an interaction.
        with online_engine.connect() as conn:
            ligand_type = conn.execute(
                text("SELECT target_type FROM targets WHERE id = :i"), {"i": target.id}
            ).scalar_one()
            interaction_rows = conn.execute(
                text("SELECT count(*) FROM targets WHERE target_key = 'CHEMBL4106122'")
            ).scalar_one()
        assert ligand_type == "single_protein"
        assert interaction_rows == 1


class TestCandidateIsIndependentOfPatentMembership:
    def test_candidates_have_no_patent_occurrence_by_default(self, online_engine, investigated):
        target, _report = investigated
        _total, items = list_candidates(online_engine, target.id)
        assert items
        assert all(i.patent_occurrences == 0 for i in items)
        assert all(i.patent_labels == [] for i in items)

    def test_a_non_patent_candidate_can_be_saved_and_reopened(self, online_engine, investigated):
        target, _report = investigated
        _total, items = list_candidates(online_engine, target.id)
        chosen = [items[0].compound_id]

        project = projects_svc.create_project(online_engine, f"ONLINE-00 candidate save {target.id}")
        result = projects_svc.save_candidates(online_engine, project.id, target.id, chosen)
        assert result.created_rows == 1
        assert result.target_key == target.target_key

        _summary, saved = projects_svc.get_project(online_engine, project.id)
        assert len(saved) == 1
        item = saved[0]
        assert item.family_id is None
        assert item.target_id == target.id
        assert item.target_key == target.target_key
        assert item.compound_id == chosen[0]
        assert item.inchikey and item.canonical_smiles
        assert item.evidence_class is not None
        assert item.record_missing is False

    def test_saving_is_idempotent(self, online_engine, investigated):
        target, _report = investigated
        _total, items = list_candidates(online_engine, target.id)
        project = projects_svc.create_project(online_engine, f"ONLINE-00 idempotent {target.id}")
        first = projects_svc.save_candidates(online_engine, project.id, target.id, [items[0].compound_id])
        second = projects_svc.save_candidates(online_engine, project.id, target.id, [items[0].compound_id])
        assert first.created_rows == 1
        assert second.created_rows == 0
        assert second.already_present_rows == 1

    def test_out_of_scope_compounds_are_refused(self, online_engine, investigated):
        target, _report = investigated
        project = projects_svc.create_project(online_engine, f"ONLINE-00 scope {target.id}")
        import uuid as _uuid

        with pytest.raises(projects_svc.ProjectScopeError):
            projects_svc.save_candidates(online_engine, project.id, target.id, [_uuid.uuid4()])

    def test_a_patent_linked_candidate_reports_its_occurrences(self, online_engine, investigated):
        """A compound that is both a target candidate and a patent occurrence
        must show the patent link rather than being treated as patent-free."""
        import uuid as _uuid

        target, _report = investigated
        family_id, document_id = _uuid.uuid4(), _uuid.uuid4()
        with online_engine.begin() as conn:
            compound = conn.execute(
                text("SELECT compound_id FROM target_candidates WHERE target_id = :t LIMIT 1"),
                {"t": target.id},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO patent_families (id, family_key, title, source_name,
                                                 dataset_version, retrieved_at)
                    VALUES (:id, 'ONLINE00-FAM', 'linkage fixture', 'test', 'test:1', now())
                    """
                ),
                {"id": family_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, source_name,
                                                 dataset_version, retrieved_at)
                    VALUES (:id, :fid, 'WO0000000001A1', 'test', 'test:1', now())
                    """
                ),
                {"id": document_id, "fid": family_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO compound_mentions (id, compound_id, document_id, patent_label,
                                                   source_name, dataset_version, retrieved_at)
                    VALUES (:id, :cid, :did, 'Example 1', 'test', 'test:1', now())
                    """
                ),
                {"id": _uuid.uuid4(), "cid": compound, "did": document_id},
            )
        _total, items = list_candidates(online_engine, target.id, include_all_modalities=True)
        linked = [i for i in items if i.compound_id == compound]
        assert linked and linked[0].patent_occurrences == 1
        assert linked[0].patent_labels == ["WO0000000001A1 · Example 1"]
        # Everything else in this investigation really is patent-free, which is
        # the state the plan requires to stay usable rather than be discarded.
        assert all(i.patent_occurrences == 0 for i in items if i.compound_id != compound)
