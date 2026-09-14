"""Adapter contract tests (AGENTS.md §8: source isolation + envelope)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from spago_core.adapters import ChemicalPatentSource, SureChemblFixtureAdapter


def test_adapter_satisfies_contract(fixture_dir: Path):
    adapter = SureChemblFixtureAdapter(fixture_dir)
    assert isinstance(adapter, ChemicalPatentSource)
    assert adapter.source_name == "surechembl_simplified_fixture"


def test_envelope_is_complete(fixture_dir: Path):
    result = SureChemblFixtureAdapter(fixture_dir).load()
    env = result.envelope
    assert env.source_name == "surechembl_simplified_fixture"
    assert env.dataset_version == "demo-fixture-v1"
    assert env.synthetic is True
    assert isinstance(env.retrieved_at, datetime)
    assert env.retrieved_at.tzinfo is not None


def test_normalized_records_shape(fixture_dir: Path):
    result = SureChemblFixtureAdapter(fixture_dir).load()
    assert len(result.families) == 1
    assert result.families[0].family_key == "DEMO-FAMILY-1"
    assert {d.publication_number for d in result.documents} == {
        "DEMO-PATENT-A", "DEMO-PATENT-B", "DEMO-PATENT-C",
    }
    assert len(result.mentions) == 13
    assert len(result.evidence) == 13


def test_mentions_keep_patent_local_labels(fixture_dir: Path):
    result = SureChemblFixtureAdapter(fixture_dir).load()
    labels = {(m.document_id, m.patent_label) for m in result.mentions}
    # Cross-document same-molecule cases keep their local labels.
    assert ("DEMO-PATENT-A", "Example 01") in labels
    assert ("DEMO-PATENT-B", "Compound 12") in labels
    assert ("DEMO-PATENT-B", "Compound C-1") in labels


def test_evidence_carries_provenance_and_missing_locators(fixture_dir: Path):
    result = SureChemblFixtureAdapter(fixture_dir).load()
    by_local_id = {e.compound_local_id: e for e in result.evidence}

    claim_ev = by_local_id["SC-DEMO-0010"]
    assert claim_ev.source_type.value == "claim"
    assert claim_ev.section is None and claim_ev.page is None
    assert claim_ev.source_url is None  # fixture never fabricates links
    assert claim_ev.provenance_state.value == "machine_extracted"
    assert claim_ev.extraction_method == "surechembl_simplified_fixture_import"

    abstract_ev = by_local_id["SC-DEMO-0004"]
    assert abstract_ev.source_type.value == "abstract"
    assert abstract_ev.page is None
    assert abstract_ev.confidence == 0.5

    paged_ev = by_local_id["SC-DEMO-0001"]
    assert paged_ev.source_type.value == "description"
    assert paged_ev.section == "Example 1"
    assert paged_ev.page == 4
    assert paged_ev.confidence == 1.0


def test_missing_smiles_is_an_issue_not_a_mention(fixture_dir: Path, tmp_path: Path):
    result = SureChemblFixtureAdapter(fixture_dir).load()
    assert all(m.raw_smiles.strip() for m in result.mentions)

    # Build a one-file fixture with an empty SMILES row and verify issue handling.
    import duckdb

    records = tmp_path / "rec.parquet"
    duckdb.sql(
        """
        COPY (SELECT * FROM (VALUES
            ('DEMO-X', 'SC-T-1', 'Example 1', CAST(NULL AS VARCHAR), 'description', NULL, NULL)
        ) AS t(document_id, compound_id, patent_label, smiles, source_field, section, page))
        TO '""" + str(records) + """' (FORMAT PARQUET)
        """
    )
    patents = tmp_path / "pat.parquet"
    duckdb.sql(
        """
        COPY (SELECT * FROM (VALUES
            ('DEMO-X', 'FAM', 't', 'a', 'assignee', DATE '2024-01-01', 'WO', 'application')
        ) AS t(publication_number, family_key, title, abstract, assignee,
               publication_date, jurisdiction, doc_type))
        TO '""" + str(patents) + """' (FORMAT PARQUET)
        """
    )
    bad_dir = tmp_path / "fx"
    (bad_dir / "surechembl").mkdir(parents=True)
    (bad_dir / "patents").mkdir()
    records.rename(bad_dir / "surechembl" / "surechembl_demo_fixture.parquet")
    patents.rename(bad_dir / "patents" / "patent_documents_demo_fixture.parquet")

    bad = SureChemblFixtureAdapter(bad_dir).load()
    assert len(bad.mentions) == 0
    assert len(bad.issues) == 1
    assert bad.issues[0].source_record_id == "SC-T-1"
    assert bad.issues[0].issue == "missing_smiles"


def test_missing_fixture_files_raise_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        SureChemblFixtureAdapter(tmp_path)
