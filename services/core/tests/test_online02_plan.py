"""ONLINE-02: natural language becomes a validated, reviewable plan.

The sealed request set (`data/fixtures/planner_requests.json`) is the evaluation
artifact: every entry states the request, the expected outcome and why. Cases
cover the three supported intents, ambiguity, missing coverage, malformed and
adversarial plans, and the boundaries the plan must not cross.

The bar these tests hold:

- an unsupported or under-specified request produces a clarification, never an
  invented target, SMILES, threshold, assay condition or patent number;
- a posted plan is re-validated, so a client cannot widen its own scope;
- the model's output is untrusted: unknown operations, extra fields and
  out-of-range values are refused;
- nothing in a request can turn into an instruction that changes policy;
- a plan that resolves to no data reports that honestly.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.main import create_app
from spago_core.services import plan_execution, planner


@pytest.fixture(scope="session")
def planner_requests() -> list[dict]:
    path = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "planner_requests.json"
    return json.loads(path.read_text())["requests"]


@pytest.fixture(scope="module")
def online_engine(seeded_engine):
    return seeded_engine


@pytest.fixture(scope="module")
def realistic_publication_number(online_engine) -> str:
    """A document whose identifier really is publication-number shaped.

    The demo fixture uses synthetic identifiers (DEMO-PATENT-A) that the
    identifier validator must NOT accept, so the open-patent path is exercised
    against a document with a realistic number. It lives in its own family so
    this fixture cannot change another test module's version expectations.
    """
    number = "EP1234567A1"
    with online_engine.begin() as conn:
        family_id = uuid.uuid4()
        conn.execute(
            text(
                """
                INSERT INTO patent_families (id, family_key, title, source_name,
                                             dataset_version, retrieved_at)
                VALUES (:fid, 'PLANNER-FAMILY', 'Planner fixture family', 'test',
                        'test:planner', now())
                ON CONFLICT (family_key) DO NOTHING
                """
            ),
            {"fid": family_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO patent_documents (id, family_id, publication_number, title,
                                              source_name, dataset_version, retrieved_at)
                VALUES (:id, :fid, :number, 'Planner fixture document', 'test',
                        'test:planner', now())
                ON CONFLICT (publication_number) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "fid": family_id, "number": number},
        )
    return number


@pytest.fixture()
def client(online_engine):
    app = create_app()
    app.state.engine = online_engine
    return TestClient(app)


# --- sealed request set -------------------------------------------------------------


def test_sealed_set_covers_the_required_intents(planner_requests):
    kinds = {case["expect"] for case in planner_requests}
    assert len(planner_requests) >= 20
    assert {
        "open_patent",
        "target_discovery",
        "clarification",
        "rejected",
        # Intents that need conversation context or a named structure are
        # covered by the LLM-proposal cases below, not by the offline planner.
        "llm_only",
    } <= kinds


@pytest.mark.parametrize(
    "case", ["open_patent", "target_discovery", "clarification", "rejected", "llm_only"]
)
def test_supported_and_unsupported_requests_behave_as_sealed(case, planner_requests):
    cases = [c for c in planner_requests if c["expect"] == case]
    assert cases
    for entry in cases:
        plan = planner.offline_plan(entry["request"], entry.get("context") or {})
        if case == "open_patent":
            assert [s["op"] for s in plan.steps] == ["open_patent"], entry["request"]
            assert plan.steps[0]["publication_number"] == entry["publication_number"]
        elif case == "target_discovery":
            assert planner.Operation.TARGET_DISCOVERY.value in [s["op"] for s in plan.steps], entry["request"]
            assert plan.steps[0]["target_query"] == entry["target_query"]
        elif case == "clarification":
            assert plan.steps == [], entry["request"]
            assert plan.clarification_required is True
            assert plan.unresolved
        elif case == "rejected":
            # A request that names an entity but also an unsupported constraint
            # executes the supported part and reports the rest as unresolved.
            assert plan.unresolved, entry["request"]
            assert plan.clarification_required is True
        elif case == "llm_only":
            # These intents need conversation context or a named structure, so the
            # offline planner must decline rather than guess...
            assert plan.steps == [], entry["request"]
            assert plan.clarification_required is True
            # ...while the same proposal, once supplied, must validate.
            proposal = dict(entry["proposal"])
            proposal["steps"] = [
                {
                    **step,
                    **(
                        {"query_compound_id": str(uuid.uuid4())}
                        if step.get("query_compound_id") == "SELECTED"
                        else {}
                    ),
                    **({"family_id": str(uuid.uuid4())} if step.get("family_id") == "OPEN_FAMILY" else {}),
                    **(
                        {"document_id": str(uuid.uuid4())}
                        if step.get("document_id") == "OPEN_DOCUMENT"
                        else {}
                    ),
                }
                for step in proposal["steps"]
            ]
            validated = planner.plan_from_proposal(entry["request"], proposal)
            assert [s["op"] for s in validated.steps] == [
                s["op"] for s in entry["proposal"]["steps"]
            ], entry["request"]


def test_no_sealed_request_ever_invents_an_argument(planner_requests):
    """No request may produce a target, SMILES or patent number that the request
    did not literally contain."""
    for entry in planner_requests:
        plan = planner.offline_plan(entry["request"], entry.get("context") or {})
        text_upper = entry["request"].upper()
        for step in plan.steps:
            if step["op"] == "open_patent":
                assert step["publication_number"] in text_upper
            if step["op"] == "target_discovery":
                # The requested entity may be an alias, a system label or an
                # accession that the reviewed catalog maps to the gene symbol, so
                # the check is provenance from the request, not byte equality.
                query = step["target_query"]
                assert _entity_came_from_request(query, entry["request"]), entry["request"]


def _entity_came_from_request(gene_symbol: str, request: str) -> bool:
    """True when the request literally names this entity or one of its reviewed
    identifiers (gene synonym, accession or system label)."""
    from spago_core.services.target_scope import try_load_catalog

    catalog, _problem = try_load_catalog()
    upper = request.upper()
    # The planner strips hyphens inside protein names ("IL-6" is the gene IL6),
    # so the same normalisation applies when checking provenance.
    squashed = upper.replace("-", "")
    for system in catalog.all_systems():
        for member in system.members:
            if member.gene_symbol != gene_symbol:
                continue
            candidates = {member.gene_symbol, member.accession, system.system_key}
            for token in candidates:
                if not token:
                    continue
                if token.upper() in upper or token.upper().replace("-", "") in squashed:
                    return True
    return False


# --- schema and allowlist -----------------------------------------------------------


class TestPlanValidation:
    def test_unknown_operation_is_refused(self):
        with pytest.raises(planner.UnsupportedRequest) as exc:
            planner.validate_step({"op": "run_sql", "sql": "select * from compounds"})
        assert "Unsupported operation" in exc.value.reason

    def test_extra_fields_are_refused_not_ignored(self):
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_step(
                {"op": "open_patent", "publication_number": "US10000000B2", "url": "http://evil"}
            )

    def test_publication_number_shape_is_enforced(self):
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_step({"op": "open_patent", "publication_number": "all potent patents"})

    def test_limit_is_bounded(self):
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_step(
                {"op": "open_patent", "publication_number": "US10000000B2", "limit": 100000}
            )

    def test_structure_search_requires_a_named_structure(self):
        with pytest.raises(planner.UnsupportedRequest) as exc:
            planner.validate_step({"op": "structure_search", "mode": "substructure"})
        assert "will not guess a structure" in exc.value.reason

    def test_similarity_requires_an_explicit_threshold(self):
        with pytest.raises(planner.UnsupportedRequest) as exc:
            planner.validate_step(
                {"op": "structure_search", "mode": "similarity", "query_smiles": "CCO"}
            )
        assert "explicit threshold" in exc.value.reason

    def test_threshold_is_bounded(self):
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_step(
                {
                    "op": "structure_search",
                    "mode": "similarity",
                    "query_smiles": "CCO",
                    "threshold": 0.05,
                }
            )

    def test_summary_requires_a_scope(self):
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_step({"op": "summarize_family"})

    def test_plan_step_count_is_bounded(self):
        plan = {
            "query": "many",
            "producer": "offline",
            "steps": [
                {"op": "open_patent", "publication_number": f"US1000000{i}B2"} for i in range(9)
            ],
        }
        with pytest.raises(planner.UnsupportedRequest):
            planner.validate_plan(plan)

    def test_llm_proposal_with_bad_steps_keeps_only_valid_ones(self):
        plan = planner.plan_from_proposal(
            "open the patent and also do something impossible",
            {
                "steps": [
                    {"op": "open_patent", "publication_number": "US10000000B2"},
                    {"op": "delete_everything"},
                ],
                "unresolved": [],
                "note": "proposed",
            },
        )
        assert [s["op"] for s in plan.steps] == ["open_patent"]
        assert plan.clarification_required is True
        assert any("delete_everything" in problem for problem in plan.unresolved)

    def test_llm_proposal_with_only_invalid_steps_requests_clarification(self):
        plan = planner.plan_from_proposal(
            "do something impossible",
            {"steps": [{"op": "drop_table"}], "unresolved": []},
        )
        assert plan.steps == []
        assert plan.clarification_required is True


# --- execution -----------------------------------------------------------------------


class TestPlanExecution:
    def test_open_patent_executes_through_the_corpus_service(
        self, online_engine, realistic_publication_number
    ):
        number = realistic_publication_number
        plan = planner.offline_plan(number)
        result = plan_execution.execute_plan(online_engine, plan)
        assert result.steps[0].status == "ok"
        assert result.steps[0].data["publication_number"] == number
        assert result.steps[0].data["family_key"]

    def test_unknown_publication_number_is_not_found_not_empty(self, online_engine):
        plan = planner.offline_plan("US99999999B2")
        result = plan_execution.execute_plan(online_engine, plan)
        assert result.steps[0].status == "not_found"
        assert "not found" in result.steps[0].detail.lower()

    def test_summarize_family_uses_the_scoped_service(self, online_engine):
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        plan = planner.SearchPlan(
            query="summarize this family",
            producer="offline",
            steps=[{"op": "summarize_family", "family_id": str(family_id)}],
        )
        result = plan_execution.execute_plan(online_engine, plan)
        assert result.steps[0].status == "ok"
        assert result.steps[0].data["scope"] == "family"
        assert result.steps[0].data["provenance_state"] == "machine_extracted"

    def test_structure_search_runs_on_the_server(self, online_engine):
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
            compound_id = conn.execute(
                text(
                    "SELECT c.id FROM compounds c JOIN compound_mentions m ON m.compound_id = c.id "
                    "JOIN patent_documents d ON d.id = m.document_id WHERE d.family_id = :f LIMIT 1"
                ),
                {"f": family_id},
            ).scalar_one()
        plan = planner.SearchPlan(
            query="find structures similar to this selected compound",
            producer="offline",
            steps=[
                {
                    "op": "structure_search",
                    "mode": "similarity",
                    "query_compound_id": str(compound_id),
                    "family_id": str(family_id),
                    "threshold": 0.4,
                }
            ],
        )
        result = plan_execution.execute_plan(online_engine, plan)
        assert result.steps[0].status == "ok"
        assert result.steps[0].data["threshold"] == 0.4
        assert result.steps[0].data["total"] >= 1
        # The structure was resolved server-side from the stored compound.
        assert result.steps[0].data["query_inchikey"]

    def test_execution_revalidates_a_posted_plan(self, online_engine):
        """A hand-written plan cannot introduce what the allowlist forbids."""
        with pytest.raises(planner.UnsupportedRequest):
            plan_execution.execute_plan(
                online_engine,
                {
                    "query": "hand written",
                    "producer": "llm",
                    "steps": [{"op": "run_sql", "sql": "SELECT 1"}],
                },
            )

    def test_compare_evidence_reports_counts_without_merging_classes(self, online_engine):
        with online_engine.begin() as conn:
            target_id = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, source_name, dataset_version,
                                         retrieved_at, uniprot_accession, target_type)
                    VALUES (:id, 'PLAN-TGT', 'Plan target', 'uniprot', 'uniprot:2026-09-15',
                            now(), 'P99999', 'single_protein')
                    """
                ),
                {"id": target_id},
            )
            compound = conn.execute(text("SELECT id FROM compounds LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, evidence_class, modality,
                                                   dataset_version, retrieved_at)
                    VALUES (:id, :tid, :cid, 'chembl', 'plan-1', 'measured_direct_binding',
                            'small_molecule', 'chembl:2026-09-15', now())
                    """
                ),
                {"id": uuid.uuid4(), "tid": target_id, "cid": compound},
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
                {"id": assay, "key": f"PLAN-ASSAY-{assay}", "tid": target_id},
            )
            for index, evidence_class in enumerate(
                ("measured_direct_binding", "functional_effect", "functional_effect")
            ):
                conn.execute(
                    text(
                        """
                        INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                                  unit, relation, source_record_id, source_name,
                                                  extraction_method, provenance_state,
                                                  dataset_version, retrieved_at, evidence_class)
                        VALUES (:id, :cid, :aid, 'IC50', :value, 'nM', '=', :rid, 'chembl',
                                'chembl_webclient_discovery', 'database_curated',
                                'chembl:2026-09-15', now(), :cls)
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "cid": compound,
                        "aid": assay,
                        "value": 100.0 + index,
                        "rid": f"plan-act-{index}",
                        "cls": evidence_class,
                    },
                )
        plan = planner.SearchPlan(
            query="compare direct and indirect evidence",
            producer="llm",
            steps=[
                {"op": "compare_evidence_classes", "target_id": str(target_id)},
            ],
        )
        result = plan_execution.execute_plan(online_engine, plan)
        step = result.steps[0]
        assert step.status == "ok"
        groups = {g["evidence_class"]: g["measurements"] for g in step.data["groups"]}
        assert groups == {"measured_direct_binding": 1, "functional_effect": 2}
        assert "deliberately not merged" in step.data["note"]

    def test_unresolved_target_for_comparison_is_not_found(self, online_engine):
        plan = planner.SearchPlan(
            query="compare evidence",
            producer="offline",
            steps=[{"op": "compare_evidence_classes", "target_query": "NOTRESOLVED"}],
        )
        result = plan_execution.execute_plan(online_engine, plan)
        assert result.steps[0].status == "not_found"
        assert "run a target discovery" in result.steps[0].detail


# --- HTTP surface --------------------------------------------------------------------


class TestPlanApi:
    def test_plan_then_execute_round_trip(self, client, realistic_publication_number):
        number = realistic_publication_number
        planned = client.post("/api/v1/ai/plan", json={"query": number})
        assert planned.status_code == 200, planned.text
        body = planned.json()
        assert body["producer"] == "offline"
        assert body["steps"][0]["op"] == "open_patent"
        assert body["steps"][0]["expensive"] is False

        executed = client.post(
            "/api/v1/ai/plan/execute",
            json={
                "plan": {
                    "query": body["query"],
                    "producer": body["producer"],
                    "steps": [
                        {
                            "op": "open_patent",
                            "publication_number": body["steps"][0]["parameters"]["publication_number"],
                        }
                    ],
                }
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["steps"][0]["status"] == "ok"

    def test_free_text_without_llm_is_a_clarification(self, client):
        response = client.post(
            "/api/v1/ai/plan", json={"query": "find something potent for an unspecified target"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["steps"] == []
        assert body["clarification_required"] is True
        assert "not guessed at" in body["note"]

    def test_llm_opt_in_without_configuration_is_503(self, client):
        response = client.post(
            "/api/v1/ai/plan",
            json={"query": "find potent inhibitors of something", "use_llm": True},
        )
        assert response.status_code == 503
        assert "still work" in response.json()["detail"]

    def test_context_is_summarised_not_dumped(self, client, online_engine):
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        response = client.post(
            "/api/v1/ai/plan", json={"query": "TSLP", "family_id": str(family_id)}
        )
        assert response.status_code == 200
        assert "Current context" in response.json()["note"]

    def test_execute_refuses_a_foreign_operation(self, client):
        response = client.post(
            "/api/v1/ai/plan/execute",
            json={
                "plan": {
                    "query": "attack",
                    "producer": "llm",
                    "steps": [{"op": "http_request", "url": "http://example.invalid"}],
                }
            },
        )
        assert response.status_code == 422
        assert "Unsupported operation" in response.json()["detail"]

    def test_execute_refuses_the_operators_project_id(self, client):
        """Guessing another project's id must fail closed, not return data."""
        response = client.post(
            "/api/v1/ai/plan/execute",
            json={
                "plan": {
                    "query": "other project",
                    "producer": "llm",
                    "steps": [
                        {
                            "op": "summarize_family",
                            "family_id": str(uuid.uuid4()),
                        }
                    ],
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["steps"][0]["status"] == "failed"

    def test_empty_query_is_rejected_by_the_schema(self, client):
        assert client.post("/api/v1/ai/plan", json={"query": ""}).status_code == 422
