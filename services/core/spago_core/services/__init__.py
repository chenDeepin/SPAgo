"""SPAgo services package: read/query orchestration over PostgreSQL.

- ``core``        — patent/family/compound/evidence reads (workloads B+C)
- ``projects``    — save-to-project (M1)
- ``export``      — CSV/SDF export with provenance (M1)
- ``targets``     — target resolution and reviewed biological scope (ONLINE-00 A)
- ``discovery``   — target-led open-database retrieval and candidates (ONLINE-00 B/C)
- ``target_scope``— curated ligand/receptor/pathway catalog (data, not code)
"""
from spago_core.services.core import (  # noqa: F401
    AmbiguousError,
    CompoundPage,
    CompoundRow,
    FamilyOverview,
    NotFoundError,
    PatentLookup,
    clamp_page,
    corpus_summary,
    count_ingestion_issues,
    find_patent,
    get_compound,
    get_compound_smiles,
    get_dataset_info,
    get_family_overview,
    list_compound_evidence,
    list_compound_mentions,
    list_family_compounds,
    list_ingestion_issues,
    list_dataset_infos,
)
from spago_core.services.targets import (  # noqa: F401
    TargetResolutionService,
    target_id_for_key,
)
