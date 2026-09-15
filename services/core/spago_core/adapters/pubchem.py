"""PubChem PUG REST adapter (ONLINE-00 B).

PubChem's role here is deliberately narrow (online-llm plan §2 ONLINE-00 B):

- **Identity** — confirm a candidate's structure against an independent
  authority (CID, canonical SMILES, InChIKey, formula). This is how a
  cross-source duplicate becomes visible instead of looking like independent
  corroboration.
- **Assay context** — a bounded list of BioAssay identifiers registered against
  the resolved gene symbol, so a user can see that screening data exists for a
  target. BioAssay records are *screening* evidence and are labelled as such;
  they are never presented as confirmed direct binding.

Exhaustive BioAssay harvesting is intentionally not implemented: the
`assaysummary` endpoint returns megabytes for a single compound (observed
2026-09-15: 1.8 MB for CID 2244) and PUG REST offers no paging for it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from spago_core.adapters.http import SourceClient, SourceUnavailableError
from spago_core.chemistry import clean_external_smiles
from spago_core.domain import RetrievalStatus

SOURCE_NAME = "pubchem"
SOURCE_VERSION = "pubchem-pug-rest"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

DEFAULT_MAX_AIDS = 25


@dataclass(frozen=True)
class CompoundIdentity:
    """Independent identity confirmation for one structure."""

    query: str
    cid: Optional[int]
    canonical_smiles: Optional[str]
    connectivity_smiles: Optional[str]
    inchikey: Optional[str]
    molecular_formula: Optional[str]
    status: str
    source_url: Optional[str]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreeningAssayContext:
    """Bounded screening-assay context for one resolved gene symbol."""

    gene_symbol: str
    assay_ids: tuple[int, ...]
    total_reported: int
    truncated: bool
    status: str
    source_url: Optional[str]
    notes: tuple[str, ...] = ()


class PubChemAdapter:
    """Identity confirmation and bounded BioAssay context."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        client: Optional[SourceClient] = None,
        max_aids: int = DEFAULT_MAX_AIDS,
    ) -> None:
        self.client = client or SourceClient(
            source_name=SOURCE_NAME,
            base_url="",
            min_interval_s=0.34,  # < 3 requests/second, per NCBI usage guidance
            timeout_s=30.0,
        )
        self.max_aids = max_aids

    # -- identity -------------------------------------------------------------

    def identify(self, smiles: str) -> CompoundIdentity:
        """Resolve a SMILES to its PubChem identity (CID, InChIKey, formula)."""
        cleaned, notes = clean_external_smiles(smiles)
        if not cleaned:
            return CompoundIdentity(
                query="",
                cid=None,
                canonical_smiles=None,
                connectivity_smiles=None,
                inchikey=None,
                molecular_formula=None,
                status=RetrievalStatus.EMPTY.value,
                source_url=None,
                notes=("Empty structure.",),
            )
        url = (
            f"{PUG}/compound/smiles/{_quote(cleaned)}/property/"
            "CanonicalSMILES,ConnectivitySMILES,InChIKey,MolecularFormula/JSON"
        )
        try:
            payload = self.client.get_json(url)
        except SourceUnavailableError as exc:
            return CompoundIdentity(
                query=cleaned,
                cid=None,
                canonical_smiles=None,
                connectivity_smiles=None,
                inchikey=None,
                molecular_formula=None,
                status=RetrievalStatus.FAILED.value,
                source_url=None,
                notes=tuple(notes) + (str(exc),),
            )

        properties = ((payload.get("PropertyTable") or {}).get("Properties") or [])
        if not properties:
            return CompoundIdentity(
                query=cleaned,
                cid=None,
                canonical_smiles=None,
                connectivity_smiles=None,
                inchikey=None,
                molecular_formula=None,
                status=RetrievalStatus.EMPTY.value,
                source_url=None,
                notes=tuple(notes) + ("PubChem returned no compound for this structure.",),
            )
        first = properties[0]
        cid = first.get("CID")
        return CompoundIdentity(
            query=cleaned,
            cid=cid,
            canonical_smiles=first.get("CanonicalSMILES"),
            connectivity_smiles=first.get("ConnectivitySMILES"),
            inchikey=first.get("InChIKey"),
            molecular_formula=first.get("MolecularFormula"),
            status=RetrievalStatus.COMPLETE.value,
            source_url=f"{PUG}/compound/cid/{cid}/JSON" if cid else None,
            notes=tuple(notes),
        )

    # -- screening context ----------------------------------------------------

    def screening_assays_for_gene(self, gene_symbol: str) -> ScreeningAssayContext:
        """BioAssay ids registered against a gene symbol (bounded, screening)."""
        gene = (gene_symbol or "").strip()
        if not gene:
            return ScreeningAssayContext(
                gene_symbol="",
                assay_ids=(),
                total_reported=0,
                truncated=False,
                status=RetrievalStatus.EMPTY.value,
                source_url=None,
                notes=("Empty gene symbol.",),
            )
        url = f"{PUG}/assay/target/genesymbol/{_quote(gene)}/aids/JSON"
        try:
            payload = self.client.get_json(url)
        except SourceUnavailableError as exc:
            if exc.status_code == 404:
                # PUG REST documents 404 as "no AIDs found for the given
                # target(s)": a genuine empty result, not an outage.
                return ScreeningAssayContext(
                    gene_symbol=gene,
                    assay_ids=(),
                    total_reported=0,
                    truncated=False,
                    status=RetrievalStatus.EMPTY.value,
                    source_url=url,
                    notes=(
                        "PubChem reports no BioAssay for this exact gene symbol. This "
                        "means no *PubChem-registered screening assay* matched, not that "
                        "no inhibitor exists.",
                    ),
                )
            return ScreeningAssayContext(
                gene_symbol=gene,
                assay_ids=(),
                total_reported=0,
                truncated=False,
                status=RetrievalStatus.FAILED.value,
                source_url=url,
                notes=(
                    str(exc),
                    "The PubChem target lookup path failed for this symbol; this is not "
                    "evidence that no assays exist.",
                ),
            )

        aids = (payload.get("IdentifierList") or {}).get("AID") or []
        ids = tuple(int(a) for a in aids if str(a).isdigit())
        truncated = len(ids) > self.max_aids
        shown = ids[: self.max_aids]
        return ScreeningAssayContext(
            gene_symbol=gene,
            assay_ids=shown,
            total_reported=len(ids),
            truncated=truncated,
            status=(
                RetrievalStatus.EMPTY.value
                if not ids
                else (RetrievalStatus.PARTIAL.value if truncated else RetrievalStatus.COMPLETE.value)
            ),
            source_url=f"{PUG}/assay/target/genesymbol/{_quote(gene)}/aids/JSON",
            notes=(
                "BioAssay records are screening data; they do not establish direct "
                "binding and are labelled accordingly.",
                (
                    f"{len(ids)} assays are registered; the first {len(shown)} are listed "
                    "under the configured request budget."
                    if truncated
                    else f"{len(ids)} assays are registered."
                ),
            ),
        )


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
