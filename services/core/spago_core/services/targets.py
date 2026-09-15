"""Target resolution service (ONLINE-00 A).

Turns a user request ("TSLP", "CD40LG", "Q969D9") into a persisted, reviewable
biological scope:

- the resolver proposes; the user (or the documented default rule) selects;
- every resolution run is stored with its candidates *and* its exclusions, so
  "why did SPAgo query this protein" is answerable later;
- the chosen target row carries its UniProt accession, gene symbol, taxon,
  target type, component membership and the mapping provenance.

Selection rule (deterministic and documented, never silent):

1. prefer a reviewed (Swiss-Prot) entry over an unreviewed one;
2. prefer an exact gene-symbol match over a synonym/name match;
3. prefer the species the user asked for (default human);
4. if two candidates remain equally preferable, the run is recorded as
   `ambiguous` and no target is chosen — the API returns the alternatives for
   the user to pick.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver, species_taxon
from spago_core.domain import (
    ResolutionCandidate,
    ResolvedTarget,
    RetrievalStatus,
    ScopeKind,
    TargetCandidateEntry,
    TargetComponent,
    TargetResolutionRecord,
    TargetType,
)
from spago_core.services.target_scope import (
    ScopeMember,
    TargetScopeCatalog,
    load_catalog,
)

#: Stable id namespace, matching the seed pipeline's scheme so an externally
#: resolved target and a patent-derived target with the same key are one row.
TARGET_NAMESPACE = uuid.UUID("3d2f1a8e-6c05-4d9b-9d3a-1f2e8b7c5a10")
RESOLUTION_NAMESPACE = uuid.UUID("b7c4e2d1-8a39-4f60-9c15-2d7e6a4b3f08")

DEFAULT_SPECIES = "human"


def target_id_for_key(target_key: str) -> uuid.UUID:
    return uuid.uuid5(TARGET_NAMESPACE, f"target:{target_key}")


def _role_to_scope(roles: list[str]) -> ScopeKind | None:
    joined = " ".join(r or "" for r in roles).lower()
    if "ligand" in joined:
        return ScopeKind.LIGAND
    if "receptor" in joined:
        return ScopeKind.RECEPTOR
    if "signalling" in joined or "component" in joined:
        return ScopeKind.COMPLEX
    if joined.strip():
        return ScopeKind.PATHWAY
    return None


@dataclass
class ResolutionOutcome:
    """Service-level result: the record plus what was stored."""

    record: TargetResolutionRecord
    target: Optional[ResolvedTarget]
    stored: bool


def _entry_to_candidate(entry: TargetCandidateEntry, reason: str) -> ResolutionCandidate:
    return ResolutionCandidate(
        identifier=entry.identifier,
        name=entry.name,
        organism=entry.organism,
        target_type=entry.target_type,
        source_name=entry.source_name,
        reason=reason,
    )


def _preference(entry: TargetCandidateEntry, query: str) -> tuple:
    """Ranking key: reviewed first, then exact gene match, then species."""
    gene = (entry.gene_symbol or "").strip().lower()
    query_lower = (query or "").strip().lower()
    return (
        0 if entry.reviewed else 1,
        0 if gene == query_lower else (1 if query_lower in gene else 2),
        0 if entry.taxon_id == 9606 else 1,
        entry.identifier,
    )


class TargetResolutionService:
    """Resolve, persist and read back target scope."""

    def __init__(
        self,
        uniprot: Optional[UniProtTargetResolver] = None,
        chembl: Optional[ChEMBLDiscoveryAdapter] = None,
    ) -> None:
        self.uniprot = uniprot or UniProtTargetResolver()
        self.chembl = chembl or ChEMBLDiscoveryAdapter()

    # -- resolution -----------------------------------------------------------

    def resolve(
        self,
        engine: Engine,
        query: str,
        species: str = DEFAULT_SPECIES,
        *,
        persist: bool = True,
        include_related: bool = True,
    ) -> ResolutionOutcome:
        """Resolve a target and (by default) persist the reviewed scope."""
        query = (query or "").strip()
        species = (species or DEFAULT_SPECIES).strip() or DEFAULT_SPECIES
        retrieved_at = datetime.now(timezone.utc)
        notes: list[str] = []

        lookup = self.uniprot.resolve(query, species, accession=_looks_like_accession(query))
        if lookup.status is RetrievalStatus.FAILED:
            return ResolutionOutcome(
                record=self._record(
                    query, species, "failed", None, None, [], [], lookup.warnings, retrieved_at
                ),
                target=None,
                stored=False,
            )
        if lookup.status is RetrievalStatus.NOT_QUERIED:
            # The request was refused before any lookup (e.g. an unsupported
            # species). That is neither "no such target" nor a source failure.
            return ResolutionOutcome(
                record=self._record(
                    query, species, "not_queried", None, None, [], [], lookup.warnings, retrieved_at
                ),
                target=None,
                stored=False,
            )
        if not lookup.entries:
            notes.extend(lookup.warnings)
            notes.append(
                "No UniProt entry matched. This says nothing about whether inhibitors "
                "exist for the intended target; check the gene symbol or use an accession."
            )
            return ResolutionOutcome(
                record=self._record(
                    query, species, "not_found", None, None, [], [], notes, retrieved_at
                ),
                target=None,
                stored=False,
            )

        ranked = sorted(lookup.entries, key=lambda e: _preference(e, query))
        return self._select_and_store(
            engine, query, species, ranked, lookup.warnings, retrieved_at,
            persist=persist, include_related=include_related,
        )

    def _select_and_store(
        self,
        engine: Engine,
        query: str,
        species: str,
        ranked: list[TargetCandidateEntry],
        warnings: list[str],
        retrieved_at: datetime,
        *,
        persist: bool,
        include_related: bool,
    ) -> ResolutionOutcome:
        chosen, runner_up, ambiguous = self._choose(ranked, query)
        candidates = [_entry_to_candidate(e, "considered") for e in ranked]
        excluded: list[ResolutionCandidate] = []
        notes = list(warnings)

        if ambiguous:
            notes.append(
                "Several candidates are equally strong matches; no target was chosen. "
                "Select one so the evidence scope is explicit."
            )
            return ResolutionOutcome(
                record=self._record(
                    query, species, "ambiguous", None, None, candidates, excluded, notes, retrieved_at
                ),
                target=None,
                stored=False,
            )

        catalog_error: Optional[str] = None
        catalog = None
        try:
            catalog = load_catalog()
        except Exception as exc:  # ScopeCatalogUnavailable or a malformed catalog
            catalog_error = str(exc)
        if catalog_error is not None:
            notes.append(
                "The reviewed ligand/receptor/pathway catalog could not be loaded, so no "
                "related-partner expansion was offered. This is a deployment problem, not "
                f"a statement about the target: {catalog_error}"
            )
            catalog = TargetScopeCatalog(
                reviewed_on="unavailable",
                purpose="catalog unavailable",
                disclaimer="No reviewed mapping was loaded.",
            )
        member = catalog.member_for(chosen.identifier) or (
            catalog.member_for(chosen.gene_symbol or "") if chosen.gene_symbol else None
        )
        system = catalog.system_for(chosen.identifier) or (
            catalog.system_for(chosen.gene_symbol or "") if chosen.gene_symbol else None
        )
        if member is None:
            notes.append(
                "This target has no reviewed ligand/receptor/pathway mapping, so no "
                "related-partner expansion is offered. Add a reviewed catalog entry to "
                "enable one."
            )
        if runner_up is not None:
            excluded.append(
                _entry_to_candidate(
                    runner_up,
                    "lower-ranked alternative (unreviewed entry or non-exact gene match)",
                )
            )

        components = list(chosen.components)
        related_members: list[tuple[ScopeMember, str]] = []
        if include_related:
            related_members = catalog.related_members(chosen.identifier) or (
                catalog.related_members(chosen.gene_symbol or "") if chosen.gene_symbol else []
            )
            for related, reason in related_members:
                components.append(
                    TargetComponent(
                        accession=related.accession,
                        name=related.name,
                        gene_symbol=related.gene_symbol,
                        role=related.role,
                        organism=related.organism,
                    )
                )
                notes.append(f"Related {related.role}: {related.gene_symbol} — {reason}")

        target_key = chosen.gene_symbol or chosen.identifier
        target = ResolvedTarget(
            id=target_id_for_key(target_key),
            target_key=target_key,
            name=chosen.name,
            organism=chosen.organism,
            taxon_id=chosen.taxon_id,
            uniprot_accession=chosen.identifier,
            gene_symbol=chosen.gene_symbol,
            target_type=chosen.target_type,
            scope_kind=_role_to_scope([member.role] if member else []),
            aliases=sorted({chosen.gene_symbol or "", *chosen.synonyms} - {""}),
            components=components,
            source_name="uniprot",
            dataset_version=f"uniprot:{retrieved_at.date().isoformat()}",
        )
        record = self._record(
            query, species, "resolved", target.id, chosen.identifier,
            candidates, excluded, notes, retrieved_at,
        )
        if persist:
            self._persist(engine, target, record)
        return ResolutionOutcome(record=record, target=target, stored=persist)

    def _choose(
        self, ranked: list[TargetCandidateEntry], query: str
    ) -> tuple[TargetCandidateEntry, Optional[TargetCandidateEntry], bool]:
        chosen = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        if runner_up is None:
            return chosen, None, False
        # Ambiguity is decided on the first two preference fields only: the
        # accession tiebreak must never be what picks a target for a user.
        if _preference(chosen, query)[:3] == _preference(runner_up, query)[:3]:
            return chosen, runner_up, True
        return chosen, runner_up, False

    def _record(
        self,
        query: str,
        species: str,
        status: str,
        target_id: Optional[uuid.UUID],
        identifier: Optional[str],
        candidates: list[ResolutionCandidate],
        excluded: list[ResolutionCandidate],
        notes: list[str],
        retrieved_at: datetime,
    ) -> TargetResolutionRecord:
        return TargetResolutionRecord(
            id=uuid.uuid5(RESOLUTION_NAMESPACE, f"resolution:{query}:{species}:{retrieved_at.isoformat()}"),
            query=query,
            species=species,
            status=status,
            chosen_target_id=target_id,
            chosen_identifier=identifier,
            candidates=candidates,
            excluded=excluded,
            source_name="uniprot",
            source_version=self.uniprot.source_version,
            retrieved_at=retrieved_at,
            notes=notes,
        )

    # -- persistence ----------------------------------------------------------

    def _persist(
        self,
        engine: Engine,
        target: ResolvedTarget,
        record: TargetResolutionRecord,
    ) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, organism, source_name,
                                         dataset_version, retrieved_at, uniprot_accession,
                                         gene_symbol, taxon_id, target_type, scope_kind,
                                         aliases, components, resolution)
                    VALUES (:id, :target_key, :name, :organism, :source_name,
                            :dataset_version, :retrieved_at, :uniprot_accession,
                            :gene_symbol, :taxon_id, :target_type, :scope_kind,
                            CAST(:aliases AS jsonb), CAST(:components AS jsonb),
                            CAST(:resolution AS jsonb))
                    ON CONFLICT (id) DO UPDATE
                      SET name = EXCLUDED.name,
                          organism = EXCLUDED.organism,
                          source_name = EXCLUDED.source_name,
                          dataset_version = EXCLUDED.dataset_version,
                          retrieved_at = EXCLUDED.retrieved_at,
                          uniprot_accession = EXCLUDED.uniprot_accession,
                          gene_symbol = EXCLUDED.gene_symbol,
                          taxon_id = EXCLUDED.taxon_id,
                          target_type = EXCLUDED.target_type,
                          scope_kind = EXCLUDED.scope_kind,
                          aliases = EXCLUDED.aliases,
                          components = EXCLUDED.components,
                          resolution = EXCLUDED.resolution
                    """
                ),
                {
                    "id": target.id,
                    "target_key": target.target_key,
                    "name": target.name,
                    "organism": target.organism,
                    "source_name": target.source_name,
                    "dataset_version": target.dataset_version,
                    "retrieved_at": record.retrieved_at,
                    "uniprot_accession": target.uniprot_accession,
                    "gene_symbol": target.gene_symbol,
                    "taxon_id": target.taxon_id,
                    "target_type": target.target_type.value if target.target_type else None,
                    "scope_kind": target.scope_kind.value if target.scope_kind else None,
                    "aliases": json.dumps(target.aliases),
                    "components": json.dumps([c.model_dump() for c in target.components]),
                    "resolution": json.dumps(
                        {
                            "query": record.query,
                            "species": record.species,
                            "source_name": record.source_name,
                            "source_version": record.source_version,
                            "retrieved_at": record.retrieved_at.isoformat(),
                            "resolution_id": str(record.id),
                        }
                    ),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO target_resolutions (id, query, species, status,
                                                    chosen_target_id, chosen_identifier,
                                                    candidates, excluded, source_name,
                                                    source_version, notes, retrieved_at)
                    VALUES (:id, :query, :species, :status, :chosen_target_id,
                            :chosen_identifier, CAST(:candidates AS jsonb),
                            CAST(:excluded AS jsonb), :source_name, :source_version,
                            CAST(:notes AS jsonb), :retrieved_at)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": record.id,
                    "query": record.query,
                    "species": record.species,
                    "status": record.status,
                    "chosen_target_id": record.chosen_target_id,
                    "chosen_identifier": record.chosen_identifier,
                    "candidates": json.dumps([c.model_dump(mode="json") for c in record.candidates]),
                    "excluded": json.dumps([c.model_dump(mode="json") for c in record.excluded]),
                    "source_name": record.source_name,
                    "source_version": record.source_version,
                    "notes": json.dumps(record.notes),
                    "retrieved_at": record.retrieved_at,
                },
            )

    # -- reads ----------------------------------------------------------------

    def get_target(self, engine: Engine, target_id: uuid.UUID) -> ResolvedTarget:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, target_key, name, organism, taxon_id, uniprot_accession,
                           gene_symbol, target_type, scope_kind, aliases, components,
                           source_name, dataset_version
                    FROM targets WHERE id = :id
                    """
                ),
                {"id": target_id},
            ).mappings().first()
        if row is None:
            from spago_core.services import NotFoundError

            raise NotFoundError(f"Target {target_id} not found.")
        return _row_to_target(row)

    def find_target(self, engine: Engine, query: str) -> Optional[ResolvedTarget]:
        """Look up an already-resolved target by key, gene symbol or accession."""
        needle = (query or "").strip()
        if not needle:
            return None
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, target_key, name, organism, taxon_id, uniprot_accession,
                           gene_symbol, target_type, scope_kind, aliases, components,
                           source_name, dataset_version
                    FROM targets
                    WHERE lower(target_key) = lower(:q)
                       OR lower(coalesce(gene_symbol, '')) = lower(:q)
                       OR lower(coalesce(uniprot_accession, '')) = lower(:q)
                    ORDER BY (uniprot_accession IS NOT NULL) DESC
                    LIMIT 1
                    """
                ),
                {"q": needle},
            ).mappings().first()
        return _row_to_target(row) if row else None

    def list_targets(self, engine: Engine, limit: int = 100) -> list[ResolvedTarget]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, target_key, name, organism, taxon_id, uniprot_accession,
                           gene_symbol, target_type, scope_kind, aliases, components,
                           source_name, dataset_version
                    FROM targets
                    WHERE uniprot_accession IS NOT NULL
                    ORDER BY target_key
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return [_row_to_target(r) for r in rows]

    def latest_resolution(
        self, engine: Engine, target_id: uuid.UUID
    ) -> Optional[TargetResolutionRecord]:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, query, species, status, chosen_target_id, chosen_identifier,
                           candidates, excluded, source_name, source_version, notes,
                           retrieved_at
                    FROM target_resolutions
                    WHERE chosen_target_id = :tid
                    ORDER BY retrieved_at DESC
                    LIMIT 1
                    """
                ),
                {"tid": target_id},
            ).mappings().first()
        if row is None:
            return None
        return TargetResolutionRecord(
            id=row["id"],
            query=row["query"],
            species=row["species"],
            status=row["status"],
            chosen_target_id=row["chosen_target_id"],
            chosen_identifier=row["chosen_identifier"],
            candidates=[ResolutionCandidate(**c) for c in _as_json(row["candidates"]) or []],
            excluded=[ResolutionCandidate(**c) for c in _as_json(row["excluded"]) or []],
            source_name=row["source_name"],
            source_version=row["source_version"],
            retrieved_at=row["retrieved_at"],
            notes=list(_as_json(row["notes"]) or []),
        )


def _as_json(value):
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def _row_to_target(row) -> ResolvedTarget:
    return ResolvedTarget(
        id=row["id"],
        target_key=row["target_key"],
        name=row["name"],
        organism=row["organism"],
        taxon_id=row["taxon_id"],
        uniprot_accession=row["uniprot_accession"],
        gene_symbol=row["gene_symbol"],
        target_type=TargetType(row["target_type"]) if row["target_type"] else None,
        scope_kind=ScopeKind(row["scope_kind"]) if row["scope_kind"] else None,
        aliases=list(_as_json(row["aliases"]) or []),
        components=[TargetComponent(**c) for c in _as_json(row["components"]) or []],
        source_name=row["source_name"],
        dataset_version=row["dataset_version"],
    )


def _looks_like_accession(query: str) -> bool:
    """A UniProt accession is 6-10 alphanumerics with a digit pattern that a
    gene symbol does not have (e.g. Q969D9, P05231). Deterministic identifier
    parsing, not language interpretation (AGENTS.md §12)."""
    import re

    return bool(re.fullmatch(r"[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}", query.strip().upper()))


def taxon_for_species(species: str) -> Optional[int]:
    return species_taxon(species)
