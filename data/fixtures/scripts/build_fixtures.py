"""Deterministic generator for the SPAgo M0 synthetic fixture dataset.

All patent identifiers, assignees, and texts are synthetic (DEMO-* prefixes).
All SMILES are real, textbook-verifiable structures used to exercise chemistry
normalization: dedup (alternate SMILES of the same molecule), a stereoisomer
pair, a salt, a salt/parent pair, a claim-only mention, a malformed record,
and a compound with two mentions in one document (description + abstract).

Run:  python build_fixtures.py <output_dir>
Writes:
  <output_dir>/surechembl/surechembl_demo_fixture.parquet
  <output_dir>/patents/patent_documents_demo_fixture.parquet
  <output_dir>/manifest.json  (schema version, sha256 checksums, row counts)
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_VERSION = "demo-fixture-v1"
SOURCE_NAME = "surechembl_simplified_fixture"
ACTIVITY_SOURCE_NAME = "bioactivity_simplified_fixture"

ACTIVITY_SCHEMA = pa.schema(
    [
        ("compound_id", pa.string()),   # matches surechembl fixture compound_id
        ("target_key", pa.string()),
        ("target_name", pa.string()),
        ("assay_key", pa.string()),
        ("assay_type", pa.string()),
        ("standard_type", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("relation", pa.string()),
    ]
)

# Synthetic potency values for the ibuprofen/naproxen/aspirin-style compounds.
# Ties a measurement to the SAME SureChEMBL-local compound ids so provenance
# stays compound-local (label-based matching is explicitly avoided).
ACTIVITIES = [
    ("SC-DEMO-0005", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-1",
     "enzymatic", "IC50", 4100.0, "nM", "="),
    ("SC-DEMO-0006", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-1",
     "enzymatic", "IC50", 5200.0, "nM", "="),
    ("SC-DEMO-0007", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-1",
     "enzymatic", "IC50", 610.0, "nM", "="),
    ("SC-DEMO-0011", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-1",
     "enzymatic", "IC50", 22.0, "nM", "="),
    # Same compound, different assay: shown separately, never ranked together.
    ("SC-DEMO-0011", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-2",
     "cellular", "IC50", 210.0, "nM", "="),
    ("SC-DEMO-0001", "DEMO-TARGET-1", "Demo cyclooxygenase (synthetic)", "DEMO-ASSAY-1",
     "enzymatic", "IC50", 12800.0, "nM", ">"),
]

PATENT_SCHEMA = pa.schema(
    [
        ("publication_number", pa.string()),
        ("family_key", pa.string()),
        ("title", pa.string()),
        ("abstract", pa.string()),
        ("assignee", pa.string()),
        ("publication_date", pa.date32()),
        ("jurisdiction", pa.string()),
        ("doc_type", pa.string()),
    ]
)

RECORD_SCHEMA = pa.schema(
    [
        ("document_id", pa.string()),
        ("compound_id", pa.string()),
        ("patent_label", pa.string()),
        ("smiles", pa.string()),
        ("source_field", pa.string()),
        ("section", pa.string()),
        ("page", pa.int32()),
    ]
)

FAMILY_KEY = "DEMO-FAMILY-1"

PATENTS = [
    (
        "DEMO-PATENT-A",
        FAMILY_KEY,
        "Illustrative inhibitor compounds, part A (synthetic demo record)",
        "Synthetic demo abstract: illustrative chemical examples used for software "
        "verification. Not a real patent and not scientific data.",
        "Demo Research Institute (illustrative)",
        date(2024, 3, 15),
        "WO",
        "application",
    ),
    (
        "DEMO-PATENT-B",
        FAMILY_KEY,
        "Illustrative inhibitor compounds, part B (synthetic demo record)",
        "Synthetic demo abstract for a family member document.",
        "Demo Research Institute (illustrative)",
        date(2024, 9, 20),
        "EP",
        "application",
    ),
    (
        "DEMO-PATENT-C",
        FAMILY_KEY,
        "Illustrative inhibitor compounds, part C (synthetic demo record)",
        "Synthetic demo abstract for a granted family member.",
        "Demo Research Institute (illustrative)",
        date(2025, 6, 10),
        "US",
        "grant",
    ),
]

# (document_id, compound_id, patent_label, smiles, source_field, section, page)
RECORDS = [
    # DEMO-PATENT-A
    ("DEMO-PATENT-A", "SC-DEMO-0001", "Example 01", "CC(=O)Oc1ccccc1C(=O)O", "description", "Example 1", 4),
    ("DEMO-PATENT-A", "SC-DEMO-0002", "Example 02", "CC(=O)Nc1ccc(O)cc1", "description", "Example 2", 5),
    ("DEMO-PATENT-A", "SC-DEMO-0003", "Example 03", "Cn1c(=O)c2c(ncn2C)n(C)c1=O", "description", "Example 3", 6),
    # Same molecule as SC-DEMO-0003, mentioned in the abstract: no section/page available.
    ("DEMO-PATENT-A", "SC-DEMO-0004", "Compound A", "Cn1cnc2c1c(=O)n(C)c(=O)n2C", "abstract", None, None),
    ("DEMO-PATENT-A", "SC-DEMO-0005", "Example 04", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "description", "Example 4", 7),
    # DEMO-PATENT-B
    # Same molecule as SC-DEMO-0001 with an alternate (non-canonical) SMILES: dedup target.
    ("DEMO-PATENT-B", "SC-DEMO-0006", "Compound 12", "O=C(O)c1ccccc1OC(C)=O", "description", "Example 12", 11),
    # Stereo-specified member of the ibuprofen pair: must stay a distinct compound.
    ("DEMO-PATENT-B", "SC-DEMO-0007", "Example 07", "CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O", "description", "Example 7", 12),
    ("DEMO-PATENT-B", "SC-DEMO-0008", "Example 08", "CN(C)C(=N)N=C(N)N", "description", "Example 8", 13),
    # Malformed structure: must be recorded as a validation warning, never a compound.
    ("DEMO-PATENT-B", "SC-DEMO-0009", "Example 09", "N=C(N)this-is-not-valid-smiles", "description", "Example 9", 14),
    # Claim-only occurrence: no example section, no page.
    ("DEMO-PATENT-B", "SC-DEMO-0010", "Compound C-1", "O=C(N)c1ccccc1", "claims", None, None),
    # DEMO-PATENT-C
    ("DEMO-PATENT-C", "SC-DEMO-0011", "Example 11", "COc1ccc2cc(ccc2c1)[C@@H](C)C(=O)O", "description", "Example 11", 21),
    # Salt and its parent: distinct identities at M0 (salt stripping is out of scope).
    ("DEMO-PATENT-C", "SC-DEMO-0012", "Example 12", "[Na+].O=C([O-])c1ccccc1O", "description", "Example 12", 22),
    ("DEMO-PATENT-C", "SC-DEMO-0013", "Example 13", "O=C(O)c1ccccc1O", "description", "Example 13", 23),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])

    patents_tbl = pa.table(
        {
            "publication_number": [p[0] for p in PATENTS],
            "family_key": [p[1] for p in PATENTS],
            "title": [p[2] for p in PATENTS],
            "abstract": [p[3] for p in PATENTS],
            "assignee": [p[4] for p in PATENTS],
            "publication_date": [p[5] for p in PATENTS],
            "jurisdiction": [p[6] for p in PATENTS],
            "doc_type": [p[7] for p in PATENTS],
        },
        schema=PATENT_SCHEMA,
    )
    records_tbl = pa.table(
        {
            "document_id": [r[0] for r in RECORDS],
            "compound_id": [r[1] for r in RECORDS],
            "patent_label": [r[2] for r in RECORDS],
            "smiles": [r[3] for r in RECORDS],
            "source_field": [r[4] for r in RECORDS],
            "section": [r[5] for r in RECORDS],
            "page": [r[6] for r in RECORDS],
        },
        schema=RECORD_SCHEMA,
    )

    patents_path = out_dir / "patents" / "patent_documents_demo_fixture.parquet"
    records_path = out_dir / "surechembl" / "surechembl_demo_fixture.parquet"
    activities_path = out_dir / "bioactivity" / "bioactivity_demo_fixture.parquet"
    patents_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.parent.mkdir(parents=True, exist_ok=True)
    activities_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(patents_tbl, patents_path)
    pq.write_table(records_tbl, records_path)
    pq.write_table(
        pa.table(
            {
                "compound_id": [a[0] for a in ACTIVITIES],
                "target_key": [a[1] for a in ACTIVITIES],
                "target_name": [a[2] for a in ACTIVITIES],
                "assay_key": [a[3] for a in ACTIVITIES],
                "assay_type": [a[4] for a in ACTIVITIES],
                "standard_type": [a[5] for a in ACTIVITIES],
                "value": [a[6] for a in ACTIVITIES],
                "unit": [a[7] for a in ACTIVITIES],
                "relation": [a[8] for a in ACTIVITIES],
            },
            schema=ACTIVITY_SCHEMA,
        ),
        activities_path,
    )

    manifest = {
        "source_name": SOURCE_NAME,
        "dataset_version": SCHEMA_VERSION,
        "generated_on": "2026-09-14",
        "synthetic": True,
        "note": "Synthetic fixture for software verification. Not scientific data.",
        "files": {
            "patents/patent_documents_demo_fixture.parquet": {
                "sha256": sha256(patents_path),
                "rows": len(PATENTS),
            },
            "surechembl/surechembl_demo_fixture.parquet": {
                "sha256": sha256(records_path),
                "rows": len(RECORDS),
            },
            "bioactivity/bioactivity_demo_fixture.parquet": {
                "sha256": sha256(activities_path),
                "rows": len(ACTIVITIES),
            },
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {patents_path}")
    print(f"wrote {records_path}")
    print(f"wrote {activities_path}")
    print(f"wrote {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
