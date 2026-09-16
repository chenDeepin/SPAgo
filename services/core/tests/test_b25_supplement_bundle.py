"""B-25: a set of literature rows arrives as one artifact, and a person admits it.

The scientific point, and the reason this is not a paste box: a bundle states *who
produced its rows and what was searched*, and that decides what the rows are. A file a
person wrote is the person's own statement; a file an agent or a script produced is a
**proposal**. A proposal is stored and readable, and it is outside the investigation —
no verdict count, no candidate, no export — until a human confirms it as a separate,
recorded act (AGENTS.md §10/§12). So this file pins, end to end:

- that the envelope is required: no producer, no search, or an unsupported version is
  refused as a whole, and a bare list of rows is not a bundle;
- that a bundle declaring another protein than its endpoint's target is refused rather
  than stored under the wrong target;
- that a refused *row* is answered for with its reasons while the rest of the file
  imports, and that what the file refused stays in the stored report;
- that the alias table maps `ic50_nm` deterministically and refuses a record that
  states two contradictory endpoints instead of choosing one;
- that `human`/`agent`/`external` produce `user_curated`/`llm_inferred`/
  `machine_extracted` rows from identical input;
- that an agent's rows create no candidate row, so the verdict, the candidate list and
  the export do not see them, while the verdict *reports* them as unreviewed;
- that confirmation is one act that flips provenance and admits the live compounds,
  that it is idempotent, and that a withdrawn row stays withdrawn through it;
- that provenance never downgrades: a person's confirmed row re-posted by an agent
  stays `user_curated` and stays in the investigation.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.chemistry.activities import DEFAULT_THRESHOLD_NM
from spago_core.db import run_migrations
from spago_core.main import create_app
from spago_core.services.discovery import TargetDiscoveryService
from spago_core.services.reference import policy_from_settings, reference_verdict
from spago_core.services.supplements import (
    BundleRefused,
    confirm_supplement_import,
    import_supplement_bundle,
    import_supplements,
    list_supplement_imports,
    map_bundle_record,
)
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture

SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
OTHER_SMALL_MOLECULE = "CC(=O)Oc1ccccc1C(=O)O"
TSLP_ACCESSION = "Q969D9"


class _Settings:
    def __init__(self, threshold_nm: float = DEFAULT_THRESHOLD_NM, min_compounds: int = 10):
        self.activity_threshold_nm = threshold_nm
        self.activity_min_compounds = min_compounds


def policy(threshold_nm: float = DEFAULT_THRESHOLD_NM, min_compounds: int = 10, **kwargs):
    return policy_from_settings(
        _Settings(threshold_nm, min_compounds), **kwargs  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_online_tables(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


@pytest.fixture()
def resolved_target(online_engine):
    resolver = UniProtTargetResolver(
        client=StubSourceClient({"uniprotkb/search": _uniprot_route})
    )
    outcome = TargetResolutionService(uniprot=resolver).resolve(online_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


def _app(online_engine):
    app = create_app()
    app.state.engine = online_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    app.state.discovery_service = TargetDiscoveryService(
        chembl=None,
        bindingdb=None,
        pubchem=PubChemAdapter(client=StubSourceClient({})),
    )
    return app


@pytest.fixture()
def client(online_engine):
    return TestClient(_app(online_engine))


def _count(engine, table: str, where: str = "", params: dict | None = None) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} {where}"), params or {}
            ).scalar_one()
        )


def bundle(**overrides) -> dict:
    """A well-formed agent bundle; the row shapes below are what a producer sends."""
    payload = {
        "bundle_version": 1,
        "produced_by": "literature agent (claude-sonnet, 2026-09-16)",
        "produced_by_kind": "agent",
        "searched": "PubMed 'TSLP inhibitor IC50' + Google Patents 'TSLP antagonist'",
        "generated_at": "2026-09-16T09:00:00Z",
        "records": [],
    }
    payload.update(overrides)
    if not payload.get("records"):
        payload["records"] = [
            {
                "name": "compound 7",
                "note": "Table 2 of the paper; IC50 against human TSLP",
                "smiles": SMALL_MOLECULE,
                "ic50_nm": 4.0,
            }
        ]
    return payload


def post_bundle(client: TestClient, target_id: uuid.UUID, payload: dict):
    return client.post(f"/api/v1/targets/{target_id}/supplements/bundle", json=payload)


class TestMapping:
    """The alias table is deterministic, and what it cannot resolve it refuses."""

    def test_a_number_is_read_by_the_table_not_guessed(self):
        mapped = map_bundle_record({"name": "7", "note": "n", "ic50_nm": 4.0})
        assert mapped["value"] == 4.0
        assert mapped["activity_type"] == "IC50"
        assert mapped["unit"] == "nM"

    def test_a_reference_is_carried_into_the_note(self):
        mapped = map_bundle_record(
            {"name": "7", "note": "Table 2", "url": "https://doi.org/10.1/x", "ki_nm": 3}
        )
        assert mapped["note"] == "Table 2\nreference: https://doi.org/10.1/x"
        assert "url" not in mapped

    def test_a_reference_alone_becomes_the_note(self):
        """The URL *is* the producer's statement about where the row comes from.

        Nothing is generated: the note is either what the record said, plus the
        reference it carried, or the reference alone. A record with neither is refused
        by the row validator ("note: Field required") — SPAgo does not write the note
        for a producer (AGENTS.md §12).
        """
        mapped = map_bundle_record({"name": "7", "reference": "https://doi.org/10.1/x"})
        assert mapped["note"] == "reference: https://doi.org/10.1/x"

    def test_two_endpoints_for_one_number_are_refused_not_chosen(self):
        with pytest.raises(Exception) as excinfo:
            map_bundle_record(
                {"name": "7", "note": "n", "value": 4.0, "ic50_nm": 30.0}
            )
        assert "not a choice this importer makes" in str(excinfo.value)

    def test_a_contradicting_endpoint_is_refused(self):
        with pytest.raises(Exception) as excinfo:
            map_bundle_record(
                {"name": "7", "note": "n", "activity_type": "Ki", "ic50_nm": 4.0}
            )
        assert "one row is one endpoint" in str(excinfo.value)

    def test_a_non_numeric_potency_is_refused(self):
        with pytest.raises(Exception) as excinfo:
            map_bundle_record({"name": "7", "note": "n", "ic50_nm": "4.0"})
        assert "expected a number" in str(excinfo.value)

    def test_an_unknown_key_is_left_for_the_row_validator_to_name(self):
        """The refusal must name the key, so a producer can fix the file."""
        mapped = map_bundle_record(
            {"name": "7", "note": "n", "smiles": SMALL_MOLECULE, "potency": "high"}
        )
        assert mapped["potency"] == "high"

    def test_a_stated_inchikey_is_checked_against_the_structure(self, online_engine, resolved_target):
        """A row whose stated identity and drawn structure differ is refused."""
        imported = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(
                bundle(
                    records=[
                        {
                            "name": "compound 7",
                            "note": "Table 2",
                            "smiles": SMALL_MOLECULE,
                            "ic50_nm": 4.0,
                            "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
                        }
                    ]
                )
            ),
        )
        assert imported.report.measurements == 0
        assert imported.report.rejected == 1
        assert any(
            "inchikey_mismatch" in reason for reason in imported.report.outcomes[0].reasons
        )
        assert _count(online_engine, "measurements") == 0

    def test_a_correct_stated_inchikey_is_accepted(self, online_engine, resolved_target):
        from spago_core.chemistry import normalize

        key = normalize(SMALL_MOLECULE).inchikey
        imported = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(
                bundle(
                    records=[
                        {
                            "name": "compound 7",
                            "note": "Table 2",
                            "smiles": SMALL_MOLECULE,
                            "ic50_nm": 4.0,
                            "inchikey": key.lower(),
                        }
                    ]
                )
            ),
        )
        assert imported.report.measurements == 1


class TestEnvelope:
    """The bundle is an artifact: its provenance is required, or it is not a bundle."""

    def test_a_bare_list_of_rows_is_not_a_bundle(self, client, resolved_target):
        response = client.post(
            f"/api/v1/targets/{resolved_target.id}/supplements/bundle",
            json=[{"name": "7", "note": "n"}],
        )
        assert response.status_code == 422

    def test_an_unsupported_version_is_refused(self, client, resolved_target):
        response = post_bundle(
            client, resolved_target.id, bundle(bundle_version=2)
        )
        assert response.status_code == 422
        assert "not supported" in response.json()["detail"][0]["msg"]

    def test_an_empty_records_list_is_refused(self, client, resolved_target):
        payload = bundle()
        payload["records"] = []
        response = post_bundle(client, resolved_target.id, payload)
        assert response.status_code == 422
        assert "at least one record" in response.json()["detail"][0]["msg"]

    def test_an_object_without_a_name_or_note_is_refused_per_row(self, client, resolved_target):
        """An incomplete row is a refusal, not an empty default (AGENTS.md §12)."""
        response = post_bundle(client, resolved_target.id, bundle(records=[{"x": 1}]))
        assert response.status_code == 201, response.text
        report = response.json()["report"]
        assert report["received"] == 1
        assert report["rejected"] == 1
        assert report["measurements"] == 0

    def test_a_record_that_is_not_an_object_is_refused(self, client, resolved_target):
        response = post_bundle(client, resolved_target.id, bundle(records=["just a string"]))
        assert response.status_code == 422

    def test_a_bundle_for_another_protein_is_refused(self, online_engine, resolved_target):
        """The realistic mistake: target A's file pasted into target B's dialog."""
        with pytest.raises(BundleRefused) as excinfo:
            import_supplement_bundle(
                online_engine,
                resolved_target.id,
                _bundle_model(bundle(uniprot="P99999")),
            )
        assert "P99999" in str(excinfo.value)
        assert _count(online_engine, "measurements") == 0

    def test_a_bundle_for_this_protein_is_accepted(self, online_engine, resolved_target):
        result = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(bundle(uniprot=TSLP_ACCESSION)),
        )
        assert result.report.measurements == 1


def _bundle_model(payload: dict):
    from spago_core.domain import SupplementBundle

    return SupplementBundle.model_validate(payload)


class TestProvenance:
    """Who produced the rows decides what they are — from identical input."""

    def test_a_human_bundle_is_the_persons_own_statement(self, online_engine, resolved_target):
        result = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle(produced_by_kind="human"))
        )
        assert result.awaiting_review is False
        assert result.report.provenance_state.value == "user_curated"
        assert _count(online_engine, "target_candidates", "WHERE target_id = :t", {"t": resolved_target.id}) == 1
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds == 1
        assert verdict.unreviewed_supplements == 0

    def test_an_external_bundle_is_a_machine_extracted_proposal(self, online_engine, resolved_target):
        result = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(bundle(produced_by_kind="external", produced_by="run_import.py")),
        )
        assert result.awaiting_review is True
        assert result.report.provenance_state.value == "machine_extracted"

    def test_an_agents_rows_are_outside_the_investigation(self, online_engine, resolved_target):
        """Stored, readable, and in no verdict count, candidate list or export."""
        result = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        assert result.report.measurements == 1
        with online_engine.connect() as conn:
            provenance = conn.execute(
                text(
                    "SELECT provenance_state FROM measurements m JOIN assays a ON a.id = m.assay_id "
                    "WHERE a.target_id = :t"
                ),
                {"t": resolved_target.id},
            ).scalar_one()
        assert provenance == "llm_inferred"
        assert _count(online_engine, "target_candidates") == 0

        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds == 0
        assert verdict.measurements == 0
        assert verdict.qualifies is False
        assert verdict.unreviewed_supplements == 1
        assert "not part of this investigation until a person reviews" in verdict.reason

    def test_a_reviewed_row_supersedes_a_structureless_proposal(self, online_engine, resolved_target):
        """A person's row with a structure replaces a structure-less claim of the same row.

        The remark and the measurement share one content-hashed row id (note, name and
        endpoint are the same), so one claim stays one row rather than the paper being
        counted twice (ONLINE-07, defect D3).
        """
        claim = {
            "name": "example 12",
            "note": "IC50 3 nM; structure not published in the paper",
            "activity_type": "IC50",
            "value": 3.0,
            "unit": "nM",
        }
        first = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(bundle(produced_by_kind="human", records=[claim])),
        )
        assert first.report.remarks == 1
        assert _count(online_engine, "target_supplement_remarks") == 1
        second = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(
                bundle(
                    produced_by_kind="human",
                    records=[dict(claim, smiles=SMALL_MOLECULE)],
                )
            ),
        )
        assert second.report.measurements == 1
        assert _count(online_engine, "target_supplement_remarks") == 0
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds == 1
        assert verdict.supplement_remarks == 0


class TestConfirmation:
    """One recorded act turns proposals into the target's own rows."""

    def test_confirmation_admits_the_live_rows(self, online_engine, resolved_target):
        imported = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(
                bundle(
                    records=[
                        {
                            "name": "compound 7",
                            "note": "Table 2",
                            "smiles": SMALL_MOLECULE,
                            "ic50_nm": 4.0,
                        },
                        {
                            "name": "compound 9",
                            "note": "Table 3, no structure published",
                            "activity_type": "IC50",
                            "value": 300.0,
                            "unit": "nM",
                        },
                    ]
                )
            ),
        )
        before = reference_verdict(online_engine, resolved_target, policy())
        assert before.unreviewed_supplements == 2
        assert before.compounds == 0

        confirmation = confirm_supplement_import(
            online_engine, resolved_target.id, imported.report.id, confirmed_by="ada@example.org"
        )
        assert confirmation.already_confirmed is False
        assert confirmation.rows == 2
        assert confirmation.candidates_created == 1
        assert _count(online_engine, "target_candidates") == 1

        after = reference_verdict(online_engine, resolved_target, policy())
        assert after.compounds == 1
        assert after.compounds_active == 1
        assert after.unreviewed_supplements == 0
        # The remark is the person's now, and the wording of the verdict is the
        # ordinary one: no unreviewed-proposal sentence is left over.
        assert after.supplement_remarks == 1
        assert "not part of this investigation" not in after.reason

    def test_confirmation_is_idempotent(self, online_engine, resolved_target):
        imported = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        first = confirm_supplement_import(online_engine, resolved_target.id, imported.report.id)
        second = confirm_supplement_import(online_engine, resolved_target.id, imported.report.id)
        assert first.already_confirmed is False
        assert second.already_confirmed is True
        assert second.confirmed_at == first.confirmed_at
        assert _count(online_engine, "target_candidates") == 1

    def test_a_row_withdrawn_before_confirmation_stays_withdrawn(
        self, online_engine, resolved_target
    ):
        imported = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        record_id = imported.report.stored[0].record_id
        # The reviewer takes the row back instead of admitting it (ONLINE-08 path).
        import spago_core.services.supplements as supplements_svc

        supplements_svc.withdraw_supplement(
            online_engine, resolved_target.id, record_id, "structure does not match the paper"
        )
        confirmation = confirm_supplement_import(
            online_engine, resolved_target.id, imported.report.id
        )
        assert confirmation.candidates_created == 0
        assert _count(online_engine, "target_candidates") == 0
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds == 0
        assert verdict.withdrawn_supplements == 1
        assert verdict.unreviewed_supplements == 0

    def test_confirmation_cannot_be_recorded_for_another_target(
        self, online_engine, resolved_target
    ):
        from spago_core.services import NotFoundError

        imported = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        with pytest.raises(NotFoundError):
            confirm_supplement_import(online_engine, uuid.uuid4(), imported.report.id)

    def test_provenance_never_downgrades(self, online_engine, resolved_target):
        """A person's own row, re-posted by an agent, stays the person's."""
        human = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle(produced_by_kind="human"))
        )
        agent_again = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        assert agent_again.report.updated_rows == 1
        with online_engine.connect() as conn:
            state = conn.execute(
                text(
                    "SELECT provenance_state FROM measurements m JOIN assays a ON a.id = m.assay_id "
                    "WHERE a.target_id = :t"
                ),
                {"t": resolved_target.id},
            ).scalar_one()
        assert state == "user_curated"
        # And the compound stays in the investigation: a later proposal cannot take a
        # candidate away by re-posting the same row.
        assert _count(online_engine, "target_candidates") == 1
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds == 1
        assert verdict.unreviewed_supplements == 0
        assert human.report.record_ids == agent_again.report.record_ids


class TestReport:
    """What arrived, what was refused, and what is still waiting for a person."""

    def test_a_refused_row_is_in_the_report_with_its_reasons(self, online_engine, resolved_target):
        imported = import_supplement_bundle(
            online_engine,
            resolved_target.id,
            _bundle_model(
                bundle(
                    records=[
                        {"name": "7", "note": "Table 2", "smiles": SMALL_MOLECULE, "ic50_nm": 4.0},
                        {"name": "11", "note": "Table 4", "ic50_nm": 5.0, "value": 500.0},
                        {"name": "13", "note": "Table 5", "potency": "potent"},
                    ]
                )
            ),
        )
        report = imported.report
        assert report.received == 3
        assert report.measurements == 1
        assert report.rejected == 2
        assert [outcome.status for outcome in report.outcomes] == [
            "measurement",
            "rejected",
            "rejected",
        ]
        assert any(
            "not a choice this importer makes" in reason
            for reason in report.outcomes[1].reasons
        )
        assert any("potency" in reason for reason in report.outcomes[2].reasons)
        # The refusal is stored, not just returned: it is part of the run.
        stored = list_supplement_imports(online_engine, resolved_target.id)
        assert stored[0].rejected == 2
        assert len(stored[0].outcomes) == 3

    def test_a_repeat_import_is_marked_as_a_repeat(self, online_engine, resolved_target):
        first = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        assert first.report.repeated_of is None
        second = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        assert second.report.repeated_of == first.report.id
        # And it is one claim, not two: the row updated instead of being duplicated.
        assert second.report.updated_rows == 1
        assert _count(online_engine, "measurements") == 1
        # The fact survives the read-back: the stored list is what a reader opens later,
        # so a repeat must not look like new work there either.
        listed = {
            report.id: report
            for report in list_supplement_imports(online_engine, resolved_target.id)
        }
        assert listed[second.report.id].repeated_of == first.report.id
        assert listed[first.report.id].repeated_of is None

    def test_a_reposted_remark_is_counted_as_an_update(self, online_engine, resolved_target):
        """A row that already exists is an update, whatever kind of row it is.

        The measurement path has always said so; a structure-less row is stored by a
        different helper, and a run that updated one must not report it as new — a
        reader deciding whether an import changed anything reads exactly this count.
        """
        payload = bundle(
            records=[
                {
                    "name": "compound 7",
                    "note": "Table 2 of the paper; IC50 against human TSLP",
                    "smiles": SMALL_MOLECULE,
                    "ic50_nm": 4.0,
                },
                {
                    "name": "example 12",
                    "note": "Table 3; IC50 against human TSLP, structure not published",
                    "ic50_nm": 45.0,
                },
            ]
        )
        first = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(payload)
        )
        assert first.report.updated_rows == 0
        assert (first.report.measurements, first.report.remarks) == (1, 1)

        second = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(payload)
        )
        # Both rows already existed, so both are updates: one measurement, one remark.
        assert second.report.updated_rows == 2
        # And still one row of each: an update is not a duplicate (§22).
        assert _count(online_engine, "target_supplement_remarks") == 1
        assert _count(online_engine, "measurements") == 1

    def test_the_report_shows_rows_as_they_stand_now(self, online_engine, resolved_target):
        imported = import_supplement_bundle(
            online_engine, resolved_target.id, _bundle_model(bundle())
        )
        record_id = imported.report.stored[0].record_id
        import spago_core.services.supplements as supplements_svc

        supplements_svc.withdraw_supplement(
            online_engine, resolved_target.id, record_id, "wrong stereochemistry"
        )
        report = list_supplement_imports(online_engine, resolved_target.id)[0]
        row = next(state for state in report.stored if state.record_id == record_id)
        assert row.live is False
        assert row.retracted_reason == "wrong stereochemistry"
        # The file's own answer stays readable beside the person's act.
        assert report.measurements == 1


class TestHttpContract:
    """The route is the workflow: import, read back, confirm."""

    @pytest.fixture()
    def target_id(self, online_engine) -> uuid.UUID:
        with TestClient(_app(online_engine)) as client:
            resolved = client.post(
                "/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"}
            )
            assert resolved.status_code == 200, resolved.text
            return uuid.UUID(resolved.json()["target_id"])

    def test_import_read_back_confirm(self, client, target_id):
        imported = post_bundle(client, target_id, bundle())
        assert imported.status_code == 201, imported.text
        body = imported.json()["report"]
        import_id = body["id"]
        assert body["produced_by_kind"] == "agent"
        assert body["awaiting_review"] is True
        assert body["stored"][0]["activity_class"] == "active"
        assert body["stored"][0]["compound_id"]

        listed = client.get(f"/api/v1/targets/{target_id}/supplement-imports")
        assert listed.status_code == 200, listed.text
        assert [report["id"] for report in listed.json()] == [import_id]
        assert listed.json()[0]["awaiting_review"] is True

        # Outside the investigation until confirmed: the candidate list sees nothing.
        candidates = client.get(f"/api/v1/targets/{target_id}/candidates")
        assert candidates.status_code == 200, candidates.text
        assert candidates.json()["total"] == 0
        assert candidates.json()["items"] == []

        confirmed = client.post(
            f"/api/v1/targets/{target_id}/supplement-imports/{import_id}/confirm"
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["already_confirmed"] is False
        assert confirmed.json()["candidates_created"] == 1
        assert confirmed.json()["confirmed_by"]

        listed = client.get(f"/api/v1/targets/{target_id}/supplement-imports").json()
        assert listed[0]["awaiting_review"] is False
        assert listed[0]["confirmed_at"]

        candidates = client.get(f"/api/v1/targets/{target_id}/candidates").json()
        assert candidates["total"] == 1
        assert len(candidates["items"]) == 1

    def test_the_verdict_reports_unreviewed_rows(self, client, target_id):
        post_bundle(client, target_id, bundle())
        verdict = client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert verdict["unreviewed_supplements"] == 1
        assert verdict["compounds"] == 0
        assert "not part of this investigation" in verdict["reason"]
        # The gate is stated as unmet, so the strip can offer the two ways a person can
        # supply rows themselves without wording this as a negative finding.
        assert verdict["qualifies"] is False

    def test_the_export_cannot_even_be_asked_for_an_unreviewed_row(self, client, target_id):
        """The strongest form of "outside the investigation": the scope refuses it.

        Export is scoped by the candidate list, so a proposal is not merely omitted from
        a file — asking for it is an error with a reason, which is what stops an
        unreviewed row from ever reaching a shared artifact (AGENTS.md §10/§12).
        """
        imported = post_bundle(client, target_id, bundle()).json()["report"]
        compound_id = imported["stored"][0]["compound_id"]
        body = {
            "target_id": str(target_id),
            "compound_ids": [compound_id],
            "format": "csv",
        }
        response = client.post("/api/v1/export", json=body)
        assert response.status_code == 422, response.text
        assert "not candidates of this target" in response.json()["detail"]

        # After a person confirms the import, the same request produces the file, and
        # the file states the provenance the rows now have.
        client.post(
            f"/api/v1/targets/{target_id}/supplement-imports/{imported['id']}/confirm"
        )
        response = client.post("/api/v1/export", json=body)
        assert response.status_code == 200, response.text
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == 1
        assert rows[0]["provenance_states"] == "user_curated"

    def test_an_unknown_import_is_a_404(self, client, target_id):
        response = client.post(
            f"/api/v1/targets/{target_id}/supplement-imports/{uuid.uuid4()}/confirm"
        )
        assert response.status_code == 404

    def test_the_one_row_path_still_creates_candidates_directly(self, client, target_id):
        """B-25 must not change what a hand-typed row means."""
        response = client.post(
            f"/api/v1/targets/{target_id}/supplements",
            json={
                "rows": [
                    {
                        "name": "compound 7",
                        "note": "Table 2",
                        "smiles": SMALL_MOLECULE,
                        "activity_type": "IC50",
                        "value": 4.0,
                        "unit": "nM",
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["measurements"] == 1
        verdict = client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert verdict["compounds"] == 1
        assert verdict["unreviewed_supplements"] == 0
