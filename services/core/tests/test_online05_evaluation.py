"""ONLINE-05 scientific evaluation.

These are the properties a scientist would check by hand, turned into
assertions over recorded fixtures. Each one states the failure it prevents, so a
future change that breaks the science fails here rather than in a user's
notebook.

Scope of this module: the *invariants of the result model and the summaries*.
Live-source coverage is recorded separately in `benchmarks/online00-coverage-*`;
whether the retrieved chemistry is correct for a given target is a scientific
judgement that requires manual cross-reading (see the ONLINE-05 acceptance
record), not an assertion a test can make.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.chemistry import Modality, classify_modality
from spago_core.domain import EvidenceClass, TargetType
from spago_core.services import ai
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_candidates,
    list_target_measurements,
    modality_breakdown,
)
from spago_core.services.targets import TargetResolutionService

from tests.open_source_stubs import StubSourceClient, load_fixture


@pytest.fixture(scope="session")
def planner_requests() -> list[dict]:
    path = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "planner_requests.json"
    return json.loads(path.read_text())["requests"]


@pytest.fixture(scope="module")
def online_engine(seeded_engine):
    return seeded_engine


@pytest.fixture(autouse=True)
def clean_investigation(online_engine):
    with online_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE target_candidates, source_retrievals, measurements, assays, "
                "target_resolutions, compounds, targets, ai_analyses CASCADE"
            )
        )
    yield


@pytest.fixture()
def tslp(online_engine):
    """The recorded TSLP investigation: 1 small molecule, 68 peptides, 3 sources."""
    service = TargetResolutionService(
        uniprot=UniProtTargetResolver(
            client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
        )
    )
    target = service.resolve(online_engine, "TSLP", "human").target
    assert target is not None
    discovery = TargetDiscoveryService(
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
    )
    report = discovery.investigate(online_engine, target, sources=["chembl", "bindingdb"])
    return target, report


class TestModalityInvariants:
    """A peptide must never be presented as a small-molecule inhibitor."""

    def test_recorded_tslp_peptides_are_not_classified_as_small_molecules(self, online_engine, tslp):
        target, _report = tslp
        breakdown = modality_breakdown(online_engine, target.id)
        assert breakdown.get("peptide", 0) > 0
        _total, small = list_candidates(online_engine, target.id)
        for candidate in small:
            assert candidate.modality in {Modality.SMALL_MOLECULE, Modality.UNCLASSIFIED}
            # The rule that decided it is recorded, so the label is reviewable.
            assert candidate.modality_rule
            # A peptide that slipped through would have many amide bonds.
            if candidate.modality is Modality.SMALL_MOLECULE:
                verdict = classify_modality(candidate.canonical_smiles)
                assert verdict.modality is Modality.SMALL_MOLECULE

    def test_the_excluded_modalities_are_counted_not_dropped(self, online_engine, tslp):
        target, _report = tslp
        breakdown = modality_breakdown(online_engine, target.id)
        filtered_total, filtered = list_candidates(online_engine, target.id)
        all_total, all_rows = list_candidates(online_engine, target.id, include_all_modalities=True)
        # The breakdown accounts for every candidate the investigation stored.
        assert all_total == sum(breakdown.values())
        assert all_total >= filtered_total
        # Nothing visible in the filtered view is missing from the full view, and
        # the filtered view is exactly the labelled subset.
        assert {c.compound_id for c in filtered} <= {c.compound_id for c in all_rows}
        assert {c.modality.value for c in filtered} <= {
            Modality.SMALL_MOLECULE.value,
            Modality.UNCLASSIFIED.value,
        }
        assert filtered_total == len(filtered)

    def test_stereochemistry_is_preserved_through_normalization(self, online_engine, tslp):
        """The stored structure still means what the source said.

        The check is that re-normalizing the stored canonical SMILES reproduces
        the stored identity and the stored stereo flag: if normalization had
        dropped a stereocentre, the flag would no longer match the structure it
        was derived from. (`has_stereo` reflects *RDKit-recognised* stereocentres,
        so a SMILES containing `@` on a non-stereogenic atom is not itself
        evidence of loss.)
        """
        target, _report = tslp
        with online_engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT inchikey, has_stereo, is_multi_component, canonical_smiles "
                    "FROM compounds ORDER BY inchikey"
                )
            ).mappings().all()
        assert stored
        from spago_core.chemistry import normalize

        for row in stored:
            renorm = normalize(row["canonical_smiles"])
            assert renorm.inchikey == row["inchikey"], row["inchikey"]
            assert renorm.has_stereo == row["has_stereo"], row["inchikey"]
            assert renorm.is_multi_component == row["is_multi_component"], row["inchikey"]
            # A specified stereocentre shows in the InChIKey's stereo block.
            if row["has_stereo"]:
                assert row["inchikey"].split("-")[1] != "UHFFFAOYSA", row["inchikey"]


class TestSaltAndMultiComponentHandling:
    def test_a_multi_component_record_stays_identified_as_such(self, online_engine):
        """Salts are not silently collapsed to a parent structure at this stage."""
        from spago_core.chemistry import normalize

        salt = normalize("CC(=O)Oc1ccccc1C(=O)O.CN1C2=CC=CC=C2SC2=CC=CC=C21")
        assert salt.is_multi_component is True
        with online_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO compounds (id, canonical_smiles, inchikey, is_multi_component,
                                           dataset_version)
                    VALUES (:id, :smi, :ik, true, 'evaluation:fixture')
                    ON CONFLICT (inchikey) DO NOTHING
                    """
                ),
                {"id": uuid.uuid4(), "smi": salt.canonical_smiles, "ik": salt.inchikey},
            )
        with online_engine.connect() as conn:
            flag = conn.execute(
                text("SELECT is_multi_component FROM compounds WHERE inchikey = :ik"),
                {"ik": salt.inchikey},
            ).scalar_one()
        assert flag is True


class TestEvidenceClassInvariants:
    """A readout must never claim more than it measured."""

    def test_percent_inhibition_is_never_labelled_direct_binding(self, online_engine, tslp):
        target, _report = tslp
        rows = list_target_measurements(online_engine, target.id, limit=500)
        assert rows
        for row in rows:
            if row["standard_type"].lower() == "inhibition" and row["unit"] == "%":
                assert row["evidence_class"] != EvidenceClass.MEASURED_DIRECT_BINDING.value

    def test_affinity_values_get_the_stronger_class_only_with_a_kinetic_endpoint(
        self, online_engine, tslp
    ):
        target, _report = tslp
        rows = list_target_measurements(online_engine, target.id, limit=500)
        for row in rows:
            if row["evidence_class"] == EvidenceClass.MEASURED_DIRECT_BINDING.value:
                assert row["standard_type"] in {"Kd", "Ki", "IC50", "EC50", "K"}, row

    def test_endpoint_types_are_never_merged(self, online_engine, tslp):
        """Kd and IC50 are different measurements and stay separate rows."""
        target, _report = tslp
        rows = list_target_measurements(online_engine, target.id, limit=500)
        endpoints = {r["standard_type"] for r in rows}
        assert len(endpoints) > 1
        for row in rows:
            assert row["unit"] is not None and row["unit"] != ""
            assert isinstance(row["value"], float)

    def test_a_source_failure_is_never_recorded_as_an_empty_result(self, online_engine):
        from spago_core.adapters.http import SourceUnavailableError

        service = TargetResolutionService(
            uniprot=UniProtTargetResolver(
                client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
            )
        )
        target = service.resolve(online_engine, "TSLP", "human").target
        assert target is not None
        discovery = TargetDiscoveryService(
            chembl=ChEMBLDiscoveryAdapter(client=StubSourceClient({})),
            bindingdb=BindingDBRestAdapter(
                client=StubSourceClient(
                    {"getLigandsByUniprot": SourceUnavailableError("bindingdb", "HTTP 200 empty body")}
                )
            ),
        )
        report = discovery.investigate(online_engine, target, sources=["chembl", "bindingdb"])
        by_source = {r.source_name: r for r in report.retrievals}
        assert by_source["bindingdb"].status.value == "failed"
        assert by_source["bindingdb"].records_seen == 0
        # The failure is stated in words a reader cannot mistake for coverage.
        assert any("not a statement that no measurements exist" in w for w in by_source["bindingdb"].warnings)


class TestSummaryInvariants:
    """A summary may not claim absence of evidence as absence of activity."""

    def test_a_target_summary_states_coverage_and_never_denies_inhibitors(self, online_engine, tslp):
        target, _report = tslp
        result = ai.summarize_target(online_engine, target.id)
        text_lower = result["text"].lower()
        assert "never demonstrate that no inhibitors exist" in text_lower
        # Any mention of an absence must be inside the explicit caveat: a bare
        # claim that nothing exists is the one thing this summary may not say.
        import re

        for sentence in re.split(r"(?<=[.!?])\s+", text_lower):
            if "no inhibitors" in sentence:
                assert "never demonstrate" in sentence or "not evidence" in sentence, sentence
        # Coverage per source travels into the summary.
        assert "chembl:" in result["text"] and "bindingdb:" in result["text"]

    def test_every_summary_citation_is_inside_the_supplied_scope(self, online_engine, tslp):
        target, _report = tslp
        result = ai.summarize_target(online_engine, target.id)
        snapshot = result["input_snapshot"]
        allowed = set()
        allowed.add(snapshot["target"]["ref"])
        allowed.update(c["ref"] for c in snapshot.get("candidates") or [])
        allowed.update(m["ref"] for m in snapshot.get("measurements") or [])
        for citation in result["citations"]:
            assert citation["fact_ref"] in allowed, citation

    def test_a_family_summary_excludes_global_ingestion_counts(self, online_engine):
        """A family conclusion must not be influenced by dataset-wide statistics."""
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        result = ai.summarize_family(online_engine, family_id)
        blob = json.dumps(result["input_snapshot"]).lower()
        assert "ingestion_issue" not in blob
        assert "ingestion issue" not in result["text"].lower()

    def test_offline_output_is_never_labelled_llm_inferred(self, online_engine, tslp):
        target, _report = tslp
        result = ai.summarize_target(online_engine, target.id)
        assert result["provenance_state"] == "machine_extracted"
        assert result["provider"] == "offline-extractive"


class TestPlanEvaluation:
    """The sealed request set is an evaluation artifact, not just a test input."""

    def test_the_sealed_set_still_describes_the_planner(self, planner_requests):
        """If the planner's vocabulary changes, the sealed expectations must be
        revisited deliberately rather than silently drifting."""
        from spago_core.services import planner

        kinds = {case["expect"] for case in planner_requests}
        assert "open_patent" in kinds and "target_discovery" in kinds
        assert len(planner_requests) >= 20
        # Every sealed request is reproducible offline.
        for entry in planner_requests:
            plan = planner.offline_plan(entry["request"], entry.get("context") or {})
            assert plan.plan_version == planner.PLAN_VERSION
