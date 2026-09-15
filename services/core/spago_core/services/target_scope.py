"""Reviewed ligand/receptor/pathway scope for the acceptance targets.

The plan requires the resolver to *offer* receptor/pathway expansion explicitly
rather than folding it in silently (online-llm plan §2 ONLINE-00 A). Membership
cannot be derived from a protein record alone — UniProt does not state "TSLP's
receptor is CRLF2" as a machine-readable relation — so the mapping is curated,
versioned with the code, and carries its sources.

Rules this module enforces:

- Systems are looked up by requested target, and each member is returned with
  its role and the note explaining why it is *not* interchangeable with the
  requested target.
- The list is data, not code: adding a target means adding a reviewed entry,
  not adding a keyword branch.
- Expansion is opt-in at the API level (`include_related`), and anything
  returned from an expansion is labelled as related, never as the requested
  target.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "target_scopes.json"


class ScopeMember(BaseModel):
    accession: str
    name: str
    gene_symbol: str
    role: str
    organism: str
    note: str = ""


class ScopeSystem(BaseModel):
    system_key: str
    label: str
    notes: str = ""
    members: list[ScopeMember] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class TargetScopeCatalog(BaseModel):
    reviewed_on: str
    purpose: str
    disclaimer: str
    systems: list[ScopeSystem] = Field(default_factory=list)
    positive_controls: list[ScopeSystem] = Field(default_factory=list)

    def all_systems(self) -> list[ScopeSystem]:
        return [*self.systems, *self.positive_controls]

    def system_for(self, identifier: str) -> ScopeSystem | None:
        """Find the system containing an accession, gene symbol or system key."""
        needle = (identifier or "").strip().lower()
        if not needle:
            return None
        for system in self.all_systems():
            if system.system_key.lower() == needle:
                return system
            for member in system.members:
                if member.accession.lower() == needle or member.gene_symbol.lower() == needle:
                    return system
        return None

    def member_for(self, identifier: str) -> ScopeMember | None:
        needle = (identifier or "").strip().lower()
        for system in self.all_systems():
            for member in system.members:
                if member.accession.lower() == needle or member.gene_symbol.lower() == needle:
                    return member
        return None

    def related_members(self, identifier: str) -> list[tuple[ScopeMember, str]]:
        """Members of the same system other than the one identified.

        Returns (member, reason) pairs; the reason states the relationship and
        the caveat, so the caller never presents a partner as the same target.
        """
        system = self.system_for(identifier)
        if system is None:
            return []
        primary = self.member_for(identifier)
        related: list[tuple[ScopeMember, str]] = []
        for member in system.members:
            if primary is not None and member.accession == primary.accession:
                continue
            related.append(
                (
                    member,
                    f"{member.role} in the {system.label}; {member.note}".strip(),
                )
            )
        return related


class ScopeCatalogUnavailable(RuntimeError):
    """The reviewed scope catalog could not be read.

    Raised rather than returning an empty catalog silently: an empty catalog
    would look like "no reviewed expansion exists for this target", which is a
    different and misleading fact. Callers decide how to degrade, and record
    what they decided.
    """


@lru_cache
def load_catalog(path: Path | None = None) -> TargetScopeCatalog:
    target = path or DATA_PATH
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError as exc:
        raise ScopeCatalogUnavailable(
            f"Reviewed target-scope catalog not found at {target}. The installed package "
            "must include its data files (see services/core/pyproject.toml package-data)."
        ) from exc
    return TargetScopeCatalog.model_validate(data)


def try_load_catalog(path: Path | None = None) -> tuple[TargetScopeCatalog, str | None]:
    """Load the catalog, or return an empty one with the reason it was unusable.

    Used on the request path so a deployment problem degrades to "no offered
    partner expansion" with an explicit note, instead of failing the whole
    resolution.
    """
    try:
        return load_catalog(path), None
    except (ScopeCatalogUnavailable, ValueError) as exc:
        empty = TargetScopeCatalog(
            reviewed_on="unavailable",
            purpose="catalog unavailable",
            disclaimer="No reviewed ligand/receptor/pathway mapping was loaded.",
        )
        return empty, str(exc)
