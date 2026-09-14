"""DuckDB-over-Parquet bulk layer tests (workload A)."""
from __future__ import annotations

from pathlib import Path

import pytest

from spago_core.queries import compound_counts_by_document, records_for_document


def test_counts_by_document(fixture_dir: Path):
    counts = {c.document_id: c.record_count for c in compound_counts_by_document(fixture_dir)}
    assert counts == {
        "DEMO-PATENT-A": 5,
        "DEMO-PATENT-B": 5,
        "DEMO-PATENT-C": 3,
    }


def test_records_for_document_scopes_correctly(fixture_dir: Path):
    rows = records_for_document(fixture_dir, "DEMO-PATENT-C")
    assert len(rows) == 3
    assert all(r[0] == "DEMO-PATENT-C" for r in rows)
    smiles = {r[3] for r in rows}
    assert "COc1ccc2cc(ccc2c1)[C@@H](C)C(=O)O" in smiles


def test_unknown_document_returns_empty(fixture_dir: Path):
    assert records_for_document(fixture_dir, "NOPE") == []


def test_missing_fixture_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        compound_counts_by_document(tmp_path)
