"""Fixture bioactivity adapter: reads the synthetic activities Parquet via DuckDB."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.domain import SourceEnvelope

EXTRACTION_METHOD = "bioactivity_simplified_fixture_import"


class BioactivityFixtureAdapter:
    source_name = "bioactivity_simplified_fixture"

    def __init__(self, fixture_dir: Path) -> None:
        self.activities_path = Path(fixture_dir) / "bioactivity" / "bioactivity_demo_fixture.parquet"
        self.manifest_path = Path(fixture_dir) / "manifest.json"
        if not self.activities_path.exists():
            raise FileNotFoundError(
                f"Bioactivity fixture not found: {self.activities_path} "
                "(regenerate fixtures with data/fixtures/scripts/build_fixtures.py)"
            )

    def load(self) -> ActivityResult:
        manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        warnings: list[str] = []
        rows = duckdb.execute(
            f"""
            SELECT compound_id, target_key, target_name, assay_key, assay_type,
                   standard_type, value, unit, relation
            FROM read_parquet('{self.activities_path.as_posix()}')
            ORDER BY compound_id, assay_key
            """
        ).fetchall()

        records = []
        for r in rows:
            (
                compound_id, target_key, target_name, assay_key, assay_type,
                standard_type, value, unit, relation,
            ) = r
            if value is None or value <= 0:
                warnings.append(f"Activity row for {compound_id} has invalid value {value!r}; skipped")
                continue
            records.append(
                ActivityRecord(
                    source_record_id=f"{assay_key}:{compound_id}",
                    compound_source_id=compound_id,
                    target_key=target_key,
                    target_name=target_name,
                    assay_key=assay_key,
                    assay_type=assay_type,
                    standard_type=standard_type,
                    value=float(value),
                    unit=unit,
                    relation=relation or "=",
                )
            )

        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=self.source_name,
                source_version="fixture",
                dataset_version=manifest.get("dataset_version", "unknown"),
                retrieved_at=datetime.now(timezone.utc),
                synthetic=bool(manifest.get("synthetic", False)),
                warnings=warnings,
            ),
            records=records,
            warnings=warnings,
        )
