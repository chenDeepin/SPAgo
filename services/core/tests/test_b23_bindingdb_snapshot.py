"""B-23: a target investigated from a local BindingDB snapshot release.

The web path asks BindingDB over REST; an operator who holds a release on disk can
answer the same question from the file, with the whole release, the target
organism, the chain count and the document each row came from. What these tests
pin is that the file path is *honest* about the three things it knows and the REST
path does not:

  * which file it read (release, digest, size, rows scanned),
  * whether it read all of it (a bound makes the answer a prefix, and says so),
  * and whose rows it kept (the requested organism, and the requested target only —
    a related protein's name is not a substring match by default).

The scan is driven by a synthetic fixture release
(`data/fixtures/open_sources/bindingdb_snapshot_sample.tsv`, 17 rows, no real
measurement values), so nothing here depends on the operator's 8.9 GB file or on
BindingDB being reachable. The store path runs against the scratch database
through the ordinary service, which is what makes "a snapshot run and a REST run
reconcile on the same compounds" checkable rather than asserted.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.bindingdb_snapshot import (
    BindingDBSnapshotAdapter,
    canonical_organism,
    default_release,
    match_target_name,
    organism_verdict,
)
from spago_core.config import get_settings
from spago_core.db import run_migrations
from spago_core.domain import EvidenceClass, RetrievalStatus, TargetType
from spago_core.domain.models import ResolvedTarget
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_source_retrievals,
    list_target_measurements,
)
from spago_core.services.reference import policy_from_settings, reference_verdict
from spago_core.services.targets import target_id_for_key

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO_ROOT / "data" / "fixtures" / "open_sources" / "bindingdb_snapshot_sample.tsv"
IL6_ACCESSION = "P05231"
IL6R_ACCESSION = "P08887"
RELEASE = "bindingdb_snapshot_sample"
DATASET_VERSION = f"bindingdb-snapshot:{RELEASE}"

# The two structures the fixture release shares with the recorded REST payload
# (`bindingdb_P05231.json`, monomerids 140015 and 331842) — the reconciliation
# test needs the same molecules from both paths.
C1_SMILES = "Cc1ncccc1NC(=O)c1ccc2c(c1)C(=O)C[C@@H]1C[C@](O)(CC[C@@]21Cc1ccccc1)C(F)(F)F"


def snapshot(**overrides) -> BindingDBSnapshotAdapter:
    """The fixture release as the adapter the operator script would build."""
    options = {
        "names": ["Interleukin-6"],
        "organism": "Homo sapiens",
        "synthetic": True,
    }
    options.update(overrides)
    return BindingDBSnapshotAdapter(SNAPSHOT, **options)


@pytest.fixture(scope="module")
def il6_scan():
    """One complete scan of the fixture release, shared by the adapter tests."""
    return snapshot().load(IL6_ACCESSION)


# --- what the scan says about the file it read ------------------------------


class TestFileIdentity:
    def test_a_complete_scan_reports_the_release_it_read(self, il6_scan):
        context = il6_scan.query_context
        assert il6_scan.status == RetrievalStatus.COMPLETE.value
        assert context["snapshot_complete"] is True
        assert context["snapshot_file"] == SNAPSHOT.name
        assert context["snapshot_release"] == RELEASE
        assert context["snapshot_size_bytes"] == SNAPSHOT.stat().st_size
        assert context["snapshot_rows_scanned"] == 19
        # The digest is of the file's own bytes, computed in the same pass.
        assert context["snapshot_sha256"] == (
            hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()[:16]
        )
        assert il6_scan.envelope.dataset_version == DATASET_VERSION
        assert il6_scan.envelope.synthetic is True

    def test_the_release_is_read_from_the_filename_when_it_carries_one(self):
        assert default_release("/data/BindingDB_All_2609.tsv") == "2609"
        assert default_release("/data/bindingdb-snapshot-2609.tsv") == "2609"
        assert default_release("/data/my_local_export.tsv") == "my_local_export"
        # An explicit release always wins over the filename.
        assert snapshot(release="2609").dataset_version == "bindingdb-snapshot:2609"

    def test_a_re_run_yields_the_same_record_ids(self, il6_scan):
        """Idempotence (D8): a re-run updates rows, it does not add a second set."""
        again = snapshot().load(IL6_ACCESSION)
        assert [r.source_record_id for r in again.records] == [
            r.source_record_id for r in il6_scan.records
        ]
        assert all(
            r.source_record_id.startswith("bindingdb-snapshot:") for r in il6_scan.records
        )


# --- what the scan says about what it did not use ---------------------------


class TestScanHonesty:
    def test_the_scan_summary_counts_rows_it_could_not_use(self, il6_scan):
        assert il6_scan.rejection_counts == {
            "missing_affinity": 1,
            "missing_record_id": 1,
            "missing_structure": 1,
            "organism_mismatch": 1,
            "unparseable_standard_value": 1,
        }
        # `records_seen` is what the scan handed forward plus the rows it dropped,
        # so no row disappears between the file and the counts.
        assert il6_scan.records_excluded == 5
        assert il6_scan.records_seen == len(il6_scan.records) + 5

    def test_a_bound_stops_the_scan_and_no_digest_is_recorded(self):
        bounded = snapshot(max_rows=5).load(IL6_ACCESSION)
        context = bounded.query_context
        assert bounded.status == RetrievalStatus.PARTIAL.value
        assert context["snapshot_complete"] is False
        assert context["snapshot_rows_scanned"] == 5
        # A prefix has no file identity: reporting a digest here would claim the
        # whole file was read.
        assert context["snapshot_sha256"] == ""
        assert any("before the end of the file" in w for w in bounded.warnings)

    def test_a_minute_bound_also_makes_the_answer_a_prefix(self):
        bounded = snapshot(max_seconds=0.0000001).load(IL6_ACCESSION)
        assert bounded.status == RetrievalStatus.PARTIAL.value
        assert bounded.query_context["snapshot_complete"] is False

    def test_a_missing_file_is_a_failure_not_an_empty_answer(self):
        result = BindingDBSnapshotAdapter(
            SNAPSHOT.parent / "not-there.tsv", names=["Interleukin-6"]
        ).load(IL6_ACCESSION)
        assert result.status == RetrievalStatus.FAILED.value
        assert "does not exist" in " ".join(result.warnings)
        assert result.records == []

    def test_a_file_that_is_not_a_bindingdb_release_is_refused(self, tmp_path):
        stranger = tmp_path / "release_2609.tsv"
        stranger.write_text("col_a\tcol_b\n1\t2\n", encoding="utf-8")
        result = BindingDBSnapshotAdapter(stranger, names=["Interleukin-6"]).load(
            IL6_ACCESSION
        )
        assert result.status == RetrievalStatus.FAILED.value
        assert "required column" in result.warnings[0]

    def test_a_release_without_an_endpoint_column_is_refused(self, tmp_path):
        no_endpoints = tmp_path / "release_2609.tsv"
        no_endpoints.write_text(
            "Target Name\tLigand SMILES\nInterleukin-6\tCCO\n", encoding="utf-8"
        )
        result = BindingDBSnapshotAdapter(no_endpoints, names=["Interleukin-6"]).load(
            IL6_ACCESSION
        )
        assert result.status == RetrievalStatus.FAILED.value
        assert "no endpoint column" in result.warnings[0]


# --- matching ---------------------------------------------------------------


class TestMatching:
    def test_a_related_proteins_name_is_not_a_substring_match_by_default(self):
        """The reason `exact` is the default: the receptor's name contains the
        cytokine's, and its rows are a different target's measurements."""
        assert match_target_name("Interleukin-6", ["Interleukin-6"], mode="exact") is True
        assert (
            match_target_name(
                "Interleukin-6 receptor subunit alpha", ["Interleukin-6"], mode="exact"
            )
            is False
        )
        assert (
            match_target_name(
                "Interleukin-6 receptor subunit alpha", ["Interleukin-6"], mode="auto"
            )
            is True
        )

    def test_a_short_alias_is_equality_only(self):
        assert match_target_name("IL-6", ["il6"], mode="exact") is False
        assert match_target_name("IL6", ["il6"], mode="exact") is True
        assert match_target_name("Interleukin-6 signalling", ["IL6"], mode="auto") is False

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ValueError):
            match_target_name("Interleukin-6", ["Interleukin-6"], mode="fuzzy")

    def test_only_the_requested_target_matches(self, il6_scan):
        context = il6_scan.query_context
        assert context["matched_rows"] == 17
        assert context["matched_by_accession"] == 16
        assert context["matched_by_name"] == 1
        # Every kept record belongs to the requested accession, including the rows
        # that only declare it on chain 2 of a complex.
        assert {r.target_key for r in il6_scan.records} == {f"bindingdb:{IL6_ACCESSION}"}
        # The IL6R row (P08887, "Interleukin-6 receptor subunit alpha") is not in
        # the set under any endpoint.
        assert not any(r.species == "Rattus norvegicus" for r in il6_scan.records)

    def test_a_name_only_row_matches_when_the_name_is_an_alias(self, il6_scan):
        """Row 5 carries no accession at all; the stored alias is what finds it."""
        propane = [r for r in il6_scan.records if r.standard_type == "Kd" and r.value == 2.5]
        assert len(propane) == 1
        assert propane[0].target_name == "Interleukin-6"

    def test_a_trembl_only_row_matches_its_own_accession(self):
        result = snapshot(names=[], organism=None).load("Q9SYNTH")
        assert result.status == RetrievalStatus.COMPLETE.value
        assert result.query_context["matched_by_accession"] == 1
        assert [r.standard_type for r in result.records] == ["Kd"]
        assert result.records[0].value == 7.0

    def test_a_complex_matches_on_either_chain(self, il6_scan):
        """A row that declares the target on chain 2 still belongs to the target,
        and it carries the release's own chain count as its declared type."""
        complexes = [
            r
            for r in il6_scan.records
            if r.target_type_declared == TargetType.PROTEIN_COMPLEX.value
        ]
        assert len(complexes) == 2
        assert {r.standard_type for r in complexes} == {"IC50", "Ki"}

    def test_the_scan_summary_reports_the_aliases_it_used(self, il6_scan):
        context = il6_scan.query_context
        assert context["uniprot"] == IL6_ACCESSION
        assert context["names"] == "Interleukin-6"
        assert context["match_mode"] == "exact"
        assert IL6_ACCESSION in context["matched_aliases"]


# --- what one row becomes ---------------------------------------------------


class TestRowProjection:
    def test_every_filled_endpoint_column_becomes_its_own_record(self, il6_scan):
        kinetics = [r for r in il6_scan.records if r.standard_type in {"kon", "koff"}]
        assert {r.standard_type for r in kinetics} == {"kon", "koff"}
        assert {r.unit for r in kinetics} == {"M-1-s-1", "s-1"}
        # Kinetic constants are not potencies; the classifier will report them so.
        assert all(
            r.evidence_class is EvidenceClass.MEASURED_DIRECT_BINDING for r in kinetics
        )

    def test_the_reported_value_keeps_its_relation_and_raw_text(self, il6_scan):
        ki = next(r for r in il6_scan.records if r.standard_type == "Ki" and r.value == 1.5)
        assert ki.unit == "nM" and ki.relation == "=" and ki.raw_value == "1.5"
        censored = next(
            r for r in il6_scan.records if r.standard_type == "IC50" and r.relation == ">"
        )
        assert censored.value == 10000.0
        assert censored.raw_value == ">10000"

    def test_a_document_and_a_structure_link_travel_with_the_record(self, il6_scan):
        patent = next(r for r in il6_scan.records if r.document_patent_number)
        # Normalized, not as the file punctuates it (`WO2021/123456 A1`).
        assert patent.document_patent_number == "WO2021123456"
        assert patent.document_doi == "10.1000/synthetic.il6.3"
        assert patent.document_ref == "doi:10.1000/synthetic.il6.3"
        assert patent.source_url.endswith("monomerid=140015")
        assert patent.source_molecule_id == "140015"
        assert patent.raw_smiles == C1_SMILES

    def test_the_extraction_path_is_not_the_network_client(self, il6_scan):
        assert {r.extraction_method for r in il6_scan.records} == {"bindingdb_snapshot_tsv"}
        # The assay record is the file's own, so a snapshot run cannot rewrite the
        # wording of the assay row the REST path stored for the same experiment.
        assert all(
            r.assay_key.startswith("bindingdb-snapshot:") for r in il6_scan.records
        )

    def test_the_scan_states_the_organism_it_excluded(self, il6_scan):
        assert any("Rattus norvegicus" in w for w in il6_scan.warnings)

    def test_a_row_from_another_organism_is_kept_only_when_asked_for(self, il6_scan):
        assert not any(r.species == "Rattus norvegicus" for r in il6_scan.records)
        permissive = snapshot(all_organisms=True).load(IL6_ACCESSION)
        assert len(permissive.records) == len(il6_scan.records) + 1
        assert any(r.species == "Rattus norvegicus" for r in permissive.records)
        assert "organism_mismatch" not in permissive.rejection_counts

    def test_a_species_named_two_ways_is_one_organism(self):
        """The failure this test exists for: BindingDB writes "Human" on most rows
        and a target row says "Homo sapiens", so comparing the strings dropped 86 of
        153 real IL6 rows as a mismatch (observed on `BindingDB_All_2609.tsv`)."""
        assert canonical_organism("Human") == canonical_organism("Homo sapiens")
        assert canonical_organism("Homo sapiens (Human)") == "human"
        assert canonical_organism("Rattus norvegicus") == canonical_organism("Rat")
        assert canonical_organism("SARS-CoV-2") == "sars cov 2"
        # Unknown is not a species: the caller must report the uncertainty.
        assert canonical_organism("Human embryonic kidney cells") is None
        assert canonical_organism("") is None and canonical_organism(None) is None

    def test_the_verdict_is_three_way_not_a_string_compare(self):
        assert organism_verdict("Homo sapiens", "Human") == "match"
        assert organism_verdict("Homo sapiens", "Rattus norvegicus") == "mismatch"
        assert organism_verdict("Homo sapiens", "") == "match"
        assert organism_verdict("Homo sapiens", "HEK293 cells") == "unverified"
        assert organism_verdict("an unlisted species", "Human") == "unverified"

    def test_a_row_wording_the_same_species_differently_is_kept(self, il6_scan):
        wording = [r for r in il6_scan.records if r.standard_type == "Ki" and r.value == 6.5]
        assert len(wording) == 1 and wording[0].species == "Human"
        assert il6_scan.query_context["organism_mismatch_rows"] == 1
        # The row is kept, and the only species reported as excluded is the rat one.
        assert any("Rattus norvegicus" in w for w in il6_scan.warnings if "excluded" in w)

    def test_a_row_whose_organism_cannot_be_compared_is_kept_and_counted(self, il6_scan):
        unverified = [
            r for r in il6_scan.records if r.standard_type == "Ki" and r.value == 8.0
        ]
        assert len(unverified) == 1
        assert il6_scan.query_context["organism_unverified_rows"] == 1
        # Kept, so it is not a rejection — and the count travels with the answer.
        assert "organism_unverified" not in il6_scan.rejection_counts
        assert any("could not be compared" in w for w in il6_scan.warnings)

    def test_a_row_that_states_no_organism_is_kept(self, il6_scan):
        """Silence is not a mismatch: `Target Source Organism` is filled on most
        rows, and dropping the blank ones would silently lose real records."""
        octane = [r for r in il6_scan.records if r.standard_type == "Ki" and r.value == 5.0]
        assert len(octane) == 1 and octane[0].species is None


# --- the store path ---------------------------------------------------------


@pytest.fixture(scope="module")
def b23_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_b23_tables(b23_engine):
    with b23_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture()
def il6_target() -> ResolvedTarget:
    """The stored target row an operator's database would already hold."""
    return ResolvedTarget(
        id=target_id_for_key("IL6"),
        target_key="IL6",
        name="Interleukin-6",
        organism="Homo sapiens",
        taxon_id=9606,
        uniprot_accession=IL6_ACCESSION,
        gene_symbol="IL6",
        target_type=TargetType.SINGLE_PROTEIN,
        aliases=["IL6", "IFNB2"],
        source_name="uniprot",
    )


def rest_run(engine, target):
    """The recorded REST payload stored through the ordinary service."""
    service = TargetDiscoveryService(
        bindingdb=BindingDBRestAdapter(
            client=StubSourceClient(
                {"getLigandsByUniprot": load_fixture("bindingdb_P05231.json")}
            )
        )
    )
    return service.investigate(engine, target, sources=["bindingdb"])


def snapshot_run(engine, target, **overrides):
    service = TargetDiscoveryService(bindingdb=snapshot(**overrides))
    return service.investigate(engine, target, sources=["bindingdb"])


class TestSnapshotStorePath:
    def test_a_snapshot_run_stores_its_measurements_with_the_release(self, b23_engine, il6_target):
        report = snapshot_run(b23_engine, il6_target)
        assert report.measurements_stored == 13

        retrieval = {
            r.source_name: r for r in list_source_retrievals(b23_engine, il6_target.id)
        }["bindingdb"]
        assert retrieval.status is RetrievalStatus.COMPLETE
        assert retrieval.dataset_version == DATASET_VERSION
        assert retrieval.source_version == "bindingdb-snapshot-tsv"
        assert retrieval.query["snapshot_sha256"]
        assert retrieval.query["snapshot_complete"] is True
        assert retrieval.query["snapshot_rows_scanned"] == 19
        assert retrieval.query["uniprot"] == IL6_ACCESSION

        measurements = list_target_measurements(b23_engine, il6_target.id)
        assert len(measurements) == 13
        assert {m["source_name"] for m in measurements} == {"bindingdb"}
        assert {m["dataset_version"] for m in measurements} == {DATASET_VERSION}
        assert {m["extraction_method"] for m in measurements} == {"bindingdb_snapshot_tsv"}
        # A snapshot row is a curated fact about that release, not a claim that the
        # compound occurs in a patent (AGENTS §7/§10).
        assert {m["provenance_state"] for m in measurements} == {"database_curated"}

    def test_a_snapshot_run_after_a_rest_run_relabels_the_retrieval(self, b23_engine, il6_target):
        """The shape the live IL6 investigation hit: BindingDB had already answered
        over REST, then the operator ran the file for the same target. The retrieval
        id is one row per (target, source), so the row must carry the *latest* run's
        ask and identity — the file's digest and match mode reach the stored query,
        and the row stops claiming `bindingdb-rest` (AGENTS §8/§25). What must not
        change is the other path's measurements: they keep their own versions and
        record ids, so a reader reconciles the two paths instead of losing one."""
        rest_run(b23_engine, il6_target)
        before = {
            r.source_name: r for r in list_source_retrievals(b23_engine, il6_target.id)
        }["bindingdb"]
        assert before.source_version == "bindingdb-rest"
        assert "snapshot_sha256" not in before.query

        snapshot_run(b23_engine, il6_target)

        after = {
            r.source_name: r for r in list_source_retrievals(b23_engine, il6_target.id)
        }["bindingdb"]
        assert after.source_version == "bindingdb-snapshot-tsv"
        assert after.dataset_version == DATASET_VERSION
        assert after.status is RetrievalStatus.COMPLETE
        assert after.records_kept == 13
        assert after.query["snapshot_file"] == SNAPSHOT.name
        assert after.query["snapshot_sha256"]
        assert after.query["snapshot_rows_scanned"] == 19
        assert after.query["match_mode"] == "exact"
        assert after.query["uniprot"] == IL6_ACCESSION
        assert after.checksum != before.checksum
        assert after.retrieved_at > before.retrieved_at

        rows = list_target_measurements(b23_engine, il6_target.id)
        assert {m["extraction_method"] for m in rows} == {
            "bindingdb_rest_uniprot",
            "bindingdb_snapshot_tsv",
        }

    def test_re_running_a_target_updates_instead_of_duplicating(self, b23_engine, il6_target):
        first = snapshot_run(b23_engine, il6_target)
        rows_before = list_target_measurements(b23_engine, il6_target.id)
        second = snapshot_run(b23_engine, il6_target)
        rows_after = list_target_measurements(b23_engine, il6_target.id)

        assert first.measurements_stored == second.measurements_stored == len(rows_after) == 13
        # Same rows, re-dated: the ids are the release's own record ids, so a re-run
        # updates a measurement instead of adding a second copy of it (AGENTS §22).
        assert {m["id"] for m in rows_after} == {m["id"] for m in rows_before}
        assert max(m["retrieved_at"] for m in rows_after) > max(
            m["retrieved_at"] for m in rows_before
        )

    def test_two_rows_of_one_experiment_are_flagged_not_counted_twice(self, b23_engine, il6_target):
        snapshot_run(b23_engine, il6_target)
        rows = list_target_measurements(b23_engine, il6_target.id)
        flagged = [m for m in rows if m["potential_duplicate"]]
        assert [m["source_record_id"] for m in flagged] == ["bindingdb-snapshot:SYNTH-14:IC50"]
        assert "SYNTH-3" in (flagged[0]["validity_comment"] or "")

    def test_a_bounded_scan_is_stored_as_partial(self, b23_engine, il6_target):
        snapshot_run(b23_engine, il6_target, max_rows=5)
        retrieval = {
            r.source_name: r for r in list_source_retrievals(b23_engine, il6_target.id)
        }["bindingdb"]
        assert retrieval.status is RetrievalStatus.PARTIAL
        assert retrieval.query["snapshot_complete"] is False
        assert not retrieval.query["snapshot_sha256"]

    def test_a_snapshot_run_leaves_another_sources_rows_alone(self, b23_engine, il6_target):
        """B-06 cooperation: the script asks one source, so a snapshot refresh
        cannot re-date what ChEMBL or PubChem stored."""
        from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
        from spago_core.adapters.uniprot import UniProtTargetResolver
        from spago_core.services.targets import TargetResolutionService

        resolver = UniProtTargetResolver(
            client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
        )
        target = TargetResolutionService(uniprot=resolver).resolve(
            b23_engine, "TSLP", "human"
        ).target
        assert target is not None and target.uniprot_accession

        chembl = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_Q969D9.json"),
                    "activity.json": load_fixture("chembl_activities_TSLP.json"),
                }
            )
        )
        TargetDiscoveryService(chembl=chembl).investigate(
            b23_engine, target, sources=["chembl"]
        )
        before = {r.source_name: r for r in list_source_retrievals(b23_engine, target.id)}

        # The snapshot's own target is a different one; the run under test asks only
        # `bindingdb`, so ChEMBL's stored retrieval must survive untouched.
        snapshot_target = ResolvedTarget(
            id=target_id_for_key("IL6"),
            target_key="IL6",
            name="Interleukin-6",
            organism="Homo sapiens",
            uniprot_accession=IL6_ACCESSION,
            target_type=TargetType.SINGLE_PROTEIN,
        )
        snapshot_run(b23_engine, snapshot_target)

        after_chembl = {
            r.source_name: r for r in list_source_retrievals(b23_engine, target.id)
        }["chembl"]
        assert after_chembl.retrieved_at == before["chembl"].retrieved_at
        assert after_chembl.records_kept == before["chembl"].records_kept

    def test_the_verdict_counts_the_snapshot_rows_and_the_kinetics_apart(self, b23_engine, il6_target):
        snapshot_run(b23_engine, il6_target)
        verdict = reference_verdict(
            b23_engine, il6_target, policy_from_settings(get_settings())
        )
        # 10 compounds: ethanol (Ki), acetic acid (>10 µM), two fixture inhibitors,
        # propane, pentane, heptane, octane, nonane, decane. The two kinetic rows are
        # not potencies, so they are counted apart from the threshold question.
        assert verdict.class_counts["active"] == 10
        assert verdict.class_counts["weak"] == 1
        assert verdict.class_counts["not_applicable"] == 2
        assert verdict.compounds == 10
        assert verdict.compounds_active == 9

    def test_a_snapshot_row_and_the_rest_row_reconcile_on_one_compound(self, b23_engine, il6_target):
        """The same experiment reaches SPAgo twice — once through the endpoint and
        once through the file. Both are stored, and the rows say which path each
        came from, so a reader reconciles them instead of counting two experiments."""
        rest_run(b23_engine, il6_target)
        snapshot_run(b23_engine, il6_target)

        rows = list_target_measurements(b23_engine, il6_target.id)
        rest_compound = next(
            m for m in rows if m["source_record_id"] == "bindingdb:140015:IC50"
        )
        same_experiment = [
            m
            for m in rows
            if m["inchikey"] == rest_compound["inchikey"] and m["standard_type"] == "IC50"
        ]
        assert len(same_experiment) == 3  # two snapshot rows + the REST row
        assert {m["value"] for m in same_experiment} == {1.1}
        assert {m["extraction_method"] for m in same_experiment} == {
            "bindingdb_rest_uniprot",
            "bindingdb_snapshot_tsv",
        }
        assert {m["source_name"] for m in same_experiment} == {"bindingdb"}
        # Different records of one assay (the file's row and the endpoint's row), so
        # neither path's wording can overwrite the other's.
        assert len({m["assay_key"] for m in same_experiment}) == 2


# --- the operator script's own contract -------------------------------------


def _script_module():
    """`scripts/bindingdb_snapshot.py` loaded by path — it is not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bindingdb_snapshot_script", REPO_ROOT / "scripts" / "bindingdb_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestOperatorScript:
    def test_json_to_stdout_stays_parseable(self, b23_engine, il6_target, capsys):
        """`--json -` is a pipe: the record must be the whole of stdout, with the
        human summary on stderr. A dry run, so nothing is written and no target has
        to exist beyond the one this fixture stores."""
        import json

        snapshot_run(b23_engine, il6_target)  # persists the stored target row
        script = _script_module()

        code = script.main(
            [
                "--target", "IL6",
                "--file", str(SNAPSHOT),
                "--dry-run",
                "--json", "-",
                "--database-url", b23_engine.url.render_as_string(hide_password=False),
            ]
        )
        captured = capsys.readouterr()
        assert code == 0
        record = json.loads(captured.out)  # would raise on a leading summary line
        assert record["mode"] == "dry-run"
        assert record["status"] == "complete"
        assert record["query"]["snapshot_release"] == RELEASE
        assert record["records_kept"] == 13
        # The summary still reaches the operator, on the other stream.
        assert "rows scanned" in captured.err

    def test_a_target_with_no_stored_row_is_refused_not_resolved(self, b23_engine, capsys):
        """The script never resolves a target: no source may be contacted by it."""
        script = _script_module()
        code = script.main(
            [
                "--target", "TSLP",
                "--file", str(SNAPSHOT),
                "--dry-run",
                "--database-url", b23_engine.url.render_as_string(hide_password=False),
            ]
        )
        assert code == 2
        assert "no stored target matches" in capsys.readouterr().err
