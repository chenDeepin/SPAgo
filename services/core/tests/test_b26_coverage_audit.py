"""B-26: what SPAgo holds for a publication, from where, and what nobody asked.

Four independent paths can contribute chemistry to one publication — the imported
corpus, a per-publication source lookup (B-24), a target-led source row (B-02) and a
person's hand-added row (ONLINE-07/B-25) — and before this item nothing put them side
by side. These tests pin what makes the audit trustworthy rather than merely present:

- **`not_queried` is not `empty`.** A leg nobody asked is reported as never asked and
  named in `unqueried`; "we never asked" must never read as "the publication has
  nothing" (AGENTS.md §11).
- **legs are never summed.** A declared compound is not a corpus occurrence, and a
  hand-added row is not a source's declaration; each count stays in its leg and the
  headline names the leg it came from.
- **a failed ask is not an answer.** A lookup stored as `failed` stays visible as
  failed, and the rows it still holds are attributed to their last successful
  retrieval rather than to the failed attempt.
- **a proposal is not coverage.** Unconfirmed bundle rows (B-25) are counted and
  reported, and they never make the headline a record.
- **matching is the codebase's one rule** (B-03): the number a person typed is compared
  through `patent_tokens`, and the stored identifier that answered is reported — the
  request is never rewritten, and two stored identifiers are reported, not chosen
  between.

The corpus here is a family this module creates, and the external answers come from the
recorded transport fixtures in `data/fixtures/open_sources/`; no number in this module
is a scientific claim.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.chembl_discovery import (
    MATCH_RULE as DECLARED_MATCH_RULE,
    ChEMBLDiscoveryAdapter,
)
from spago_core.adapters.http import SourceUnavailableError
from spago_core.chemistry import normalize
from spago_core.db import run_migrations
from spago_core.domain import ProvenanceState
from spago_core.main import create_app
from spago_core.services import coverage as coverage_svc
from spago_core.services.patent_sources import PatentSourceService
from spago_core.services.supplements import import_supplements, withdraw_supplement

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture

#: The family and documents this module owns. The scratch database is truncated per
#: test, so these identifiers never collide with another module's corpus.
FAMILY_KEY = "B26-FAMILY-1"
CORPUS_DOC = "US-20130089624-A1"  # imported, and holds a compound mention
THIN_DOC = "EP-3000000-A1"  # imported, and holds no live mention

#: A number the stub source declares a set for, absent from this module's corpus.
DECLARED_NUMBER = "US10508115"
#: A number the stub source answers `empty` for (it knows no such document).
ASKED_EMPTY_NUMBER = "US9999999999"
#: A number nobody asked anything about.
NEVER_ASKED = "WO2020123456"

#: A hand-added row cites this publication.
SUPPLEMENT_PATENT = "US8618102"
#: ...and this one is cited only by an unconfirmed proposal.
PROPOSED_PATENT = "EP1234567"

COMPOUND_SMILES = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
HAND_SMILES = "CC(=O)Oc1ccccc1C(=O)O"
PROPOSED_SMILES = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"
TSLP_ACCESSION = "Q969D9"

SOURCE_DOCUMENT = "chembl_document_US10508115.json"
SOURCE_ACTIVITIES = "chembl_patent_activities_US10508115.json"
EMPTY_DOCUMENTS = {
    "documents": [],
    "page_meta": {"limit": 100, "offset": 0, "total_count": 0},
}


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture()
def clean_tables(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


pytestmark = pytest.mark.usefixtures("clean_tables")


# --- the world these tests read ----------------------------------------------------


def _insert_compound(conn, smiles: str) -> uuid.UUID:
    structure = normalize(smiles)
    compound_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO compounds (id, canonical_smiles, inchikey, dataset_version)
            VALUES (:id, :smiles, :inchikey, 'b26-test')
            """
        ),
        {"id": compound_id, "smiles": structure.canonical_smiles, "inchikey": structure.inchikey},
    )
    return compound_id


def _insert_family(conn, key: str, documents: list[str]) -> uuid.UUID:
    family_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO patent_families (id, family_key, title, source_name,
                                         dataset_version, retrieved_at)
            VALUES (:id, :key, 'B-26 test family', 'stub', 'corpus:b26-test', now())
            """
        ),
        {"id": family_id, "key": key},
    )
    for number in documents:
        conn.execute(
            text(
                """
                INSERT INTO patent_documents (id, family_id, publication_number, doc_type,
                                              source_name, dataset_version, retrieved_at)
                VALUES (:id, :fid, :pn, 'A1', 'stub', 'corpus:b26-test', now())
                """
            ),
            {"id": uuid.uuid4(), "fid": family_id, "pn": number},
        )
    return family_id


def _insert_target(conn, key: str = "B26-TARGET") -> uuid.UUID:
    target_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO targets (id, target_key, name, organism, source_name,
                                 dataset_version, retrieved_at)
            VALUES (:id, :key, 'TSLP', 'Homo sapiens', 'uniprot', 'uniprot:test', now())
            """
        ),
        {"id": target_id, "key": key},
    )
    return target_id


def _insert_assay(conn, target_id: uuid.UUID, key: str = "B26-ASSAY") -> uuid.UUID:
    assay_id = uuid.uuid4()
    conn.execute(
        text(
            """
            INSERT INTO assays (id, assay_key, target_id, source_name, dataset_version,
                                retrieved_at)
            VALUES (:id, :key, :tid, 'chembl', 'chembl:b26-test', now())
            """
        ),
        {"id": assay_id, "key": key, "tid": target_id},
    )
    return assay_id


@pytest.fixture()
def world(online_engine, clean_tables):
    """One owned family with two documents, a mentioned compound and a target.

    `CORPUS_DOC` holds one live mention; `THIN_DOC` is imported and holds none — the
    pair is what makes "imported but without compounds" (asked, empty) testable
    against "not imported at all" (never asked).
    """
    with online_engine.begin() as conn:
        compounds = [_insert_compound(conn, COMPOUND_SMILES)]
        family_id = _insert_family(conn, FAMILY_KEY, [CORPUS_DOC, THIN_DOC])
        document_id = conn.execute(
            text("SELECT id FROM patent_documents WHERE publication_number = :pn"),
            {"pn": CORPUS_DOC},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO compound_mentions (id, compound_id, document_id, patent_label,
                                               source_name, dataset_version, retrieved_at)
                VALUES (:id, :cid, :did, 'Example 7', 'stub', 'corpus:b26-test', now())
                """
            ),
            {"id": uuid.uuid4(), "cid": compounds[0], "did": document_id},
        )
        target_id = _insert_target(conn)
        assay_id = _insert_assay(conn, target_id)
    return SimpleNamespace(
        engine=online_engine,
        family_id=family_id,
        document_id=document_id,
        compound_id=compounds[0],
        target_id=target_id,
        assay_id=assay_id,
    )


# --- seeding helpers for the other three paths -------------------------------------


def _declared_service(documents=None) -> PatentSourceService:
    return PatentSourceService(
        chembl=ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "document.json": (
                        documents if documents is not None else load_fixture(SOURCE_DOCUMENT)
                    ),
                    "activity.json": load_fixture(SOURCE_ACTIVITIES),
                }
            )
        )
    )


def ask_declared(engine, number: str = DECLARED_NUMBER) -> dict:
    """A stored per-publication lookup, through the shipped B-24 path."""
    return _declared_service().lookup(engine, number)


def ask_declared_empty(engine, number: str = ASKED_EMPTY_NUMBER) -> dict:
    return _declared_service(documents=EMPTY_DOCUMENTS).lookup(engine, number)


def fail_declared(engine, number: str = DECLARED_NUMBER) -> dict:
    failing = _declared_service(
        documents=SourceUnavailableError("chembl", "HTTP 503 for document.json", status_code=503)
    )
    return failing.lookup(engine, number)


def add_target_led_row(world, number: str = DECLARED_NUMBER) -> None:
    """A stored retrieval row (B-02) that names a publication as its document."""
    with world.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                          unit, relation, source_record_id, source_name,
                                          extraction_method, provenance_state,
                                          dataset_version, retrieved_at,
                                          document_patent_number)
                VALUES (:id, :cid, :aid, 'IC50', 12.0, 'nM', '=', 'CHEMBL-ACT-1', 'chembl',
                        'source_payload', 'database_curated', 'chembl:b26-test', now(),
                        :pn)
                """
            ),
            {
                "id": uuid.uuid4(),
                "cid": world.compound_id,
                "aid": world.assay_id,
                "pn": number,
            },
        )


def add_hand_row(
    world,
    number: str = SUPPLEMENT_PATENT,
    *,
    smiles: str = HAND_SMILES,
    name: str = "compound 7",
) -> None:
    """A person's own row (the shipped ONLINE-07 path), citing a publication."""
    result = import_supplements(
        world.engine,
        world.target_id,
        [
            {
                "name": name,
                "note": "Table 2 of the paper",
                "smiles": smiles,
                "activity_type": "IC50",
                "value": 4.0,
                "unit": "nM",
                "patent_number": number,
            }
        ],
    )
    assert result.received == 1 and result.measurements + result.remarks == 1
    assert [row.status for row in result.rows] != ["rejected"]


def add_proposed_row(
    world, number: str = PROPOSED_PATENT, *, target_id: uuid.UUID | None = None
) -> None:
    """An unconfirmed proposal (an agent bundle's row, B-25) citing a publication."""
    result = import_supplements(
        world.engine,
        target_id or world.target_id,
        [
            {
                "name": "compound 9",
                "note": "Table 3 of the paper",
                "smiles": PROPOSED_SMILES,
                "activity_type": "IC50",
                "value": 40.0,
                "unit": "nM",
                "patent_number": number,
            }
        ],
        provenance_state=ProvenanceState.LLM_INFERRED,
    )
    assert result.received == 1 and result.measurements + result.remarks == 1
    assert [row.status for row in result.rows] != ["rejected"]


def seed_declared_lookup(world, token: str, *, compounds: int = 2) -> None:
    """A stored per-publication lookup, written the way the B-24 service writes it.

    Used where a test needs a declared set under a *specific* token (the precedence
    tests): the shipped path is driven through the recorded fixture in the class
    above, and a fixture file only speaks for one publication.
    """
    lookup_id = uuid.uuid4()
    with world.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO patent_source_lookups (id, publication_number, requested_number,
                                                   source_name, source_version, dataset_version,
                                                   match_rule, status, documents, near_matches,
                                                   warnings, rejection_counts, records_seen,
                                                   records_excluded, bounds, retrieved_at)
                VALUES (:id, :pn, :pn, 'chembl', '34', 'chembl:b26-test',
                        :rule, 'complete', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb,
                        :seen, 0, '{}'::jsonb, now())
                """
            ),
            {
                "id": lookup_id,
                "pn": token,
                "rule": DECLARED_MATCH_RULE,
                "seen": compounds,
            },
        )
        for index in range(compounds):
            structure = normalize(["O=C(O)c1ccccc1", "O=C(O)c1ccc(O)cc1",
                                   "O=C(O)c1ccncc1"][index % 3])
            compound_id = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO compounds (id, canonical_smiles, inchikey, dataset_version)
                    VALUES (:id, :smiles, :inchikey, 'b26-test')
                    ON CONFLICT (inchikey) DO NOTHING
                    """
                ),
                {
                    "id": compound_id,
                    "smiles": structure.canonical_smiles,
                    "inchikey": structure.inchikey,
                },
            )
            resolved = conn.execute(
                text("SELECT id FROM compounds WHERE inchikey = :k"),
                {"k": structure.inchikey},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO patent_source_compounds (id, lookup_id, compound_id,
                                                         source_record_id, standard_type,
                                                         value, unit, relation,
                                                         provenance_state, dataset_version,
                                                         retrieved_at)
                    VALUES (:id, :lid, :cid, :rid, 'IC50', :value, 'nM', '=',
                            'database_curated', 'chembl:b26-test', now())
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "lid": lookup_id,
                    "cid": resolved,
                    "rid": f"B26-ACT-{index}",
                    "value": 10.0 + index,
                },
            )


def _row(report, requested: str):
    return next(row for row in report.publications if row.requested == requested)


def _leg(row, name: str):
    return next(leg for leg in row.legs if leg.leg == name)


def _count(engine, table: str, where: str = "", params: dict | None = None) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text(f"SELECT count(*) FROM {table} {where}"), params or {}).scalar_one()
        )


# --- the corpus leg ----------------------------------------------------------------


class TestTheCorpusLeg:
    def test_a_stored_document_reports_its_mentions_and_compounds(self, world):
        report = coverage_svc.audit_publications(world.engine, [CORPUS_DOC])
        row = _row(report, CORPUS_DOC)
        assert row.status == "corpus"
        assert row.matched == CORPUS_DOC and row.in_corpus is True
        assert row.family_key == FAMILY_KEY and row.doc_type == "A1"
        leg = _leg(row, "corpus")
        assert leg.state == "has_records"
        assert leg.records == 1 and leg.compounds == 1
        assert leg.answers[0].kind == "corpus"
        assert leg.answers[0].dataset_version == "corpus:b26-test"
        assert row.unqueried == ["declared", "supplement"]

    def test_a_document_that_is_imported_without_mentions_was_asked_and_is_empty(self, world):
        row = _row(coverage_svc.audit_publications(world.engine, [THIN_DOC]), THIN_DOC)
        leg = _leg(row, "corpus")
        assert (leg.state, leg.records) == ("asked_empty", 0)
        assert "holds no live compound mention" in leg.detail
        # The corpus was asked; nothing else was, and the row says so.
        assert row.unqueried == ["declared", "supplement"]
        assert row.status == "empty"

    def test_a_number_the_corpus_never_imported_is_never_asked_not_absent(self, world):
        row = _row(coverage_svc.audit_publications(world.engine, [NEVER_ASKED]), NEVER_ASKED)
        leg = _leg(row, "corpus")
        assert leg.state == "not_queried"
        assert row.status == "not_queried"
        assert row.unqueried == ["corpus", "declared", "supplement"]
        assert "no document in the loaded corpus is stored under" in leg.detail

    def test_a_retracted_mention_stops_counting(self, world):
        with world.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE compound_mentions SET retracted_at = now() WHERE document_id = :d"
                ),
                {"d": world.document_id},
            )
        row = _row(coverage_svc.audit_publications(world.engine, [CORPUS_DOC]), CORPUS_DOC)
        assert _leg(row, "corpus").state == "asked_empty"
        assert row.status == "empty"

    def test_the_number_a_person_typed_reaches_the_same_document(self, world):
        report = coverage_svc.audit_publications(world.engine, ["US20130089624A1"])
        row = _row(report, "US20130089624A1")
        # Reported, never rewritten: the request and the stored identifier both travel.
        assert row.requested == "US20130089624A1"
        assert row.matched == CORPUS_DOC
        assert row.normalized == ["US20130089624"]
        assert row.status == "corpus"

    def test_two_stored_identifiers_are_reported_not_chosen_between(self, world):
        with world.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, doc_type,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:id, :fid, 'US20130089624B2', 'B2', 'stub', 'corpus:b26-test',
                            now())
                    """
                ),
                {"id": uuid.uuid4(), "fid": world.family_id},
            )
        # The token-only form misses both stored spellings, so the tolerant pass runs
        # and reports what it found rather than choosing (the rule `find_patent` uses:
        # an exact hit settles the question, a tolerant one must not).
        report = coverage_svc.audit_publications(world.engine, ["US20130089624"])
        row = _row(report, "US20130089624")
        assert row.matched == CORPUS_DOC
        assert row.ambiguous == ["US20130089624B2"]
        assert "reported, not merged" in _leg(row, "corpus").detail
        assert report.totals["ambiguous"] == 1


# --- the declared leg --------------------------------------------------------------


class TestTheDeclaredLeg:
    def test_a_stored_lookup_declares_compounds_for_a_number_the_corpus_lacks(self, world):
        view = ask_declared(world.engine)
        assert view["status"] == "complete" and view["row_count"] == 3

        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        assert row.status == "declared"
        assert row.in_corpus is False and row.matched is None
        leg = _leg(row, "declared")
        assert (leg.state, leg.records, leg.compounds) == ("has_records", 3, 3)
        answer = leg.answers[0]
        assert answer.kind == "patent_source_lookup"
        assert answer.source_name == "chembl"
        assert answer.match_rule == DECLARED_MATCH_RULE
        assert answer.dataset_version.startswith("chembl:")
        # The corpus leg was asked — by looking, and finding nothing.
        assert _leg(row, "corpus").state == "not_queried"
        assert row.unqueried == ["corpus", "supplement"]

    def test_the_declared_set_is_not_counted_as_a_corpus_occurrence(self, world):
        ask_declared(world.engine)
        assert _count(world.engine, "compound_mentions") == 1  # the module's own mention
        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        assert _leg(row, "corpus").state == "not_queried"
        assert _leg(row, "corpus").records == 0

    def test_an_empty_answer_is_an_answer_and_reads_as_asked_empty(self, world):
        view = ask_declared_empty(world.engine)
        assert view["status"] == "empty"
        row = _row(
            coverage_svc.audit_publications(world.engine, [ASKED_EMPTY_NUMBER]),
            ASKED_EMPTY_NUMBER,
        )
        leg = _leg(row, "declared")
        assert (leg.state, leg.records) == ("asked_empty", 0)
        assert "returned no declared compound" in leg.detail
        assert row.status == "empty"
        assert row.unqueried == ["corpus", "supplement"]

    def test_a_failed_ask_keeps_its_rows_and_still_reads_as_failed(self, world):
        ask_declared(world.engine)
        failed = fail_declared(world.engine)
        assert failed["status"] == "failed" and failed["row_count"] == 3

        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        leg = _leg(row, "declared")
        answer = leg.answers[0]
        assert leg.state == "has_records"  # the last successful set is still held
        assert answer.status == "failed" and answer.state == "has_records"
        assert "could not answer on the last attempt" in answer.detail
        # A record exists, and the row still says the picture is incomplete.
        assert row.status == "declared"
        assert "not the whole picture" in row.status_reason
        assert any("did not complete" in note for note in coverage_svc.audit_publications(
            world.engine, [DECLARED_NUMBER]
        ).notes)

    def test_a_failed_ask_without_rows_is_failed_not_empty(self, world):
        fail_declared(world.engine)
        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        leg = _leg(row, "declared")
        assert leg.state == "failed"
        assert row.status == "failed"
        assert "did not complete" in row.status_reason

    def test_a_target_led_row_says_the_source_declared_it_for_a_target(self, world):
        add_target_led_row(world)
        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        leg = _leg(row, "declared")
        assert leg.state == "has_records"
        answer = leg.answers[0]
        assert answer.kind == "target_led_source"
        assert answer.source_name == "chembl"
        assert answer.records == 1 and answer.compounds == 1
        assert "target-led retrieval name this publication" in answer.detail
        assert row.status == "declared"

    def test_a_lookup_and_a_target_led_row_are_two_answers_one_leg(self, world):
        ask_declared(world.engine)
        add_target_led_row(world)
        row = _row(coverage_svc.audit_publications(world.engine, [DECLARED_NUMBER]), DECLARED_NUMBER)
        leg = _leg(row, "declared")
        kinds = sorted(answer.kind for answer in leg.answers)
        assert kinds == ["patent_source_lookup", "target_led_source"]
        assert leg.records == 4
        # Distinct across both answers: three from the fixture, one from the
        # target-led row (a leg count, never a sum of per-answer counts).
        assert leg.compounds == 4

    def test_nobody_asked_is_a_third_state(self, world):
        row = _row(coverage_svc.audit_publications(world.engine, [NEVER_ASKED]), NEVER_ASKED)
        leg = _leg(row, "declared")
        assert leg.state == "not_queried" and leg.answers == []
        assert "no source has ever been asked" in leg.detail


# --- the supplement leg ------------------------------------------------------------


class TestTheSupplementLeg:
    def test_a_hand_added_row_citing_a_publication_is_its_own_leg(self, world):
        add_hand_row(world)
        row = _row(coverage_svc.audit_publications(world.engine, [SUPPLEMENT_PATENT]), SUPPLEMENT_PATENT)
        assert row.status == "supplement"
        leg = _leg(row, "supplement")
        assert (leg.state, leg.records, leg.compounds) == ("has_records", 1, 1)
        assert leg.targets == 1 and leg.unconfirmed_records == 0
        assert leg.answers[0].kind == "hand_added"
        assert row.unqueried == ["corpus", "declared"]

    def test_a_structure_less_remark_is_a_record_and_not_a_compound(self, world):
        result = import_supplements(
            world.engine,
            world.target_id,
            [
                {
                    "name": "compound 12",
                    "note": "no structure published",
                    "activity_type": "IC50",
                    "value": 90.0,
                    "unit": "nM",
                    "patent_number": SUPPLEMENT_PATENT,
                }
            ],
        )
        assert result.remarks == 1
        leg = _leg(
            _row(coverage_svc.audit_publications(world.engine, [SUPPLEMENT_PATENT]), SUPPLEMENT_PATENT),
            "supplement",
        )
        assert (leg.state, leg.records, leg.compounds) == ("has_records", 1, 0)

    def test_an_unconfirmed_proposal_is_counted_and_is_not_coverage(self, world):
        add_proposed_row(world)
        row = _row(coverage_svc.audit_publications(world.engine, [PROPOSED_PATENT]), PROPOSED_PATENT)
        assert row.status == "proposed"
        leg = _leg(row, "supplement")
        assert (leg.state, leg.records, leg.unconfirmed_records) == ("unconfirmed", 1, 1)
        assert "no person has confirmed" in leg.detail
        assert "await review" in row.status_reason
        assert row.unqueried == ["corpus", "declared"]

    def test_a_confirmed_row_outranks_a_proposal_beside_it(self, world):
        add_hand_row(world, SUPPLEMENT_PATENT)
        add_proposed_row(world, SUPPLEMENT_PATENT)
        row = _row(coverage_svc.audit_publications(world.engine, [SUPPLEMENT_PATENT]), SUPPLEMENT_PATENT)
        leg = _leg(row, "supplement")
        assert row.status == "supplement"
        assert (leg.state, leg.records, leg.unconfirmed_records) == ("has_records", 2, 1)
        assert leg.compounds == 2
        assert "await a person's confirmation" in leg.detail

    def test_a_withdrawn_row_leaves_the_leg_never_asked_again(self, world):
        add_hand_row(world)
        with world.engine.connect() as conn:
            record_id = conn.execute(
                text(
                    """
                    SELECT source_record_id FROM measurements
                    WHERE document_patent_number = :pn AND source_name = 'user_supplement'
                      AND retracted_at IS NULL
                    """
                ),
                {"pn": SUPPLEMENT_PATENT},
            ).scalar_one()
        withdrawn = withdraw_supplement(
            world.engine, world.target_id, record_id, "superseded by a re-read"
        )
        assert withdrawn.kind == "measurement" and withdrawn.record_id == record_id
        row = _row(coverage_svc.audit_publications(world.engine, [SUPPLEMENT_PATENT]), SUPPLEMENT_PATENT)
        assert _leg(row, "supplement").state == "not_queried"
        assert row.status == "not_queried"


# --- the headline ------------------------------------------------------------------


class TestTheHeadline:
    def test_the_corpus_outranks_a_declared_set_and_a_hand_added_row(self, world):
        """All three legs hold records for one publication; the corpus names it.

        The declared set and the hand-added row are both stored under the *token*
        of the corpus document (`US20130089624`), which is how the two later paths
        key their rows (B-02's `document_patent_number`, B-24's lookup).
        """
        seed_declared_lookup(world, "US20130089624", compounds=2)
        add_hand_row(world, "US20130089624")
        row = _row(coverage_svc.audit_publications(world.engine, [CORPUS_DOC]), CORPUS_DOC)
        assert [leg.state for leg in row.legs] == ["has_records", "has_records", "has_records"]
        assert row.status == "corpus"
        assert "the corpus holds compounds for this publication" in row.status_reason

    def test_a_declared_set_outranks_a_hand_added_row(self, world):
        seed_declared_lookup(world, SUPPLEMENT_PATENT, compounds=2)
        add_hand_row(world, SUPPLEMENT_PATENT)
        row = _row(coverage_svc.audit_publications(world.engine, [SUPPLEMENT_PATENT]), SUPPLEMENT_PATENT)
        assert row.status == "declared"
        assert "a person's own rows do" not in row.status_reason

    def test_a_failed_ask_outranks_an_empty_one(self, world):
        fail_declared(world.engine, ASKED_EMPTY_NUMBER)
        row = _row(
            coverage_svc.audit_publications(world.engine, [ASKED_EMPTY_NUMBER]),
            ASKED_EMPTY_NUMBER,
        )
        assert _leg(row, "corpus").state == "not_queried"
        assert row.status == "failed"

    def test_a_number_nobody_asked_about_is_never_queried_with_all_three_legs_named(self, world):
        report = coverage_svc.audit_publications(world.engine, [NEVER_ASKED])
        row = report.publications[0]
        assert row.status == "not_queried"
        assert row.unqueried == ["corpus", "declared", "supplement"]
        assert all(leg.state == "not_queried" for leg in row.legs)
        assert report.totals["not_fully_asked"] == 1
        assert report.totals["not_queried"] == 1

    def test_the_holding_total_counts_records_not_absences(self, world):
        """`holds_records` is what a surface reads for "N of M hold compounds": the
        four statuses that name a leg with records. An asked-and-empty or never-asked
        row is not holding anything, and must not be counted into that summary line
        (which is the whole reason the count lives in the service)."""
        fail_declared(world.engine, ASKED_EMPTY_NUMBER)
        seed_declared_lookup(world, SUPPLEMENT_PATENT)
        report = coverage_svc.audit_publications(
            world.engine, [CORPUS_DOC, SUPPLEMENT_PATENT, ASKED_EMPTY_NUMBER, NEVER_ASKED]
        )
        statuses = {row.requested: row.status for row in report.publications}
        assert statuses[CORPUS_DOC] == "corpus"
        assert statuses[SUPPLEMENT_PATENT] == "declared"
        assert report.totals["holds_records"] == 2
        assert report.totals["holds_records"] == sum(
            report.totals.get(status, 0)
            for status in ("corpus", "declared", "supplement", "proposed")
        )
        assert report.totals["publications"] == 4

    def test_every_row_carries_the_rule_that_produced_it(self, world):
        report = coverage_svc.audit_publications(world.engine, [CORPUS_DOC, NEVER_ASKED])
        assert report.rule == coverage_svc.COVERAGE_RULE
        assert report.rule_text.startswith("patent-coverage-v1")
        for row in report.publications:
            assert row.status_rule == coverage_svc.COVERAGE_RULE
            assert row.status_reason

    def test_the_report_states_what_it_cannot_see(self, world):
        report = coverage_svc.audit_publications(world.engine, [CORPUS_DOC])
        text = " ".join(report.notes)
        assert "reads stored rows only" in text
        assert "snapshot" in text  # the no-snapshot-leg limit is stated, not implied
        assert "not_queried" in text
        assert "never an 'absent' verdict" in text


# --- the request bound -------------------------------------------------------------


class TestTheRequestBound:
    def test_an_empty_list_is_refused_with_a_reason(self, world):
        with pytest.raises(coverage_svc.CoverageError, match="at least one publication"):
            coverage_svc.audit_publications(world.engine, [])

    def test_a_value_without_a_publication_number_is_refused(self, world):
        with pytest.raises(coverage_svc.CoverageError, match="carries a publication number"):
            coverage_svc.audit_publications(world.engine, ["TSLP", "thirteen elephants"])

    def test_a_list_over_the_bound_is_refused_rather_than_truncated(self, world):
        numbers = [f"US{1000000 + i}" for i in range(coverage_svc.MAX_COVERAGE_PUBLICATIONS + 1)]
        with pytest.raises(coverage_svc.CoverageError) as exc:
            coverage_svc.audit_publications(world.engine, numbers)
        assert str(coverage_svc.MAX_COVERAGE_PUBLICATIONS) in str(exc.value)
        assert "Split the list" in str(exc.value)

    def test_the_same_number_twice_yields_one_row(self, world):
        report = coverage_svc.audit_publications(
            world.engine, [CORPUS_DOC, CORPUS_DOC.lower(), " US-20130089624-A1 "]
        )
        assert len(report.publications) == 1
        assert report.totals["publications"] == 1


# --- the served surface ------------------------------------------------------------


def _client(engine):
    app = create_app()
    app.state.engine = engine
    return TestClient(app)


class TestTheServedSurface:
    def test_the_audit_is_served_and_carries_the_rule(self, world):
        body = _client(world.engine).post(
            "/api/v1/patents/coverage", json={"publications": [CORPUS_DOC, NEVER_ASKED]}
        ).json()
        assert body["rule"] == coverage_svc.COVERAGE_RULE
        assert body["rule_text"]
        assert [row["requested"] for row in body["publications"]] == [CORPUS_DOC, NEVER_ASKED]
        assert body["publications"][0]["status"] == "corpus"
        assert body["publications"][1]["status"] == "not_queried"
        assert body["publications"][1]["unqueried"] == ["corpus", "declared", "supplement"]

    def test_junk_is_refused_with_a_reason_not_an_empty_report(self, world):
        response = _client(world.engine).post(
            "/api/v1/patents/coverage", json={"publications": ["TSLP"]}
        )
        assert response.status_code == 422
        assert "carries a publication number" in response.json()["detail"]

    def test_an_empty_request_is_refused(self, world):
        response = _client(world.engine).post("/api/v1/patents/coverage", json={"publications": []})
        assert response.status_code == 422

    def test_every_count_can_be_re_derived_from_the_database(self, world):
        """The acceptance sketch: every status re-derivable from stored rows.

        The audit's numbers are compared with direct SQL over the same tables, not
        with constants: a report that disagreed with the rows it summarizes would be
        worse than no report.
        """
        ask_declared(world.engine)
        add_hand_row(world)
        body = _client(world.engine).post(
            "/api/v1/patents/coverage",
            json={"publications": [CORPUS_DOC, DECLARED_NUMBER, SUPPLEMENT_PATENT, NEVER_ASKED]},
        ).json()
        by_request = {row["requested"]: row for row in body["publications"]}
        legs = {
            (request, leg["leg"]): leg
            for request, row in by_request.items()
            for leg in row["legs"]
        }

        mentions = _count(
            world.engine,
            "current_compound_mentions",
            "WHERE document_id = :d",
            {"d": world.document_id},
        )
        assert legs[(CORPUS_DOC, "corpus")]["records"] == mentions == 1

        declared_rows = _count(
            world.engine,
            "patent_source_compounds c",
            "JOIN patent_source_lookups l ON l.id = c.lookup_id "
            "WHERE l.publication_number = :pn",
            {"pn": DECLARED_NUMBER},
        )
        assert legs[(DECLARED_NUMBER, "declared")]["records"] == declared_rows

        hand_rows = _count(
            world.engine,
            "measurements",
            "WHERE document_patent_number = :pn AND retracted_at IS NULL",
            {"pn": SUPPLEMENT_PATENT},
        )
        assert legs[(SUPPLEMENT_PATENT, "supplement")]["records"] == hand_rows == 1

        assert all(
            leg["state"] == "not_queried" for (request, _leg_name), leg in legs.items()
            if request == NEVER_ASKED
        )

    def test_the_markdown_export_is_a_file_that_states_its_rule(self, world):
        response = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "markdown"},
            json={"publications": [CORPUS_DOC, NEVER_ASKED]},
        )
        assert response.status_code == 200
        assert response.headers["X-Spago-Coverage-Rule"] == coverage_svc.COVERAGE_RULE
        assert response.headers["X-Spago-Coverage-Publications"] == "2"
        assert "spago-coverage-" in response.headers["Content-Disposition"]
        text = response.text
        assert "# Patent coverage audit (patent-coverage-v1)" in text
        assert NEVER_ASKED in text and "never asked" in text
        assert "## Notes" in text and "## Rule" in text

    def test_the_csv_export_is_long_form_and_self_contained(self, world):
        ask_declared(world.engine)
        response = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "csv"},
            json={"publications": [CORPUS_DOC, DECLARED_NUMBER]},
        )
        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert {(row["publication_requested"], row["leg"]) for row in rows} == {
            (CORPUS_DOC, "corpus"),
            (CORPUS_DOC, "declared"),
            (CORPUS_DOC, "supplement"),
            (DECLARED_NUMBER, "corpus"),
            (DECLARED_NUMBER, "declared"),
            (DECLARED_NUMBER, "supplement"),
        }
        for row in rows:
            assert row["coverage_rule"] == coverage_svc.COVERAGE_RULE
            assert row["generated_at"]
            assert row["status_reason"]
        declared = next(
            row for row in rows if row["publication_requested"] == DECLARED_NUMBER
            and row["leg"] == "declared"
        )
        assert declared["leg_state"] == "has_records"
        assert declared["answer_kind"] == "patent_source_lookup"
        assert declared["answer_match_rule"] == DECLARED_MATCH_RULE
        assert int(declared["answer_records"]) == 3

    def test_the_json_export_is_the_report_itself(self, world):
        response = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "json"},
            json={"publications": [CORPUS_DOC]},
        )
        body = json.loads(response.text)
        assert body["rule"] == coverage_svc.COVERAGE_RULE
        assert body["publications"][0]["legs"][0]["leg"] == "corpus"
        # The JSON is the served report's own shape, not a second one.
        served = _client(world.engine).post(
            "/api/v1/patents/coverage", json={"publications": [CORPUS_DOC]}
        ).json()
        assert body["publications"] == served["publications"]

    def test_an_unsupported_export_format_says_what_is_supported(self, world):
        response = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "xlsx"},
            json={"publications": [CORPUS_DOC]},
        )
        assert response.status_code == 422
        assert "json, csv or markdown" in response.json()["detail"]

    def test_the_filename_names_the_scope(self, world):
        single = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "csv"},
            json={"publications": [CORPUS_DOC]},
        )
        assert CORPUS_DOC in single.headers["Content-Disposition"]
        many = _client(world.engine).post(
            "/api/v1/patents/coverage/export",
            params={"format": "csv"},
            json={"publications": [CORPUS_DOC, NEVER_ASKED]},
        )
        assert "2-publications" in many.headers["Content-Disposition"]
