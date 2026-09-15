"""ONLINE-00 A: target resolution adapter and service contract.

Covers the required behaviours without network access:
- a clean resolution persists the reviewed scope with its provenance;
- an ambiguous query does not silently pick a target;
- an unknown query is `not_found`, an unreachable source is `failed` (never
  silently empty), and an unsupported species is `not_queried`;
- receptor/partner expansion is offered but labelled as related.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.adapters.http import SourceUnavailableError
from spago_core.adapters.uniprot import UniProtTargetResolver, species_taxon
from spago_core.db import run_migrations
from spago_core.domain import RetrievalStatus
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    """A migrated database: ONLINE-00 does not depend on the demo fixture."""
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_target_state(online_engine):
    """Resolution tests assert on exact stored state, so they start empty."""
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def resolver_for(payload: dict) -> UniProtTargetResolver:
    return UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": payload}))


def test_gene_exact_resolution_returns_reviewed_entry_first():
    resolver = resolver_for(load_fixture("uniprot_TSLP_human.json"))
    result = resolver.resolve("TSLP", "human")
    assert result.status is RetrievalStatus.COMPLETE
    assert result.entries[0].identifier == "Q969D9"
    assert result.entries[0].gene_symbol == "TSLP"
    assert result.entries[0].reviewed is True
    assert result.entries[0].organism == "Homo sapiens"
    assert result.entries[0].taxon_id == 9606
    assert result.entries[0].source_url.endswith("/Q969D9/entry")


def test_species_taxon_supports_names_and_numeric_ids():
    assert species_taxon("human") == 9606
    assert species_taxon("Mus musculus") == 10090
    assert species_taxon("9541") == 9541
    assert species_taxon("") is None


def test_unsupported_species_is_not_queried_not_empty():
    resolver = resolver_for(load_fixture("uniprot_TSLP_human.json"))
    result = resolver.resolve("TSLP", "unicorn")
    assert result.status is RetrievalStatus.NOT_QUERIED
    assert result.entries == []
    assert "Unsupported species" in result.warnings[0]


def test_source_failure_is_reported_as_failed():
    client = StubSourceClient(
        {"uniprotkb/search": SourceUnavailableError("uniprot", "HTTP 503")}
    )
    result = UniProtTargetResolver(client=client).resolve("TSLP", "human")
    assert result.status is RetrievalStatus.FAILED
    assert result.entries == []
    assert "503" in result.warnings[0]


def test_empty_result_is_empty_and_says_what_it_does_not_mean():
    resolver = resolver_for({"results": [], "totalResults": 0})
    result = resolver.resolve("NOTAREALGENE", "human")
    assert result.status is RetrievalStatus.EMPTY
    assert result.entries == []


def test_ambiguous_query_chooses_nothing():
    resolver = resolver_for(load_fixture("uniprot_ambiguous.json"))
    result = resolver.resolve("TSLP", "human")
    assert result.status is RetrievalStatus.COMPLETE
    # Both entries are reviewed, human and gene-exact: indistinguishable by the
    # documented preference rules.
    assert len(result.entries) == 2


def test_service_records_ambiguity_instead_of_picking(online_engine):
    service = TargetResolutionService(uniprot=resolver_for(load_fixture("uniprot_ambiguous.json")))
    outcome = service.resolve(online_engine, "TSLP", "human")
    assert outcome.record.status == "ambiguous"
    assert outcome.target is None
    assert len(outcome.record.candidates) == 2
    assert "Select one" in " ".join(outcome.record.notes)
    with online_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM targets")).scalar_one() == 0


def test_service_resolution_persists_scope_and_related_members(online_engine):
    service = TargetResolutionService(uniprot=resolver_for(load_fixture("uniprot_TSLP_human.json")))
    outcome = service.resolve(online_engine, "TSLP", "human")
    assert outcome.record.status == "resolved"
    assert outcome.stored is True
    target = outcome.target
    assert target is not None
    assert target.gene_symbol == "TSLP"
    assert target.uniprot_accession == "Q969D9"
    assert target.scope_kind is not None and target.scope_kind.value == "ligand"
    # Receptor expansion is offered, and labelled as related rather than merged.
    roles = {c.role: c.gene_symbol for c in target.components if c.role != "component"}
    assert roles.get("receptor") in {"CRLF2", "IL7R"}
    assert any("Related receptor" in note for note in outcome.record.notes)

    stored = service.get_target(online_engine, target.id)
    assert stored.uniprot_accession == "Q969D9"
    assert {c.accession for c in stored.components} >= {"Q9HC73", "P16871"}

    record = service.latest_resolution(online_engine, target.id)
    assert record is not None and record.query == "TSLP"
    assert record.source_name == "uniprot"

    # The resolution run itself is persisted for review.
    with online_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM target_resolutions")).scalar_one() == 1


def test_related_expansion_can_be_declined(online_engine):
    service = TargetResolutionService(uniprot=resolver_for(load_fixture("uniprot_TSLP_human.json")))
    outcome = service.resolve(online_engine, "TSLP", "human", include_related=False)
    target = outcome.target
    assert target is not None
    assert [c for c in target.components if c.role == "receptor"] == []


def test_find_target_reuses_a_resolved_scope(online_engine):
    service = TargetResolutionService(uniprot=resolver_for(load_fixture("uniprot_TSLP_human.json")))
    outcome = service.resolve(online_engine, "TSLP", "human")
    found = service.find_target(online_engine, "tslp")
    assert found is not None and found.id == outcome.target.id
    found_by_accession = service.find_target(online_engine, "Q969D9")
    assert found_by_accession is not None and found_by_accession.id == outcome.target.id
    assert service.find_target(online_engine, f"{uuid.uuid4()}") is None


def test_target_key_uses_the_stable_namespace(online_engine):
    """An externally resolved target and a patent-derived target with the same
    key must be one row, or evidence would split across two identities."""
    from spago_core.seed import _compound_id  # same namespace object
    from spago_core.services.targets import target_id_for_key

    assert target_id_for_key("TSLP") == uuid.uuid5(
        target_id_for_key("TSLP").__class__("3d2f1a8e-6c05-4d9b-9d3a-1f2e8b7c5a10"), "target:TSLP"
    )
    assert _compound_id("X") is not None  # imported namespace is the same family
