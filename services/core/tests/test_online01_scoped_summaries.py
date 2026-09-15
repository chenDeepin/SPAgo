"""ONLINE-01: scoped summaries with one real (or recorded) endpoint.

The contract under test:

- a document summary covers only that document and says so;
- a target summary carries the per-source coverage and never converts a
  missing record into a scientific conclusion;
- the family path is unchanged;
- the cache is keyed by scope, so one scope's analysis is never served for
  another;
- citations are validated against the supplied scope, and an out-of-scope
  citation is rejected rather than stored;
- every documented failure state maps to its own HTTP status.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.main import create_app
from spago_core.services import ai


@pytest.fixture(scope="module")
def online_engine(seeded_engine):
    """Migrations applied and the demo fixture loaded, on a known-empty state.

    `seeded_engine` resets first, so this module does not depend on which other
    PG module ran before it.
    """
    return seeded_engine


@pytest.fixture()
def scope_ids(online_engine):
    with online_engine.connect() as conn:
        family = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        docs = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT id FROM patent_documents WHERE family_id = :f ORDER BY publication_number"
                ),
                {"f": family},
            ).all()
        ]
    return family, docs


@pytest.fixture()
def client(online_engine):
    app = create_app()
    app.state.engine = online_engine
    return TestClient(app)


class TestDocumentScope:
    def test_document_summary_is_labelled_and_scoped(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        result = ai.summarize_document(online_engine, docs[0])
        assert result["scope"] == "document"
        assert result["input_snapshot"]["summary_scope"] == "document"
        assert result["input_snapshot"]["document"]["id"] == str(docs[0])
        # A document summary carries no family-level fact list, so it cannot be
        # mistaken for (or quote) a family analysis.
        assert "family" not in result["input_snapshot"]
        assert result["input_snapshot"]["document"]["family_key"]
        assert "claims were not assessed" in result["text"]
        assert {c["kind"] for c in result["citations"]} <= {"document", "measurement", "evidence"}

    def test_sibling_documents_are_absent_from_the_facts(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        result = ai.summarize_document(online_engine, docs[0])
        blob = json.dumps(result["input_snapshot"])
        for other in docs[1:]:
            assert str(other) not in blob

    def test_document_and_family_summaries_are_distinct_analyses(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        family = ai.summarize_family(online_engine, family_id)
        document = ai.summarize_document(online_engine, docs[0])
        assert family["analysis_id"] != document["analysis_id"]
        assert family["scope"] == "family"
        assert document["scope"] == "document"

    def test_unknown_document_is_not_found(self, online_engine):
        from spago_core.services import NotFoundError

        with pytest.raises(NotFoundError):
            ai.summarize_document(online_engine, uuid.uuid4())


class TestCacheIsScoped:
    def test_repeating_a_scope_reuses_the_cached_row(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        first = ai.summarize_document(online_engine, docs[0])
        again = ai.summarize_document(online_engine, docs[0])
        assert again["cached"] is True
        assert again["analysis_id"] == first["analysis_id"]

    def test_the_other_scope_is_not_served_from_the_cache(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        family = ai.summarize_family(online_engine, family_id)
        document = ai.summarize_document(online_engine, docs[0])
        assert document["analysis_id"] != family["analysis_id"]
        # Both analyses are persisted separately, with their own scope label.
        with online_engine.connect() as conn:
            kinds = {
                row[0]
                for row in conn.execute(
                    text("SELECT analysis_kind FROM ai_analyses WHERE id IN (:a, :b)"),
                    {"a": family["analysis_id"], "b": document["analysis_id"]},
                ).all()
            }
        assert kinds == {"family_summary", "document_summary"}

    def test_a_prompt_version_change_invalidates_the_cached_row(
        self, online_engine, scope_ids, monkeypatch
    ):
        """A changed instruction must not be served an old answer.

        The prompt version is part of the analysis cache key; this pins that, so
        a future prompt edit that forgets to bump the version cannot silently
        keep showing summaries written under the previous instructions.
        """
        _family_id, docs = scope_ids
        first = ai.summarize_document(online_engine, docs[0])
        monkeypatch.setitem(ai.PROMPT_VERSION_BY_SCOPE, "document", "document-summary-next")
        second = ai.summarize_document(online_engine, docs[0])
        assert second["cached"] is False
        assert second["analysis_id"] != first["analysis_id"]
        # The stored row records the version that produced it, so an old answer
        # cannot be read as if the new instruction had produced it.
        with online_engine.connect() as conn:
            versions = {
                row[0]
                for row in conn.execute(
                    text("SELECT prompt_version FROM ai_analyses WHERE id IN (:a, :b)"),
                    {"a": first["analysis_id"], "b": second["analysis_id"]},
                ).all()
            }
        assert versions == {ai.DOCUMENT_PROMPT_VERSION, "document-summary-next"}


class TestTargetScope:
    @pytest.fixture(scope="class")
    @classmethod
    def target_id(cls, online_engine):
        """A minimal target investigation, built without network access.

        Class-scoped because `targets.target_key` is unique: a per-test insert
        would collide, and reusing one investigation is what the tests describe.
        """
        with online_engine.begin() as conn:
            tid = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, organism, source_name,
                                         dataset_version, retrieved_at, uniprot_accession,
                                         gene_symbol, target_type, scope_kind, components)
                    VALUES (:id, 'TESTTGT', 'Test target', 'Homo sapiens', 'uniprot',
                            'uniprot:2026-09-15', now(), 'P00001', 'TESTTGT',
                            'single_protein', 'ligand', CAST(:components AS jsonb))
                    """
                ),
                {
                    "id": tid,
                    "components": json.dumps(
                        [
                            {
                                "accession": "P00002",
                                "name": "Partner",
                                "gene_symbol": "PARTNER",
                                "role": "receptor",
                                "organism": "Homo sapiens",
                            },
                            {
                                "accession": "CPX-1",
                                "name": "ComplexPortal CPX-1",
                                "role": "complex_membership",
                            },
                        ]
                    ),
                },
            )
            for source, status, seen, kept in (
                ("chembl", "complete", 10, 8),
                ("bindingdb", "failed", 0, 0),
                ("pubchem", "not_queried", 0, 0),
            ):
                conn.execute(
                    text(
                        """
                        INSERT INTO source_retrievals (id, target_id, source_name, query, status,
                                                       records_seen, records_kept, retrieved_at)
                        VALUES (:id, :tid, :source, '{}'::jsonb, :status, :seen, :kept, now())
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": tid,
                        "source": source,
                        "status": status,
                        "seen": seen,
                        "kept": kept,
                    },
                )
            # One candidate compound with a measurement against the target.
            compound = conn.execute(text("SELECT id FROM compounds LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, evidence_class, modality,
                                                   dataset_version, retrieved_at)
                    VALUES (:id, :tid, :cid, 'chembl', 'rec-1', 'measured_direct_binding',
                            'small_molecule', 'chembl:2026-09-15', now())
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
                    VALUES (:id, :key, :tid, 'B', 'chembl', 'chembl:2026-09-15', now())
                    """
                ),
                {"id": assay, "key": f"TARGET-SCOPE-{assay}", "tid": tid},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                              unit, relation, source_record_id, source_name,
                                              extraction_method, provenance_state,
                                              dataset_version, retrieved_at, evidence_class)
                    VALUES (:id, :cid, :aid, 'Kd', 12.0, 'nM', '=', 'act-1', 'chembl',
                            'chembl_webclient_discovery', 'database_curated',
                            'chembl:2026-09-15', now(), 'measured_direct_binding')
                    """
                ),
                {"id": uuid.uuid4(), "cid": compound, "aid": assay},
            )
        return tid

    def test_target_summary_reports_each_source_status(self, online_engine, target_id):
        result = ai.summarize_target(online_engine, target_id)
        assert result["scope"] == "target"
        assert "chembl: complete" in result["text"]
        assert "bindingdb: failed" in result["text"]
        assert "pubchem: not_queried" in result["text"]
        # The coverage statement is explicit, so a thin result cannot read as
        # "no inhibitors exist".
        assert "never demonstrate that no inhibitors exist" in result["text"]
        assert result["input_snapshot"]["coverage_note"]

    def test_target_summary_keeps_related_members_and_annotations_apart(self, online_engine, target_id):
        snapshot = ai.summarize_target(online_engine, target_id)["input_snapshot"]
        members = snapshot["target"]["components"]
        assert [m["gene_symbol"] for m in members] == ["PARTNER"]
        annotations = snapshot["target"]["structural_annotations"]
        assert any(a["role"] == "complex_membership" for a in annotations)

    def test_evidence_class_counts_cover_all_measurements(self, online_engine, target_id):
        snapshot = ai.summarize_target(online_engine, target_id)["input_snapshot"]
        assert snapshot["measurement_total"] == 1
        assert snapshot["evidence_class_counts"] == {"measured_direct_binding": 1}

    def test_candidate_totals_survive_bounding(self, online_engine, target_id):
        snapshot = ai.summarize_target(online_engine, target_id)["input_snapshot"]
        # The denominator stays in the snapshot even if items are dropped, so a
        # bounded list is never reported as complete.
        assert snapshot["candidate_total"] == 1
        assert len(snapshot["candidates"]) == 1

    def test_root_ref_is_citable_in_every_scope(self, online_engine, target_id, scope_ids):
        """The aggregate-citation rule must be satisfiable in every scope.

        The prompt tells the model to cite the input's root ref for scope-level
        coverage and totals statements. If a scope's allowed set ever lost its
        root, that instruction would be a trap: such a paragraph would have no
        legal citation and the whole summary would be refused. That
        contradiction was the dominant refusal class in
        `benchmarks/online01-llm-eval-2026-09-15.md`; this pins the fix.
        """
        family_id, docs = scope_ids
        snapshots = {
            "family": ai.summarize_family(online_engine, family_id)["input_snapshot"],
            "document": ai.summarize_document(online_engine, docs[0])["input_snapshot"],
            "target": ai.summarize_target(online_engine, target_id)["input_snapshot"],
        }

        class FakeResult:
            finish_reason = "stop"
            tool_calls = False
            usage = None
            model = "recorded"

            def __init__(self, content):
                self.content = content

        for scope, snapshot in snapshots.items():
            root = snapshot[scope]["ref"]
            assert root in ai.allowed_refs(snapshot), (scope, root)
            # Citing the root for an aggregate statement validates, so the
            # instruction is achievable rather than aspirational.
            content = json.dumps(
                {"paragraphs": [{"text": "Totals.", "fact_refs": [root]}], "limitations": []}
            )
            ai._validate_llm_output(FakeResult(content), snapshot)

    def test_unknown_target_is_not_found(self, online_engine):
        from spago_core.services import NotFoundError

        with pytest.raises(NotFoundError):
            ai.summarize_target(online_engine, uuid.uuid4())

    def test_every_retrieval_is_citable_by_its_own_ref(self, online_engine, target_id):
        """Per-source status is quoted from the retrieval, not the target root.

        Run 4 of the evaluation (`benchmarks/online01-llm-eval-2026-09-15.md`)
        found the model describing per-source status and version against a ref
        the snapshot did not advertise, and the summaries were refused for it.
        The retrievals now carry their own `source:<name>` ref; this test pins
        that both places the model reads the retrieval from advertise the same
        legal citation, and that the validator accepts all of them.
        """
        snapshot = ai.summarize_target(online_engine, target_id)["input_snapshot"]
        allowed = ai.allowed_refs(snapshot)

        source_refs = [s["ref"] for s in snapshot["sources"]]
        assert source_refs == [
            f"source:{name}" for name in ("bindingdb", "chembl", "pubchem")
        ]
        # The coverage projection is where the version string appears, so it must
        # not require a different ref from the same retrieval.
        coverage_refs = [c["ref"] for c in snapshot["coverage"]]
        assert set(coverage_refs) <= set(source_refs)
        assert set(source_refs) <= allowed

        class FakeResult:
            finish_reason = "stop"
            tool_calls = False
            usage = None
            model = "recorded"

            def __init__(self, content):
                self.content = content

        # A paragraph made only of per-source statements validates, which is the
        # behaviour the fix exists to allow.
        content = json.dumps(
            {"paragraphs": [{"text": "Per-source status.", "fact_refs": source_refs}], "limitations": []}
        )
        output = ai._validate_llm_output(FakeResult(content), snapshot)
        assert output.paragraphs[0].fact_refs == source_refs

        citations = ai._build_citations(output, snapshot)
        kinds = {c["fact_ref"]: c["kind"] for c in citations}
        assert kinds["source:chembl"] == "source"
        # The UI focuses a coverage chip by source name, so the citation has to
        # carry it; a citation mapped without one is not a usable destination.
        chembl = next(c for c in citations if c["fact_ref"] == "source:chembl")
        assert chembl["source_name"] == "chembl"
        assert "complete" in chembl["label"]
        assert "8 kept" in chembl["label"]

        # Widening the allowed set to any `source:` string would accept a
        # retrieval the snapshot never contained, so the rejection still holds.
        invented = json.dumps(
            {
                "paragraphs": [
                    {"text": "Invented source.", "fact_refs": ["source:not_queried_here"]}
                ],
                "limitations": [],
            }
        )
        with pytest.raises(ai.LLMUpstreamError):
            ai._validate_llm_output(FakeResult(invented), snapshot)


class TestCitationValidation:
    def test_out_of_scope_citations_are_rejected(self, online_engine, scope_ids):
        family_id, docs = scope_ids
        snapshot = ai.collect_facts(online_engine, "document", docs[0])
        snapshot, _ = ai.finalize_snapshot(snapshot)
        allowed = ai.allowed_refs(snapshot)
        assert f"document:{docs[0]}" in allowed
        # A sibling document's ref is not in the allowed set for this scope.
        for other in docs[1:]:
            assert f"document:{other}" not in allowed

        class FakeResult:
            finish_reason = "stop"
            tool_calls = False
            usage = None
            model = "recorded"

            def __init__(self, content):
                self.content = content

        foreign = json.dumps(
            {
                "paragraphs": [
                    {"text": "Foreign fact.", "fact_refs": [f"document:{docs[1]}"]}
                ],
                "limitations": [],
            }
        )
        with pytest.raises(ai.LLMUpstreamError):
            ai._validate_llm_output(FakeResult(foreign), snapshot)

    def test_in_scope_citations_are_accepted(self, online_engine, scope_ids):
        _family_id, docs = scope_ids
        snapshot = ai.collect_facts(online_engine, "document", docs[0])
        snapshot, _ = ai.finalize_snapshot(snapshot)

        class FakeResult:
            finish_reason = "stop"
            tool_calls = False
            usage = None
            model = "recorded"
            content = json.dumps(
                {
                    "paragraphs": [
                        {"text": "In-scope fact.", "fact_refs": [f"document:{docs[0]}"]}
                    ],
                    "limitations": ["Bounded input."],
                }
            )

        output = ai._validate_llm_output(FakeResult(), snapshot)
        assert output.paragraphs[0].fact_refs == [f"document:{docs[0]}"]


class TestScopedSummaryApi:
    def test_document_route(self, client, scope_ids):
        _family_id, docs = scope_ids
        response = client.post(f"/api/v1/documents/{docs[0]}/summary", json={"mode": "offline"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scope"] == "document"
        assert body["mode"] == "offline"
        assert body["provenance_state"] == "machine_extracted"

    def test_document_route_unknown_id_is_404(self, client):
        response = client.post(f"/api/v1/documents/{uuid.uuid4()}/summary", json={"mode": "offline"})
        assert response.status_code == 404

    def test_target_route_unknown_id_is_404(self, client):
        response = client.post(f"/api/v1/targets/{uuid.uuid4()}/summary", json={"mode": "offline"})
        assert response.status_code == 404

    def test_family_route_still_works_without_a_body(self, client, scope_ids):
        family_id, _docs = scope_ids
        response = client.post(f"/api/v1/families/{family_id}/summary")
        assert response.status_code == 200
        assert response.json()["scope"] == "family"

    def test_llm_mode_without_configuration_is_503(self, client, scope_ids):
        _family_id, docs = scope_ids
        response = client.post(f"/api/v1/documents/{docs[0]}/summary", json={"mode": "llm"})
        assert response.status_code == 503
        assert "configured" in response.json()["detail"].lower()

    def test_invalid_mode_is_rejected_by_the_schema(self, client, scope_ids):
        _family_id, docs = scope_ids
        response = client.post(
            f"/api/v1/documents/{docs[0]}/summary", json={"mode": "interpretive"}
        )
        assert response.status_code == 422
