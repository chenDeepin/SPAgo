"""M3 bioactivity tests: fixture adapter, ChEMBL/BindingDB contracts, DB + API."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from spago_core.adapters import (
    BioactivityFixtureAdapter,
    BioactivitySource,
    BindingDBTsvAdapter,
    ChEMBLActivityAdapter,
)


def test_fixture_adapter_satisfies_contract(fixture_dir: Path):
    adapter = BioactivityFixtureAdapter(fixture_dir)
    assert isinstance(adapter, BioactivitySource)
    result = adapter.load()
    assert result.envelope.source_name == "bioactivity_simplified_fixture"
    assert result.envelope.dataset_version == "demo-fixture-v1"
    assert result.envelope.synthetic is True
    assert len(result.records) == 6


def test_fixture_values_stay_as_reported(fixture_dir: Path):
    result = BioactivityFixtureAdapter(fixture_dir).load()
    by_source = {r.source_record_id: r for r in result.records}
    enzymatic = by_source["DEMO-ASSAY-1:SC-DEMO-0011"]
    cellular = by_source["DEMO-ASSAY-2:SC-DEMO-0011"]
    # Same compound in two assays: kept separate, never ranked together.
    assert enzymatic.value == 22.0 and cellular.value == 210.0
    assert enzymatic.assay_key != cellular.assay_key


def test_chembl_adapter_maps_and_filters():
    payload = {
        "activities": [
            {
                "activity_id": 1001,
                "molecule_chembl_id": "CHEMBL999",
                "molecule_canonical_smiles": "CCO",
                "assay_chembl_id": "CHEMBL-A1",
                "assay_type": "B",
                "standard_type": "IC50",
                "standard_units": "nM",
                "standard_value": 5.5,
                "relation": "=",
                "target_pref_name": "Demo target",
            },
            {"activity_id": 1002, "molecule_chembl_id": "CHEMBL999", "molecule_canonical_smiles": "CCC", "standard_value": None},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "target_chembl_id=CHEMBL123" in str(request.url)
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://www.ebi.ac.uk")
    adapter = ChEMBLActivityAdapter(
        target_chembl_id="CHEMBL123",
        compound_map={"CHEMBL999": "spago-source-1"},
        client=client,
    )
    result = adapter.load(max_pages=1)
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.compound_source_id == "spago-source-1"
    assert rec.standard_type == "IC50" and rec.value == 5.5 and rec.unit == "nM"
    assert rec.source_record_id == "1001"
    # unmapped/unparseable rows produce warnings, not silent drops
    assert result.warnings and "no standard_value" in result.warnings[0]


def test_chembl_adapter_failure_becomes_warning():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://www.ebi.ac.uk")
    adapter = ChEMBLActivityAdapter("CHEMBL1", {}, client=client)
    result = adapter.load(max_pages=1)
    assert result.records == []
    assert result.warnings and "failed" in result.warnings[0]


def test_bindingdb_adapter_reads_tsv(tmp_path: Path):
    tsv = tmp_path / "bindingdb.tsv"
    tsv.write_text(
        "Ligand SMILES\tIC50 (nM)\tTarget Name\n"
        "CCO\t120\tDemo kinase\n"
        "CCC\t<25\tDemo kinase\n"
        "CCC\tjunk\tDemo kinase\n",
        encoding="utf-8",
    )
    adapter = BindingDBTsvAdapter(
        tsv, compound_map={"CCO": "src-1", "CCC": "src-2"}, value_column="IC50 (nM)",
        target_name_column="Target Name",
    )
    assert isinstance(adapter, BioactivitySource)
    result = adapter.load()
    assert len(result.records) == 2
    by_id = {r.compound_source_id for r in result.records}
    assert by_id == {"src-1", "src-2"}
    rel = {r.compound_source_id: r.relation for r in result.records}
    assert rel["src-2"] == "<"
    assert any("junk" in w for w in result.warnings)


def test_bindingdb_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        BindingDBTsvAdapter(tmp_path / "nope.tsv", {})
