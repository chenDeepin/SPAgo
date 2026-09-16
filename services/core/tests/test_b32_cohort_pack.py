"""B-32 (machine half): source-only versus combined verdict scoping, and the pack.

The scientific point: a workspace that holds hand-added rows and one that holds
only what the sources retrieved can give *different* answers to the same
question, and the difference must be a stated scope rather than a silent blend
(`docs/online-capability.md` §5 records exactly this confusion between the local
cohort and the isolated rehearsal). These tests pin:

- the source-only verdict excludes `user_supplement` rows from every count while
  the combined verdict includes them, under the same policy;
- hand-added gaps (remarks, withdrawals) stay visible in the combined verdict and
  are not smuggled into the source-only one, whose subject is the sources;
- source-side facts (records without a structure) belong to both scopes;
- the pack script's own plumbing: the served-identity comparison fails loudly on
  mismatch/unreachable, and the rendered record states both verdicts and the
  machine-preparation limits.
"""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.db import run_migrations
from spago_core.services.reference import (
    policy_from_settings,
    reference_verdict,
    reference_verdicts,
)
from spago_core.services.supplements import import_supplements, withdraw_supplement
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubActivityAdapter, StubSourceClient, load_fixture

REPO_ROOT = Path(__file__).resolve().parents[3]

TSLP_ACCESSION = "Q969D9"
SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
#: A different compound, so a hand-added active cannot be confused with the
#: source's weak one by identity.
SUPPLEMENT_MOLECULE = "CC(=O)Oc1ccccc1C(=O)O"


class _Settings:
    """The two policy knobs, as `Settings` exposes them."""

    def __init__(self, threshold_nm: float = 10_000.0, min_compounds: int = 10) -> None:
        self.activity_threshold_nm = threshold_nm
        self.activity_min_compounds = min_compounds


def policy(**kwargs):
    return policy_from_settings(_Settings(), **kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def b32_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_b32_tables(b32_engine):
    with b32_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture()
def resolved_target(b32_engine):
    resolver = UniProtTargetResolver(
        client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
    )
    outcome = TargetResolutionService(uniprot=resolver).resolve(b32_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


def _record(record_id: str, smiles: str, *, value: float):
    """One weak source record: above the 10 µM threshold, so only a hand-added
    potent row can move the combined verdict (the case B-32 exists for)."""
    from tests.test_online06_reference import record as source_record

    return source_record(record_id, smiles, value=value)


def _investigate_with_weak_source(engine, target):
    from spago_core.services.discovery import TargetDiscoveryService
    from spago_core.adapters.pubchem import PubChemAdapter

    service = TargetDiscoveryService(
        chembl=StubActivityAdapter([_record("r1", SMALL_MOLECULE, value=43_000.0)]),
        bindingdb=StubActivityAdapter([]),
        pubchem=PubChemAdapter(client=StubSourceClient({})),
    )
    service.investigate(engine, target, sources=["chembl"])


def _add_supplement(
    engine, target, *, smiles: str | None = SUPPLEMENT_MOLECULE, value: float | None = 4.0
):
    rows = [
        {
            "name": "Compound 7",
            "note": "hand-added from the cross-read fixture: a literature claim",
            "smiles": smiles,
            "activity_type": "IC50" if value is not None else None,
            "value": value,
            "unit": "nM" if value is not None else None,
            "relation": "=",
        }
    ]
    result = import_supplements(engine, target.id, rows)
    assert result.measurements + result.remarks == 1, result.model_dump()
    return result


# --- the service-level scoping -----------------------------------------------------


class TestSourceOnlyScoping:
    def test_a_supplement_moves_the_combined_verdict_but_not_the_source_only_one(
        self, b32_engine, resolved_target
    ):
        _investigate_with_weak_source(b32_engine, resolved_target)
        before = reference_verdict(b32_engine, resolved_target, policy())
        assert before.qualifies is False and before.compounds == 1

        _add_supplement(b32_engine, resolved_target)

        combined = reference_verdict(b32_engine, resolved_target, policy())
        assert combined.qualifies is True
        assert combined.compounds == 2 and combined.compounds_active == 1

        source_only = reference_verdict(
            b32_engine, resolved_target, policy(), include_supplements=False
        )
        # Same stored rows, one stated scope: the sources alone still say weak.
        assert source_only.qualifies is False
        assert source_only.compounds == 1 and source_only.compounds_active == 0
        assert source_only.compounds_weak == 1
        assert "sparse and weak" in source_only.reason

    def test_a_structureless_remark_is_visible_in_combined_and_absent_from_source_only(
        self, b32_engine, resolved_target
    ):
        _investigate_with_weak_source(b32_engine, resolved_target)
        _add_supplement(b32_engine, resolved_target, smiles=None, value=None)

        combined = reference_verdict(b32_engine, resolved_target, policy())
        assert combined.supplement_remarks == 1
        assert "literature remark" in combined.reason

        source_only = reference_verdict(
            b32_engine, resolved_target, policy(), include_supplements=False
        )
        assert source_only.supplement_remarks == 0
        assert "literature remark" not in source_only.reason
        assert source_only.compounds == 1

    def test_a_withdrawn_row_is_outside_both_counts_and_reported_by_combined_only(
        self, b32_engine, resolved_target
    ):
        _investigate_with_weak_source(b32_engine, resolved_target)
        result = _add_supplement(b32_engine, resolved_target)
        outcome = next(o for o in result.rows if o.status in ("measurement", "remark"))
        withdraw_supplement(
            b32_engine, resolved_target.id, outcome.record_id, "cross-read fixture: taken back"
        )

        combined = reference_verdict(b32_engine, resolved_target, policy())
        source_only = reference_verdict(
            b32_engine, resolved_target, policy(), include_supplements=False
        )
        # A retracted row is in neither count; only the workspace verdict owes the
        # reader the explanation that a row was taken back.
        assert combined.compounds == 1 and source_only.compounds == 1
        assert combined.withdrawn_supplements == 1
        assert source_only.withdrawn_supplements == 0
        assert "withdrawn" in combined.reason
        assert "withdrawn" not in source_only.reason

    def test_records_without_structure_is_a_source_fact_in_both_scopes(
        self, b32_engine, resolved_target
    ):
        _investigate_with_weak_source(b32_engine, resolved_target)
        _add_supplement(b32_engine, resolved_target)
        # The rejection tally lives on the source retrieval's own record; it says
        # nothing about supplements and must survive the scoping unchanged.
        with b32_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE source_retrievals SET rejection_counts = :counts "
                    "WHERE target_id = :tid AND source_name = 'chembl'"
                ),
                {
                    "tid": resolved_target.id,
                    "counts": json.dumps({"missing_structure": 3}),
                },
            )
        combined = reference_verdict(b32_engine, resolved_target, policy())
        source_only = reference_verdict(
            b32_engine, resolved_target, policy(), include_supplements=False
        )
        assert combined.records_without_structure == 3
        assert source_only.records_without_structure == 3

    def test_the_batch_read_scopes_every_target_the_same_way(
        self, b32_engine, resolved_target
    ):
        from types import SimpleNamespace

        _investigate_with_weak_source(b32_engine, resolved_target)
        _add_supplement(b32_engine, resolved_target)
        # A second target in the batch that holds no rows at all: the batch read
        # must scope the first target without touching the second's answer.
        other = SimpleNamespace(id=uuid.uuid4(), target_key="OTHER", name="other target")

        combined = reference_verdicts(b32_engine, [resolved_target, other], policy())
        source_only = reference_verdicts(
            b32_engine, [resolved_target, other], policy(), include_supplements=False
        )
        assert combined[resolved_target.id].compounds == 2
        assert source_only[resolved_target.id].compounds == 1
        assert combined[other.id].compounds == source_only[other.id].compounds == 0


# --- the pack script's own plumbing -------------------------------------------------


def _script_module():
    """`scripts/cohort_pack.py` loaded by path — it is not a package."""
    spec = importlib.util.spec_from_file_location(
        "cohort_pack_script", REPO_ROOT / "scripts" / "cohort_pack.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pack():
    return _script_module()


class TestBuildComparison:
    def test_a_matching_expectation_passes_and_is_recorded(self, pack, monkeypatch):
        monkeypatch.setattr(
            pack,
            "_fetch_health",
            lambda url, timeout: {
                "build_id": "abc1234-dirty",
                "build_source": "env",
                "api_version": "0.1.0",
            },
        )
        block, code = pack._build_block("http://stub", 1.0, "abc1234-dirty")
        assert code == 0
        assert block["build_id"] == "abc1234-dirty" and block["match"] is True
        assert block["healthz"]["api_version"] == "0.1.0"

    def test_a_mismatched_expectation_fails(self, pack, monkeypatch):
        monkeypatch.setattr(
            pack,
            "_fetch_health",
            lambda url, timeout: {"build_id": "fff0000", "build_source": "env"},
        )
        block, code = pack._build_block("http://stub", 1.0, "abc1234-dirty")
        assert code == 1 and block["match"] is False

    def test_an_unknown_served_identity_never_matches_a_real_expectation(
        self, pack, monkeypatch
    ):
        monkeypatch.setattr(
            pack,
            "_fetch_health",
            lambda url, timeout: {"build_id": "unknown", "build_source": "unknown"},
        )
        _block, code = pack._build_block("http://stub", 1.0, "abc1234-dirty")
        assert code == 1

    def test_no_expectation_records_an_unknown_without_failing(self, pack, monkeypatch):
        monkeypatch.setattr(
            pack,
            "_fetch_health",
            lambda url, timeout: {"build_id": "unknown", "build_source": "unknown"},
        )
        block, code = pack._build_block("http://stub", 1.0, None)
        assert code == 0 and block["match"] == "not checked"

    def test_an_unreachable_server_is_not_a_pass(self, pack, monkeypatch):
        def boom(url, timeout):
            raise OSError("connection refused")

        monkeypatch.setattr(pack, "_fetch_health", boom)
        block, code = pack._build_block("http://stub", 1.0, None)
        assert code == 1 and block["status"] == "unreachable"

    def test_usage_refusals(self, pack):
        assert pack.main(["--expected-build", "unknown"]) == 2
        assert pack.main(["TSLP"]) == 2  # no output target given


class TestStratificationAndRendering:
    def test_stratification_counts_the_reviewer_hooks_separately(self, pack):
        records = [
            {
                "evidence_class": "measured_direct_binding",
                "relation": "=",
                "activity_class": "active",
                "is_supplement": False,
                "in_scope": True,
                "smiles_stored": True,
                "inchikey": "AAAAAA",
                "source_declared_patent": "US1",
                "corpus_occurrences": 0,
            },
            {
                "evidence_class": "functional_effect",
                "relation": "<",
                "activity_class": "unknown",
                "is_supplement": True,
                "in_scope": False,
                "smiles_stored": False,
                "inchikey": None,
                "source_declared_patent": None,
                "corpus_occurrences": 2,
            },
        ]
        strat = pack._stratification(records)
        assert strat["records"] == 2
        assert strat["records_in_policy_scope"] == 1
        assert strat["by_evidence_class"] == {
            "measured_direct_binding": 1,
            "functional_effect": 1,
        }
        assert strat["by_relation"] == {"=": 1, "<": 1}
        assert strat["supplement_records"] == 1
        assert strat["stereochemistry_stored_smiles_and_inchikey"] == 1
        # Declared and occurring are carried through separately, never merged.
        assert strat["records_with_source_declared_patent"] == 1
        assert strat["source_declared_patents"] == ["US1"]
        assert strat["records_with_corpus_occurrence"] == 1

    def test_the_markdown_states_both_verdicts_and_the_machine_limits(self, pack):
        verdict = {
            "qualifies": True,
            "reason": "1 of 1 in-scope compound(s) at or below 10 µM.",
            "compounds": 1,
            "compounds_active": 1,
            "compounds_weak": 0,
            "compounds_unknown": 0,
            "compounds_not_applicable": 0,
            "measurements": 1,
            "records_without_structure": 0,
            "active_compounds_outside_scope": 0,
            "policy": {
                "version": "potency-gate-v1",
                "threshold_label": "10 µM",
                "modality_scope": "small molecules and unclassified entities",
            },
        }
        record = {
            "generated_at": "2026-09-16T00:00:00+00:00",
            "generator": {"checkout": "test-dirty", "spago_core_version": "0.1.0"},
            "json_path": "benchmarks/test.json",
            "requested_cohort": ["TSLP"],
            "build": {
                "status": "ok",
                "fetched_from": "http://stub/healthz",
                "build_id": "test-dirty",
                "build_source": "env",
                "expected_build_id": "test-dirty",
                "match": True,
                "healthz": {"api_version": "0.1.0", "dataset_version": "demo", "status": "ok"},
            },
            "schema": {
                "status": "ok",
                "applied_count": 1,
                "applied": [{"version": 1, "filename": "0001_init.sql"}],
                "pending_in_generator_checkout": [],
            },
            "policy": {
                "version": "potency-gate-v1",
                "threshold_nm": 10_000.0,
                "threshold_label": "10 µM",
                "min_compounds": 10,
                "modality_scope": "small molecules and unclassified entities",
            },
            "query_bounds": {
                "verdict_read_cap_per_target": 5000,
                "retrieval_defaults_if_re_investigated": {"http_timeout_s": 25.0},
            },
            "targets": [
                {
                    "query": "TSLP",
                    "resolution": "stored target TSLP",
                    "target": {
                        "target_key": "TSLP",
                        "name": "Thymic stromal lymphopoietin",
                        "uniprot_accession": "Q969D9",
                        "target_type": "single_protein",
                        "organism": "Homo sapiens",
                        "source_name": "uniprot",
                        "dataset_version": "uniprot:2026-09-15",
                    },
                    "sources": [],
                    "verdict_source_only": verdict,
                    "verdict_combined": dict(verdict, compounds=2),
                    "stratification": {
                        "records": 2,
                        "records_in_policy_scope": 1,
                        "by_evidence_class": {"measured_direct_binding": 2},
                        "by_relation": {"=": 2},
                        "by_activity_class": {"active": 2},
                        "supplement_records": 1,
                        "stereochemistry_stored_smiles_and_inchikey": 2,
                        "records_with_source_declared_patent": 0,
                        "source_declared_patents": [],
                        "records_with_corpus_occurrence": 0,
                    },
                    "records_truncated": False,
                }
            ],
            "limits": list(pack.LIMITS),
        }
        rendered = pack._render_markdown(record)
        assert "Verdict (source-only)" in rendered
        assert "Verdict (combined workspace)" in rendered
        assert "build_id `test-dirty`" in rendered and "match: **yes**" in rendered
        assert "## Limits" in rendered
        assert "cannot approve" in rendered
        assert "declared and occurring are counted separately" in rendered
