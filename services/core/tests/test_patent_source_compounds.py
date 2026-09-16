"""B-24: what a source *declares* for a publication, and how far that claim reaches.

The product's first promise is "enter a patent, see its compounds". Until this
item that meant "enter a patent SPAgo happens to hold": a family that was never
imported — or imported thinly — showed an empty compound table even when the
compound set is publicly indexed. The patent-led read path closes that gap by
asking a source what it declares for a publication number.

These tests pin what makes the answer usable rather than merely present:

- the match rule is stated and versioned, and a document the body search returns
  that normalizes to a *different* number is a near match: reported and excluded,
  never merged and never dropped;
- a number the source does not know returns `empty` **with the rule**, which is a
  different answer from "the source failed" and from "we never asked";
- a bound being reached is `partial`, so a thin set is not read as the whole truth;
- records without a structure or a numeric value are counted, not silently lost —
  on the live US10508115 document most rows are kinetic constants (`kon`/`k_off`)
  with no `standard_value`, which is exactly that case;
- a declared compound is **not** a corpus occurrence: a lookup writes no
  `compound_mentions` row and does not move the family's counts;
- the potency reading is computed on read, and the patent path claims no evidence
  class, because it never resolves the assayed biological object.

The adapter and the service are driven with the recorded live payloads in
`data/fixtures/open_sources/`; those are transport fixtures, so no number here is
a scientific claim.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from spago_core.adapters.chembl_discovery import (
    MATCH_RULE,
    ChEMBLDiscoveryAdapter,
    DeclaredCompounds,
)
from spago_core.adapters.http import SourceUnavailableError
from spago_core.chemistry import normalize
from spago_core.domain import EvidenceClass
from spago_core.services.compound_store import compound_id_for_inchikey
from spago_core.services.patent_sources import (
    SOURCE_NAME,
    PatentSourceError,
    PatentSourceService,
)

from tests.open_source_stubs import StubSourceClient, load_fixture

PATENT = "US10508115"
PATENT_AS_DECLARED = "US-10508115-B2"
SOURCE_DOCUMENT = "chembl_document_US10508115.json"
SOURCE_ACTIVITIES = "chembl_patent_activities_US10508115.json"


def _adapter(documents=None, activities=None, **kwargs) -> ChEMBLDiscoveryAdapter:
    return ChEMBLDiscoveryAdapter(
        client=StubSourceClient(
            {
                "document.json": documents
                if documents is not None
                else load_fixture(SOURCE_DOCUMENT),
                "activity.json": activities
                if activities is not None
                else load_fixture(SOURCE_ACTIVITIES),
            }
        ),
        **kwargs,
    )


def _service(adapter=None) -> PatentSourceService:
    return PatentSourceService(chembl=adapter or _adapter())


class TestTheMatchRule:
    def test_the_rule_is_versioned_and_travels_with_the_result(self):
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        assert result.match_rule == MATCH_RULE
        assert result.publication_number == PATENT
        # What was asked is kept verbatim, so a wrong number stays visible.
        assert result.requested_number == PATENT_AS_DECLARED

    def test_a_number_that_is_not_a_publication_number_queries_nothing(self):
        client = StubSourceClient({})
        result = ChEMBLDiscoveryAdapter(client=client).declared_compounds("fourteen elephants")
        assert result.status == "failed"
        assert client.calls == []
        assert "not a publication number" in result.warnings[0]

    def test_the_source_declaring_a_different_number_is_a_near_match_not_a_match(self):
        documents = {
            "documents": [
                {
                    "doc_type": "PATENT",
                    "document_chembl_id": "CHEMBL_OTHER",
                    "doi": None,
                    "patent_id": "EP-10508115-A1",
                    "pubmed_id": None,
                    "year": 2019,
                }
            ],
            "page_meta": {"limit": 100, "offset": 0, "total_count": 1},
        }
        client = StubSourceClient(
            {"document.json": documents, "activity.json": load_fixture(SOURCE_ACTIVITIES)}
        )
        result = ChEMBLDiscoveryAdapter(client=client).declared_compounds(PATENT)
        assert result.status == "empty"
        assert result.records == []
        assert [n["patent_id"] for n in result.near_matches] == ["EP-10508115-A1"]
        assert result.near_matches[0]["reason"] == "body_only"
        # The rule is stated when the answer is empty, so "no compounds declared"
        # is readable as a rule-based statement rather than a bare absence.
        assert MATCH_RULE in result.warnings[0]
        # Nothing was queried for a document that is not this publication.
        assert [call[0] for call in client.calls] == ["/chembl/api/data/document.json"]

    def test_the_body_search_is_what_the_source_is_asked(self):
        client = StubSourceClient(
            {"document.json": load_fixture(SOURCE_DOCUMENT), "activity.json": load_fixture(SOURCE_ACTIVITIES)}
        )
        ChEMBLDiscoveryAdapter(client=client).declared_compounds(PATENT_AS_DECLARED)
        _, params = client.calls[0]
        assert params["patent_id__icontains"] == "10508115"
        assert "patent_id" in params["only"]

    def test_the_activity_query_is_scoped_to_the_matched_documents(self):
        client = StubSourceClient(
            {"document.json": load_fixture(SOURCE_DOCUMENT), "activity.json": load_fixture(SOURCE_ACTIVITIES)}
        )
        ChEMBLDiscoveryAdapter(client=client).declared_compounds(PATENT_AS_DECLARED)
        _, params = client.calls[1]
        assert params["document_chembl_id__in"] == "CHEMBL5727449"


class TestWhatIsKept:
    def test_kept_records_carry_their_assay_target_and_document(self):
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        assert result.status == "complete"
        assert result.records_seen == 9
        assert len(result.records) == 3
        record = next(r for r in result.records if r.target_key == "CHEMBL5936")
        assert record.standard_type == "EC50"
        assert record.unit == "nM"
        assert record.target_name == "Toll-like receptor 7"
        # The document is in hand from the search, so the reference is stamped
        # without a second lookup — and it is the normalized number.
        assert record.document_ref == "CHEMBL5727449"
        assert record.document_patent_number == PATENT

    def test_the_source_name_for_the_ligand_is_kept_when_the_payload_has_it(self):
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        names = {r.source_molecule_name for r in result.records}
        # The source names some ligands and not others; absence stays absence
        # rather than becoming a generated name.
        assert names - {None} and names - {None} <= {"RESIQUIMOD", "VESATOLIMOD"}
        assert None in names

    def test_a_source_flagged_duplicate_stays_flagged(self):
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        assert any(r.potential_duplicate for r in result.records)

    def test_records_without_a_numeric_value_are_counted_not_just_dropped(self):
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        # The live document's kinetic rows (kon/k_off) carry no `standard_value`.
        assert result.records_excluded == 6
        assert result.rejection_counts == {"missing_standard_value": 6}
        assert result.records_seen == len(result.records) + result.records_excluded

    def test_this_path_claims_no_evidence_class(self):
        # The patent-led path does not resolve the assayed biological object, so it
        # must not read a binding assay as direct binding on an interaction target.
        result = _adapter().declared_compounds(PATENT_AS_DECLARED)
        assert {r.evidence_class for r in result.records} == {EvidenceClass.UNSPECIFIED}

    def test_a_structure_less_row_is_rejected_with_its_reason(self):
        activities = load_fixture(SOURCE_ACTIVITIES)
        activities["activities"][0]["canonical_smiles"] = None
        result = _adapter(activities=activities).declared_compounds(PATENT)
        assert result.rejection_counts.get("missing_structure") == 1
        assert len(result.records) == 2


class TestFailureAndBounds:
    def test_a_source_failure_is_a_failure_and_not_an_empty_answer(self):
        adapter = _adapter(
            documents=SourceUnavailableError(
                "chembl", "HTTP 503 for document.json", status_code=503
            )
        )
        result = adapter.declared_compounds(PATENT)
        assert result.status == "failed"
        assert result.records == []
        assert "not an empty result" in result.warnings[0]

    def test_a_failed_activity_page_keeps_what_was_read_and_says_partial(self):
        page = load_fixture(SOURCE_ACTIVITIES)
        page["page_meta"] = {"limit": 200, "offset": 0, "total_count": 400}
        calls = {"n": 0}

        def activity_route(call):
            calls["n"] += 1
            if calls["n"] == 1:
                return page
            raise SourceUnavailableError("chembl", "HTTP 503 for activity.json", status_code=503)

        result = _adapter(activities=activity_route).declared_compounds(PATENT)
        assert result.status == "partial"
        assert len(result.records) == 3  # what the first page held is kept
        assert any("503" in w for w in result.warnings)

    def test_the_activity_bound_is_reported_as_partial(self):
        result = _adapter().declared_compounds(PATENT, max_activities=2)
        assert result.status == "partial"
        assert len(result.records) == 2
        assert any("bound of 2" in w for w in result.warnings)
        assert result.bounds["max_activities"] == 2

    def test_more_documents_than_the_bound_says_the_set_is_partial(self):
        documents = {
            "documents": [
                {
                    "doc_type": "PATENT",
                    "document_chembl_id": f"CHEMBL{i}",
                    "doi": None,
                    "patent_id": PATENT_AS_DECLARED,
                    "pubmed_id": None,
                    "year": 2019,
                }
                for i in range(3)
            ],
            "page_meta": {"limit": 100, "offset": 0, "total_count": 3},
        }
        client = StubSourceClient(
            {"document.json": documents, "activity.json": load_fixture(SOURCE_ACTIVITIES)}
        )
        result = ChEMBLDiscoveryAdapter(client=client).declared_compounds(PATENT, max_documents=2)
        assert result.records  # the records the first two documents carry are kept
        assert any("first 2" in w for w in result.warnings)


class TestStoredLookup:
    """What a lookup leaves in the database — and what it must never leave."""

    def test_a_lookup_stores_the_set_and_the_rule_that_produced_it(self, seeded_engine):
        service = _service()
        view = service.lookup(seeded_engine, PATENT_AS_DECLARED)
        assert view["status"] == "complete"
        assert view["match_rule"] == MATCH_RULE
        assert view["row_count"] == 3
        assert view["compound_count"] == 3
        assert view["documents"][0]["patent_id"] == PATENT_AS_DECLARED

        reread = service.read(seeded_engine, PATENT)
        assert reread["status"] == "complete"
        assert reread["row_count"] == 3
        assert reread["retrieved_at"] == view["retrieved_at"]

    def test_a_declared_compound_is_not_a_corpus_occurrence(self, seeded_engine):
        service = _service()
        before = seeded_engine.connect().execute(
            text("SELECT count(*) FROM compound_mentions")
        ).scalar_one()
        view = service.lookup(seeded_engine, PATENT)
        after = seeded_engine.connect().execute(
            text("SELECT count(*) FROM compound_mentions")
        ).scalar_one()
        assert after == before  # no mention, no occurrence, no corpus count moved
        assert view["row_count"] > 0

    def test_a_declared_compound_keeps_the_shared_identity(self, seeded_engine):
        service = _service()
        view = service.lookup(seeded_engine, PATENT)
        row = view["rows"][0]
        assert row["compound_id"] == str(compound_id_for_inchikey(row["inchikey"]))
        stored = seeded_engine.connect().execute(
            text("SELECT count(*) FROM compounds WHERE inchikey = :k"),
            {"k": row["inchikey"]},
        ).scalar_one()
        assert stored == 1

    def test_a_second_lookup_replaces_rather_than_duplicates(self, seeded_engine):
        service = _service()
        first = service.lookup(seeded_engine, PATENT)
        second = service.lookup(seeded_engine, PATENT)
        assert second["row_count"] == first["row_count"]
        total = seeded_engine.connect().execute(
            text("SELECT count(*) FROM patent_source_compounds")
        ).scalar_one()
        assert total == second["row_count"]

    def test_a_failed_lookup_is_stored_as_failed_and_not_as_not_queried(self, seeded_engine):
        service = _service()
        service.lookup(seeded_engine, PATENT)  # a set the user already has
        failing = _service(
            _adapter(
                documents=SourceUnavailableError(
                    "chembl", "HTTP 503 for document.json", status_code=503
                )
            )
        )
        view = failing.lookup(seeded_engine, PATENT)
        assert view["status"] == "failed"
        assert view["warnings"]
        # The set from the last good attempt is still there, with its own time.
        assert view["row_count"] == 3
        assert view["rows_retrieved_at"] != view["retrieved_at"]
        # A publication nobody asked about is a third state.
        assert failing.read(seeded_engine, "US9999999999")["status"] == "not_queried"

    def test_a_number_the_source_does_not_know_reads_empty_with_the_rule(self, seeded_engine):
        documents = {"documents": [], "page_meta": {"limit": 100, "offset": 0, "total_count": 0}}
        service = _service(ChEMBLDiscoveryAdapter(client=StubSourceClient({"document.json": documents})))
        view = service.lookup(seeded_engine, "US9999999999")
        assert view["status"] == "empty"
        assert view["row_count"] == 0
        assert MATCH_RULE in view["warnings"][0]
        assert view["near_matches"] == []

    def test_the_reading_is_paged_and_bounded(self, seeded_engine):
        service = _service()
        service.lookup(seeded_engine, PATENT)
        page = service.read(seeded_engine, PATENT, limit=2)
        assert page["row_count"] == 3
        assert len(page["rows"]) == 2
        assert page["limit"] == 2
        rest = service.read(seeded_engine, PATENT, offset=2, limit=2)
        assert len(rest["rows"]) == 1
        # Both pages carry the rule, so a row never travels without it.
        assert rest["match_rule"] == MATCH_RULE

    def test_a_stored_row_carries_its_provenance_and_source(self, seeded_engine):
        service = _service()
        service.lookup(seeded_engine, PATENT)
        row = service.read(seeded_engine, PATENT)["rows"][0]
        assert row["dataset_version"].startswith("chembl:")
        assert row["provenance_state"] == "database_curated"
        # The declared reference is the source's, not something resolved later.
        assert row["document_patent_number"] == PATENT
        assert row["source_record_id"]
        assert row["source_url"].startswith("https://www.ebi.ac.uk/chembl/activity/")

    def test_the_potency_reading_is_computed_on_read(self, seeded_engine):
        service = _service()
        service.lookup(seeded_engine, PATENT)
        view = service.read(seeded_engine, PATENT)
        by_type = {row["standard_type"]: row for row in view["rows"]}
        assert by_type["EC50"]["activity_class"] in {"active", "weak"}
        assert by_type["EC50"]["potency_label"].startswith("EC50 ")
        assert view["reference_policy_version"]
        assert view["reference_threshold_nM"] > 0
        # Three declared records, every one a potency read under the same policy.
        assert view["activity_class_counts"]["not_applicable"] == 0
        assert sum(view["activity_class_counts"].values()) == view["row_count"]

    def test_a_publication_that_cannot_be_normalized_is_refused(self, seeded_engine):
        with pytest.raises(PatentSourceError, match="publication number"):
            _service().lookup(seeded_engine, "not a patent")


class TestTheAdapterContract:
    def test_the_result_type_carries_the_source_envelope(self):
        result = _adapter().declared_compounds(PATENT)
        assert isinstance(result, DeclaredCompounds)
        assert result.envelope.source_name == SOURCE_NAME
        assert result.envelope.synthetic is False
        assert result.envelope.retrieved_at is not None

    def test_a_declared_structure_normalizes_like_any_other(self):
        result = _adapter().declared_compounds(PATENT)
        record = result.records[0]
        # The declared structure goes through the same RDKit path as an import.
        assert normalize(record.raw_smiles).inchikey


class TestTheApi:
    """The served surface: what the patent view reads and downloads."""

    @pytest.fixture(autouse=True)
    def _fresh_declared_state(self, seeded_engine):
        """Start each API test with no stored lookup, whatever ran before it.

        The module shares one scratch database, so a lookup stored by an earlier
        test would otherwise decide whether a publication reads `not_queried`.
        """
        with seeded_engine.begin() as conn:
            conn.execute(text("DELETE FROM patent_source_compounds"))
            conn.execute(text("DELETE FROM patent_source_lookups"))

    def _client(self, app_client):
        from spago_core.api.routes import _patent_source_service

        app_client.app.dependency_overrides[_patent_source_service] = lambda: _service()
        return app_client

    def test_before_a_lookup_the_answer_is_not_queried(self, app_client):
        response = app_client.get(f"/api/v1/patents/{PATENT}/source-compounds")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "not_queried"
        assert body["rows"] == []
        assert "nothing was asked" in body["not_queried_reason"]
        assert body["match_rule"] == MATCH_RULE

    def test_the_lookup_endpoint_stores_and_serves_the_declared_set(self, app_client):
        client = self._client(app_client)
        response = client.post(f"/api/v1/patents/{PATENT_AS_DECLARED}/source-compounds")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["row_count"] == 3
        assert body["compound_count"] == 3
        assert body["match_rule"] == MATCH_RULE
        assert body["match_rule_text"]
        assert body["reference_policy_version"]
        assert body["documents"][0]["patent_id"] == PATENT_AS_DECLARED

        again = client.get(f"/api/v1/patents/{PATENT}/source-compounds")
        assert again.json()["row_count"] == 3

    def test_a_row_is_labelled_as_a_declaration_not_a_corpus_occurrence(self, app_client):
        client = self._client(app_client)
        client.post(f"/api/v1/patents/{PATENT}/source-compounds")
        row = client.get(f"/api/v1/patents/{PATENT}/source-compounds").json()["rows"][0]
        assert row["document_patent_number"] == PATENT
        assert row["provenance_state"] == "database_curated"
        assert row["activity_class"] in {"active", "weak", "unknown", "not_applicable"}
        assert row["potency_label"]

    def test_the_reading_is_paged_served_side(self, app_client):
        client = self._client(app_client)
        client.post(f"/api/v1/patents/{PATENT}/source-compounds")
        body = client.get(
            f"/api/v1/patents/{PATENT}/source-compounds", params={"offset": 1, "limit": 1}
        ).json()
        assert body["offset"] == 1 and body["limit"] == 1
        assert len(body["rows"]) == 1 and body["row_count"] == 3

    def test_the_export_carries_the_kind_the_rule_and_the_policy(self, app_client):
        client = self._client(app_client)
        client.post(f"/api/v1/patents/{PATENT}/source-compounds")
        response = client.get(f"/api/v1/patents/{PATENT}/source-compounds/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "source_declared" in response.headers["x-spago-source-set"]
        assert f"-{PATENT}-" in response.headers["content-disposition"]
        text = response.text
        assert "record_kind" in text.splitlines()[0]
        assert "source_declared_compound" in text
        assert MATCH_RULE in text
        assert "reference_policy_version" in text.splitlines()[0]

    def test_the_sdf_export_holds_the_declared_structures(self, app_client):
        client = self._client(app_client)
        client.post(f"/api/v1/patents/{PATENT}/source-compounds")
        response = client.get(
            f"/api/v1/patents/{PATENT}/source-compounds/export", params={"format": "sdf"}
        )
        assert response.status_code == 200
        assert response.text.count("$$$$") == 3
        assert ">  <record_kind>" in response.text
        assert ">  <match_rule>" in response.text

    def test_an_export_without_a_lookup_says_so_instead_of_writing_an_empty_file(
        self, app_client
    ):
        response = app_client.get(f"/api/v1/patents/US9999999999/source-compounds/export")
        assert response.status_code == 422
        assert "run the lookup first" in response.json()["detail"]

    def test_a_publication_that_is_not_a_number_is_refused_with_a_reason(self, app_client):
        client = self._client(app_client)
        response = client.post("/api/v1/patents/thirteen%20elephants/source-compounds")
        assert response.status_code == 422
        assert "publication number" in response.json()["detail"]
