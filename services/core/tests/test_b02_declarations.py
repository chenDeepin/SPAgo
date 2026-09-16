"""B-02: how far a source's data can actually be linked to a patent.

The product's central relation is "this compound was reported in this document".
A retrieval that cannot establish it must say so *and* say why: "the source does
not know the document id", "the lookup bound was reached" and "the document
declares no patent" are three different facts, and the first two are facts about
our retrieval, not about the compound.

These tests drive the shipped path (adapter → stored retrieval → API) and pin:

- every kept record lands in exactly one bucket, so the tally can be checked
  against `records_kept` rather than taken on faith;
- a bound being reached is counted and named, never rounded into "no patent";
- a failed lookup is reported as a failure, not as an absence;
- a measurement reachable through two ChEMBL target definitions is counted once;
- a retrieval stored before the tally existed reports "not recorded", which is
  not zero.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bioactivity_base import ActivityRecord
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.db import run_migrations
from spago_core.domain import (
    ACTIVITY_WITHOUT_DOCUMENT,
    DOCUMENT_NOT_RETRIEVED_BOUND,
    DOCUMENT_NOT_RETRIEVED_FAILURE,
    DOCUMENT_REFERENCE_STATUSES,
    DOCUMENT_UNKNOWN_TO_SOURCE,
    DOI_ONLY,
    MISSING_REFERENCE_STATUSES,
    NO_REFERENCE_FROM_SOURCE,
    NO_REFERENCE_ON_DOCUMENT,
    PATENT_DECLARED,
    document_reference_counts,
)
from spago_core.main import create_app
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_source_retrievals,
)

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture

TSLP_ACCESSION = "Q969D9"
SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"

#: The recorded TSLP activity page cites four documents; the recorded document
#: payload answers for two of them (one patent, one publication) and is silent
#: about the rest. That asymmetry is the point of these tests.
TSLP_PATENT_DOCUMENT = {
    "documents": [
        {
            "doc_type": "PATENT",
            "document_chembl_id": "CHEMBL5537198",
            "doi": None,
            "patent_id": "EP-2345678-A1",
            "pubmed_id": None,
            "year": 2011,
        }
    ],
    "page_meta": {"limit": 20, "offset": 0, "total_count": 1, "next": None, "previous": None},
}


def _adapter(documents, **kwargs) -> ChEMBLDiscoveryAdapter:
    return ChEMBLDiscoveryAdapter(
        client=StubSourceClient(
            {
                "target.json": load_fixture("chembl_targets_Q969D9.json"),
                "activity.json": load_fixture("chembl_activities_TSLP.json"),
                "document.json": documents,
            }
        ),
        **kwargs,
    )


def _tally(adapter: ChEMBLDiscoveryAdapter):
    result = adapter.activities("CHEMBL3712931")
    return result, document_reference_counts(result.records)


class TestTheVocabulary:
    def test_an_unknown_status_raises_rather_than_becoming_a_bucket(self):
        record = ActivityRecord(
            source_record_id="r1",
            compound_source_id=SMALL_MOLECULE,
            target_key="T",
            assay_key="A",
            standard_type="IC50",
            value=1.0,
            unit="nM",
        )
        record.document_reference_status = "probably_a_patent"
        with pytest.raises(ValueError, match="Unknown document-reference status"):
            document_reference_counts([record])

    def test_an_empty_retrieval_tallies_to_nothing(self):
        assert document_reference_counts([]) == {}

    def test_a_missing_reference_is_never_a_declared_one(self):
        # The subset that means "no reference attached" is exactly the vocabulary
        # minus the three that mean a reference was found.
        declared = {PATENT_DECLARED, DOI_ONLY, "pmid_only"}
        assert MISSING_REFERENCE_STATUSES == set(DOCUMENT_REFERENCE_STATUSES) - declared


class TestAdapterTally:
    def test_every_kept_record_lands_in_exactly_one_bucket(self):
        result, counts = _tally(
            _adapter(
                {
                    "documents": [
                        {
                            "doc_type": "PATENT",
                            "document_chembl_id": "CHEMBL5537198",
                            "patent_id": "EP-2345678-A1",
                        },
                        {
                            "doc_type": "PUBLICATION",
                            "document_chembl_id": "CHEMBL4043230",
                            "doi": "10.1016/j.bmcl.2017.09.010",
                            "pubmed_id": 28927768,
                        },
                    ]
                }
            )
        )
        assert sum(counts.values()) == len(result.records)
        assert result.document_reference_counts == counts
        # The recorded page keeps three records (one activity carries no numeric
        # value and is counted in `rejection_counts` instead): one cites the
        # patent document, one the publication, one a document the source does
        # not return.
        assert result.records_excluded == 1
        assert counts[PATENT_DECLARED] == 1
        assert counts[DOI_ONLY] == 1
        assert counts[DOCUMENT_UNKNOWN_TO_SOURCE] == 1

    def test_a_document_the_source_does_not_know_is_not_no_patent(self):
        _result, counts = _tally(_adapter({"documents": [], "page_meta": {"total_count": 0}}))
        # The source answered "no such documents"; that is a statement about the
        # document id, not a statement that the compound has no patent.
        assert counts == {DOCUMENT_UNKNOWN_TO_SOURCE: 3}
        assert NO_REFERENCE_ON_DOCUMENT not in counts

    def test_the_bound_is_counted_and_named(self):
        _result, counts = _tally(
            _adapter(
                {"documents": [], "page_meta": {"total_count": 0}},
                # No request is allowed at all, so every document that the page
                # cites stays unresolved for a stated reason.
                max_document_lookups=0,
            )
        )
        assert counts[DOCUMENT_NOT_RETRIEVED_BOUND] == 3
        # A bound is a configuration fact. It must never be reported as the
        # source having no reference.
        assert MISSING_REFERENCE_STATUSES >= set(counts)
        assert DOCUMENT_UNKNOWN_TO_SOURCE not in counts

    def test_a_failed_lookup_is_counted_as_a_failure(self):
        from spago_core.adapters.http import SourceUnavailableError

        _result, counts = _tally(
            _adapter(SourceUnavailableError("chembl", "HTTP 503"))
        )
        assert counts == {DOCUMENT_NOT_RETRIEVED_FAILURE: 3}

    def test_a_record_without_a_document_is_counted_as_such(self):
        without = load_fixture("chembl_activities_TSLP.json")
        for activity in without["activities"]:
            activity["document_chembl_id"] = None
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "activity.json": without,
                    "document.json": {"documents": [], "page_meta": {"total_count": 0}},
                }
            )
        )
        result = adapter.activities("CHEMBL3712931")
        # Nothing to resolve, so nothing was asked for — and the bucket is not a
        # statement about patents, only about what the row carried.
        assert result.document_reference_counts == {ACTIVITY_WITHOUT_DOCUMENT: 3}
        assert not [call for call in adapter.client.calls if "document.json" in call[0]]

    def test_records_excluded_for_a_missing_value_are_not_in_the_tally(self):
        payload = load_fixture("chembl_activities_TSLP.json")
        for activity in payload["activities"]:
            activity["standard_value"] = None
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "activity.json": payload,
                    "document.json": {"documents": [], "page_meta": {"total_count": 0}},
                }
            )
        )
        result = adapter.activities("CHEMBL3712931")
        # Nothing was kept, so nothing is tallied: the two tallies describe
        # different sets and must not be added together.
        assert result.records == []
        assert result.records_excluded == 4
        assert result.document_reference_counts == {}


@pytest.fixture(scope="module")
def b02_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_tables(b02_engine):
    with b02_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture()
def stored_target(b02_engine):
    from spago_core.adapters.uniprot import UniProtTargetResolver
    from spago_core.services.targets import TargetResolutionService

    resolver = UniProtTargetResolver(
        client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
    )
    outcome = TargetResolutionService(uniprot=resolver).resolve(b02_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


def _investigate(engine, target, adapter):
    service = TargetDiscoveryService(
        chembl=adapter,
        bindingdb=ChEMBLDiscoveryAdapter(client=StubSourceClient({})),
        pubchem=None,
    )
    service.investigate(engine, target, sources=["chembl"])


class TestStoredAndServed:
    def test_the_retrieval_stores_its_tally_and_serves_it(self, b02_engine, stored_target):
        adapter = _adapter(
            {
                "documents": [
                    {
                        "doc_type": "PATENT",
                        "document_chembl_id": "CHEMBL5537198",
                        "patent_id": "EP-2345678-A1",
                    },
                    {
                        "doc_type": "PUBLICATION",
                        "document_chembl_id": "CHEMBL4043230",
                        "doi": "10.1016/j.bmcl.2017.09.010",
                        "pubmed_id": 28927768,
                    },
                ]
            }
        )
        _investigate(b02_engine, stored_target, adapter)

        retrievals = list_source_retrievals(b02_engine, stored_target.id)
        chembl = next(r for r in retrievals if r.source_name == "chembl")
        assert chembl.reference_counts == {
            PATENT_DECLARED: 1,
            DOI_ONLY: 1,
            DOCUMENT_UNKNOWN_TO_SOURCE: 1,
        }
        # The invariant survives the round trip through jsonb.
        assert sum(chembl.reference_counts.values()) == chembl.records_kept

        app = create_app()
        app.state.engine = b02_engine
        with TestClient(app) as client:
            served = client.get(f"/api/v1/targets/{stored_target.id}/coverage")
        assert served.status_code == 200
        row = next(r for r in served.json() if r["source_name"] == "chembl")
        assert row["reference_counts"] == chembl.reference_counts
        # The warning that used to be written but never rendered is served too.
        assert isinstance(row["warnings"], list)

    def test_a_source_that_states_no_reference_says_so(self, b02_engine, stored_target):
        # BindingDB states its reported reference on the row (or not at all), so
        # there is no second lookup to diagnose — and the stored tally must still
        # be a real count, not the empty "not recorded" state that means a run
        # predates the tally.
        from spago_core.adapters.bioactivity_base import ActivityRecord
        from tests.open_source_stubs import StubActivityAdapter

        def row(record_id: str) -> ActivityRecord:
            return ActivityRecord(
                source_record_id=record_id,
                compound_source_id="CC(=O)Oc1ccccc1C(=O)O",
                target_key="Q15416",
                assay_key=f"STUB:{record_id}",
                assay_type="B",
                standard_type="IC50",
                value=5.0,
                unit="nM",
                raw_smiles="CC(=O)Oc1ccccc1C(=O)O",
                source_name="bindingdb",
            )

        service = TargetDiscoveryService(
            chembl=ChEMBLDiscoveryAdapter(client=StubSourceClient({})),
            bindingdb=StubActivityAdapter([row("b1"), row("b2")]),
            pubchem=None,
        )
        service.investigate(b02_engine, stored_target, sources=["bindingdb"])
        row_stored = next(
            r for r in list_source_retrievals(b02_engine, stored_target.id)
            if r.source_name == "bindingdb"
        )
        assert row_stored.records_kept == 2
        assert row_stored.reference_counts == {NO_REFERENCE_FROM_SOURCE: 2}
        assert sum(row_stored.reference_counts.values()) == row_stored.records_kept

    def test_a_measurement_reachable_twice_is_counted_once(self, b02_engine, stored_target):
        # The recorded target lookup resolves Q969D9 to one target id; a second
        # plan entry for the same activity id (a single-protein and an
        # interaction definition) must not double the tally, because the study
        # object is one measurement.
        adapter = _adapter({"documents": [], "page_meta": {"total_count": 0}})
        original = adapter.activities

        def twice(target_chembl_id, target_type=None):
            return original(target_chembl_id, target_type)

        adapter.activities = twice  # type: ignore[method-assign]
        _investigate(b02_engine, stored_target, adapter)
        chembl = next(
            r for r in list_source_retrievals(b02_engine, stored_target.id)
            if r.source_name == "chembl"
        )
        assert sum(chembl.reference_counts.values()) == chembl.records_kept

    def test_a_run_without_the_tally_reports_not_recorded(self, b02_engine, stored_target):
        _investigate(
            b02_engine,
            stored_target,
            _adapter({"documents": [], "page_meta": {"total_count": 0}}),
        )
        # A retrieval stored before migration 0016 has `{}`. The read path must
        # keep that distinct from "kept records with no reference".
        with b02_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE source_retrievals SET reference_counts = '{}'::jsonb "
                    "WHERE target_id = :tid"
                ),
                {"tid": stored_target.id},
            )
        chembl = next(
            r for r in list_source_retrievals(b02_engine, stored_target.id)
            if r.source_name == "chembl"
        )
        assert chembl.reference_counts == {}
        assert chembl.records_kept > 0
