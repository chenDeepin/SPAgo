"""BindingDB activity adapter (Milestone 3).

BindingDB distributes curated TSV downloads
(https://www.bindingdb.org/bind/downloads.jsp). This adapter reads a
user-provided download file and maps it onto the SPAgo activity contract —
it deliberately performs no crawling or scraping (AGENTS.md §5/§16).

The relevant columns of the standard export:
    ChEMBL ID of Ligand / SMILES
    BindingDB Target Chain  ...  (multiple columns; pass the chosen one)
    IC50 (nM) / Ki (nM) / EC50 (nM)   (one of them per selected column)
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.domain import SourceEnvelope

EXTRACTION_METHOD = "bindingdb_tsv_import"


class BindingDBTsvAdapter:
    """Reads a local BindingDB TSV export (already filtered by the user)."""

    source_name = "bindingdb"

    def __init__(
        self,
        tsv_path: Path,
        compound_map: dict[str, str],
        value_column: str = "IC50 (nM)",
        target_name_column: str | None = None,
    ) -> None:
        """
        compound_map: SMILES (as in the TSV ligand column) -> SPAgo compound_source_id.
        value_column: which standard measurement column to import.
        """
        self.tsv_path = Path(tsv_path)
        self.compound_map = compound_map
        self.value_column = value_column
        self.target_name_column = target_name_column
        if not self.tsv_path.exists():
            raise FileNotFoundError(
                f"BindingDB TSV not found: {self.tsv_path}. Download it from "
                "https://www.bindingdb.org/bind/downloads.jsp and provide the path."
            )

    def load(self) -> ActivityResult:
        warnings: list[str] = []
        records: list[ActivityRecord] = []
        retrieved_at = datetime.now(timezone.utc)

        with self.tsv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for idx, row in enumerate(reader):
                smiles = (row.get("Ligand SMILES") or row.get("SMILES") or "").strip()
                source_id = self.compound_map.get(smiles)
                if source_id is None:
                    continue
                raw = (row.get(self.value_column) or "").strip()
                if not raw:
                    continue
                value_str = raw.lstrip("<>~")
                relation = raw[0] if raw[0] in "<>~" else "="
                try:
                    value = float(value_str)
                except ValueError:
                    warnings.append(f"Row {idx}: unparseable {self.value_column} value {raw!r}; skipped")
                    continue
                target_name = (
                    row.get(self.target_name_column, "").strip()
                    if self.target_name_column
                    else None
                ) or None
                records.append(
                    ActivityRecord(
                        source_record_id=f"bindingdb:{idx}",
                        compound_source_id=source_id,
                        target_key=target_name or "bindingdb-unknown-target",
                        target_name=target_name,
                        assay_key=f"bindingdb:{target_name or 'unknown'}",
                        assay_type="binding",
                        standard_type=self.value_column.split(" ")[0],  # e.g. IC50
                        value=value,
                        unit="nM",
                        relation=relation,
                    )
                )

        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=self.source_name,
                source_version=f"tsv:{self.tsv_path.name}",
                dataset_version=f"bindingdb:{retrieved_at.date().isoformat()}",
                retrieved_at=retrieved_at,
                synthetic=False,
                warnings=warnings,
            ),
            records=records,
            warnings=warnings,
        )
