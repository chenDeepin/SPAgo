"""SPAgo services package: read/query orchestration over PostgreSQL.

- ``core``    — patent/family/compound/evidence reads (workloads B+C)
- ``projects``— save-to-project (M1)
- ``export``  — CSV/SDF export with provenance (M1)
"""
from spago_core.services.core import (  # noqa: F401
    CompoundPage,
    CompoundRow,
    FamilyOverview,
    NotFoundError,
    clamp_page,
    count_ingestion_issues,
    find_patent,
    get_compound,
    get_compound_smiles,
    get_dataset_info,
    get_family_overview,
    list_compound_evidence,
    list_family_compounds,
    list_ingestion_issues,
)
