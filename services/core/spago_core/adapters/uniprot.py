"""UniProt target resolution adapter (ONLINE-00 A).

Authoritative protein identity for a requested target: stable accessions,
reviewed status, gene names and synonyms, organism and taxon. It answers
*identity* questions only — no activity, potency or inhibitor claims come from
this source (online-llm plan §2 ONLINE-00 B).

Access path: the UniProt REST search API (`/uniprotkb/search`), queried with
`format=json`. Verified against the live service on 2026-09-15: a
`(gene_exact:TSLP) AND (organism_id:9606)` query returns Q969D9 / TSLP_HUMAN.

Ambiguity is preserved: several entries may match, and `components` describes
membership of a complex. The resolver returns them all and lets the service
decide and record which one was chosen and why.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from spago_core.adapters.http import SourceClient, SourceUnavailableError
from spago_core.domain import (
    RetrievalStatus,
    TargetCandidateEntry,
    TargetComponent,
    TargetLookupResult,
    TargetType,
)

SOURCE_NAME = "uniprot"
SEARCH_PATH = "/uniprotkb/search"
MAX_RESULTS = 10

#: Species the workflow supports explicitly. The default is human and the UI
#: shows it (online-llm plan §2 ONLINE-00 A); numeric taxon ids are accepted.
SPECIES_TAXON: dict[str, int] = {
    "human": 9606,
    "homo sapiens": 9606,
    "mouse": 10090,
    "mus musculus": 10090,
    "rat": 10116,
    "rattus norvegicus": 10116,
    "cynomolgus": 9541,
    "macaque": 9544,
}


def species_taxon(species: str) -> Optional[int]:
    value = (species or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return SPECIES_TAXON.get(value.lower())


_ENTRY_TYPE_MAP = {
    "uniprotkb reviewed (swiss-prot)": True,
    "uniprotkb unreviewed (trembl)": False,
}


def _flatten_text(node) -> Optional[str]:
    """UniProt JSON wraps text in {'value': ...}; also seen as plain strings."""
    if node is None:
        return None
    if isinstance(node, str):
        return node or None
    if isinstance(node, dict):
        value = node.get("value")
        return value or None
    return None


def _protein_name(entry: dict) -> Optional[str]:
    description = entry.get("proteinDescription") or {}
    recommended = description.get("recommendedName") or {}
    name = _flatten_text(recommended.get("fullName"))
    if name:
        return name
    for submission in description.get("submissionNames") or []:
        name = _flatten_text((submission or {}).get("fullName"))
        if name:
            return name
    for alternative in description.get("alternativeNames") or []:
        name = _flatten_text((alternative or {}).get("fullName"))
        if name:
            return name
    return None


def _gene_symbol(entry: dict) -> Optional[str]:
    genes = entry.get("genes") or []
    for gene in genes:
        value = _flatten_text((gene.get("geneName") or {}).get("value"))
        if value:
            return value
    return None


def _gene_synonyms(entry: dict) -> list[str]:
    synonyms: list[str] = []
    for gene in entry.get("genes") or []:
        for synonym in gene.get("synonyms") or []:
            value = _flatten_text((synonym or {}).get("value"))
            if value and value not in synonyms:
                synonyms.append(value)
    return synonyms


def _reviewed(entry: dict) -> Optional[bool]:
    entry_type = (entry.get("entryType") or "").strip().lower()
    return _ENTRY_TYPE_MAP.get(entry_type)


def _components(entry: dict) -> list[TargetComponent]:
    """Component membership: a UniProt entry can describe a complex, and the
    members must stay distinct from the complex itself (ONLINE-00 A)."""
    components: list[TargetComponent] = []
    description = entry.get("proteinDescription") or {}
    containing = description.get("contains") or []
    for item in containing:
        recommended = (item or {}).get("recommendedName") or {}
        components.append(
            TargetComponent(
                name=_flatten_text(recommended.get("fullName")),
                organism=(entry.get("organism") or {}).get("scientificName"),
                role="contains",
            )
        )
    for subunit in (entry.get("uniProtKBCrossReferences") or []):
        if (subunit.get("database") or "").upper() == "COMPLEXPORTAL":
            components.append(
                TargetComponent(
                    accession=subunit.get("id"),
                    name=f"ComplexPortal {subunit.get('id')}",
                    role="complex_membership",
                )
            )
    return components


def _target_type(entry: dict) -> TargetType:
    text = " ".join(
        filter(
            None,
            [
                _protein_name(entry),
                " ".join(_gene_synonyms(entry)),
            ],
        )
    ).lower()
    if "complex" in text:
        return TargetType.PROTEIN_COMPLEX
    return TargetType.SINGLE_PROTEIN


def entry_to_candidate(entry: dict) -> Optional[TargetCandidateEntry]:
    accession = entry.get("primaryAccession")
    if not accession:
        return None
    organism = entry.get("organism") or {}
    genes = _gene_symbol(entry)
    synonyms = _gene_synonyms(entry)
    notes: list[str] = []
    if (entry.get("proteinExistence") or ""):
        notes.append(f"protein existence: {entry['proteinExistence']}")
    if synonyms:
        notes.append("gene synonyms: " + ", ".join(synonyms))
    return TargetCandidateEntry(
        identifier=accession,
        identifier_kind="uniprot_accession",
        name=_protein_name(entry),
        gene_symbol=genes,
        synonyms=synonyms,
        organism=organism.get("scientificName"),
        taxon_id=organism.get("taxonId"),
        target_type=_target_type(entry),
        reviewed=_reviewed(entry),
        components=_components(entry),
        source_name=SOURCE_NAME,
        source_url=f"https://www.uniprot.org/uniprotkb/{accession}/entry",
        notes=notes,
    )


class UniProtTargetResolver:
    """Resolves a target name/gene/accession to UniProt protein identities."""

    source_name = SOURCE_NAME
    source_version = "uniprot-rest-uniprotkb"

    def __init__(
        self,
        client: Optional[SourceClient] = None,
        max_results: int = MAX_RESULTS,
    ) -> None:
        self.client = client or SourceClient(
            source_name=SOURCE_NAME,
            base_url="https://rest.uniprot.org",
            min_interval_s=0.15,
        )
        self.max_results = max_results

    # -- queries -------------------------------------------------------------

    def _search(self, query: str, *, fields: str | None = None) -> dict:
        params = {"query": query, "format": "json", "size": str(self.max_results)}
        if fields:
            params["fields"] = fields
        return self.client.get_json(SEARCH_PATH, params=params)

    def resolve(
        self,
        query: str,
        species: str = "human",
        *,
        reviewed_only: bool = False,
        accession: bool = False,
    ) -> TargetLookupResult:
        """Resolve `query` to UniProt entries for one species.

        `accession=True` treats the query as an accession. Gene-exact matches
        are tried first, then a general term search, so "TSLP" resolves to the
        TSLP ligand rather than to any entry mentioning the string.
        """
        query = (query or "").strip()
        retrieved_at = datetime.now(timezone.utc)
        if not query:
            return TargetLookupResult(
                source_name=SOURCE_NAME,
                query=query,
                status=RetrievalStatus.EMPTY,
                retrieved_at=retrieved_at,
                warnings=["Empty target query."],
            )

        taxon = species_taxon(species)
        if species and taxon is None:
            return TargetLookupResult(
                source_name=SOURCE_NAME,
                query=query,
                status=RetrievalStatus.NOT_QUERIED,
                retrieved_at=retrieved_at,
                warnings=[
                    f"Unsupported species {species!r}; supported: "
                    + ", ".join(sorted(set(SPECIES_TAXON)))
                    + ", or a numeric NCBI taxon id."
                ],
            )

        organism_clause = f" AND (organism_id:{taxon})" if taxon else ""
        escaped = quote(query, safe="")
        if accession:
            attempts = [f"(accession:{escaped}){organism_clause}"]
        else:
            attempts = [
                f"(gene_exact:{escaped}){organism_clause}",
                f"(protein_name:{escaped} OR gene:{escaped}){organism_clause}",
                f"({escaped}){organism_clause}",
            ]

        warnings: list[str] = []
        try:
            payload: dict = {}
            for index, candidate_query in enumerate(attempts):
                payload = self._search(candidate_query)
                if payload.get("results"):
                    if index > 0:
                        warnings.append(
                            "No exact gene-name match; a broader term search was used."
                        )
                    break
        except SourceUnavailableError as exc:
            return TargetLookupResult(
                source_name=SOURCE_NAME,
                query=query,
                status=RetrievalStatus.FAILED,
                retrieved_at=retrieved_at,
                warnings=[str(exc)],
            )

        entries = [
            candidate
            for candidate in (entry_to_candidate(e) for e in payload.get("results") or [])
            if candidate is not None
        ]
        if reviewed_only:
            filtered = [e for e in entries if e.reviewed]
            if filtered:
                entries = filtered

        total = int(payload.get("totalResults") or len(entries) or 0)
        truncated = total > len(entries)
        if truncated:
            warnings.append(
                f"{total} UniProt entries matched; the first {len(entries)} are listed."
            )
        status = (
            RetrievalStatus.EMPTY
            if not entries
            else (RetrievalStatus.PARTIAL if truncated else RetrievalStatus.COMPLETE)
        )
        return TargetLookupResult(
            source_name=SOURCE_NAME,
            query=query,
            status=status,
            entries=entries,
            total_found=total,
            truncated=truncated,
            source_version=self.source_version,
            retrieved_at=retrieved_at,
            warnings=warnings,
        )
