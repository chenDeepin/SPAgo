"""Shared compound identity and persistence.

Every path that introduces a structure into SPAgo — patent ingestion, open-database
discovery, a user-added literature row — must produce the *same* compound for the same
structure. Identity therefore lives in one place: the InChIKey namespace below, plus
the single upsert that fills a compound row and lets the RDKit cartridge derive the
descriptors (AGENTS.md §11: chemistry stays deterministic, and one structure is one
compound).

The module is deliberately free of adapter and HTTP imports so any service can use it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from spago_core.chemistry import Modality, NormalizedStructure
from spago_core.services.targets import TARGET_NAMESPACE

#: Same namespace as the patent ingestion path, so a compound discovered from ChEMBL
#: and seen in a patent is one compound.
COMPOUND_NAMESPACE = TARGET_NAMESPACE


def compound_id_for_inchikey(inchikey: str) -> uuid.UUID:
    """The global identity of a structure, derived from its InChIKey."""
    return uuid.uuid5(COMPOUND_NAMESPACE, "compound:" + inchikey)


@dataclass
class CandidateStructure:
    """A structure as RDKit normalized it, plus its deterministic modality.

    The whole `NormalizedStructure` travels with the candidate: writing only a subset
    (as an earlier revision did) stored `has_stereo = false` for structures that have
    specified stereocentres, which the ONLINE-05 evaluation caught by re-deriving the
    flag from the stored SMILES.
    """

    raw_smiles: str
    structure: NormalizedStructure
    modality: Modality
    modality_rule: str
    modality_source: str
    scaffold: Optional[str]

    @property
    def canonical_smiles(self) -> str:
        return self.structure.canonical_smiles

    @property
    def inchikey(self) -> str:
        return self.structure.inchikey


def persist_compounds(conn, normalized: dict[str, CandidateStructure]) -> tuple[int, int]:
    """Insert or reuse one compounds row per structure. Returns (stored, reused)."""
    stored = 0
    reused = 0
    for candidate in normalized.values():
        compound_id = compound_id_for_inchikey(candidate.inchikey)
        existing = conn.execute(
            text("SELECT 1 FROM compounds WHERE inchikey = :k"), {"k": candidate.inchikey}
        ).first()
        if existing:
            reused += 1
            # Modality is deterministic from the canonical structure, so an
            # external classification may refine a patent-derived "unclassified"
            # label but never downgrade a definite one.
            conn.execute(
                text(
                    """
                    UPDATE compounds
                    SET modality = CASE
                            WHEN modality IS NULL OR modality IN ('unclassified','unparseable')
                            THEN :modality ELSE modality END,
                        modality_rule = CASE
                            WHEN modality IS NULL OR modality IN ('unclassified','unparseable')
                            THEN :rule ELSE modality_rule END,
                        modality_source = CASE
                            WHEN modality IS NULL OR modality IN ('unclassified','unparseable')
                            THEN :source ELSE modality_source END
                    WHERE inchikey = :k
                    """
                ),
                {
                    "modality": candidate.modality.value,
                    "rule": candidate.modality_rule,
                    "source": candidate.modality_source,
                    "k": candidate.inchikey,
                },
            )
            continue
        norm = candidate.structure
        conn.execute(
            text(
                """
                INSERT INTO compounds (id, canonical_smiles, inchikey, inchi,
                                       molecular_formula, molecular_weight, hbd, hba,
                                       tpsa, logp, has_stereo, is_multi_component,
                                       scaffold, modality, modality_rule,
                                       modality_source, dataset_version, m)
                VALUES (:id, :canonical_smiles, :inchikey, :inchi,
                        :formula, :mw, :hbd, :hba,
                        :tpsa, :logp, :has_stereo, :multi_component,
                        :scaffold, :modality, :rule, :source, :dataset_version,
                        mol_from_smiles(:canonical_smiles))
                ON CONFLICT (inchikey) DO NOTHING
                """
            ),
            {
                "id": compound_id,
                "canonical_smiles": norm.canonical_smiles,
                "inchikey": norm.inchikey,
                "inchi": norm.inchi,
                "formula": norm.molecular_formula,
                "mw": norm.molecular_weight,
                "hbd": norm.hbd,
                "hba": norm.hba,
                "tpsa": norm.tpsa,
                "logp": norm.logp,
                "has_stereo": norm.has_stereo,
                "multi_component": norm.is_multi_component,
                "scaffold": candidate.scaffold,
                "modality": candidate.modality.value,
                "rule": candidate.modality_rule,
                "source": candidate.modality_source,
                "dataset_version": "external:open-databases",
            },
        )
        stored += 1
    # Descriptors and InChI are filled in SQL by the RDKit cartridge, so
    # external compounds carry exactly the same chemistry columns as
    # patent-derived ones. Function names verified against cartridge
    # 4.2.0: mol_inchi / mol_formula / mol_amw / mol_hbd / mol_hba /
    # mol_tpsa / mol_logp.
    if normalized:
        conn.execute(
            text(
                """
                UPDATE compounds c SET
                    inchi = mol_inchi(m),
                    molecular_formula = NULLIF(mol_formula(m)::text, ''),
                    molecular_weight = round(mol_amw(m)::numeric, 2)::float8,
                    hbd = mol_hbd(m),
                    hba = mol_hba(m),
                    tpsa = round(mol_tpsa(m)::numeric, 1)::float8,
                    logp = round(mol_logp(m)::numeric, 2)::float8
                WHERE c.m IS NOT NULL
                  AND c.inchikey = ANY(:keys)
                  AND (c.inchi IS NULL OR c.molecular_formula IS NULL
                       OR c.molecular_weight IS NULL)
                """
            ),
            {"keys": [c.inchikey for c in normalized.values()]},
        )
    return stored, reused
