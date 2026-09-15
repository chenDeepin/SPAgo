"""Deterministic modality classification (ONLINE-00).

Small molecules are the default result focus of a target investigation, so
biologics and unclassified entities must be *labelled* rather than silently
returned as inhibitors (online-llm plan §2 ONLINE-00 C).

Why this is not a source field lookup: ChEMBL reports `molecule_type:
"Small molecule"` for peptide ligands (observed 2026-09-15 on the TSLP
acceptance target), and molecular weight alone does not separate a cyclic
peptide from a natural product. Classification therefore combines the
source-declared type with deterministic RDKit structure rules, and the rule
that fired is recorded on the compound so the decision stays reviewable
(AGENTS.md §11/§10).

Nothing here is a filter by itself: callers decide what to show, and every
excluded record stays visible with its label.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional

from rdkit import Chem
from rdkit.Chem import Descriptors

from spago_core.chemistry.engine import StructureParseError, parse

# Amide-bond SMARTS: a carbonyl carbon bonded to a nitrogen (peptide backbone
# linkage, including N-methylated amides). Counted, never used as identity.
_AMIDE_SMARTS = "[CX3](=[OX1])[NX3]"
# Source-declared types that mean "not a small molecule" outright.
_BIOLOGIC_SOURCE_TYPES = {
    "protein",
    "antibody",
    "antibodies",
    "enzyme",
    "biotherapeutic",
    "oligonucleotide",
    "cell",
    "gene",
    "vaccine",
    "virus",
}
_OLIGO_SOURCE_TYPES = {"oligonucleotide", "oligosaccharide", "sirna", "antisense"}

# Documented thresholds. A 9-residue peptide observed on the TSLP target has
# 8 amide bonds and MW ~1.2 kDa; typical small-molecule leads stay well below
# both bounds.
PEPTIDE_AMIDE_MIN = 5
PEPTIDE_AMIDE_MW_MIN = 3
PEPTIDE_MW_MIN = 700.0
OLIGO_PHOSPHORUS_MIN = 3
OLIGO_MW_MIN = 800.0


class Modality(str, enum.Enum):
    SMALL_MOLECULE = "small_molecule"
    PEPTIDE = "peptide"
    OLIGONUCLEOTIDE = "oligonucleotide"
    BIOLOGIC = "biologic"
    UNCLASSIFIED = "unclassified"
    UNPARSEABLE = "unparseable"


#: Modalities that belong in the default small-molecule result view.
SMALL_MOLECULE_MODALITIES = frozenset({Modality.SMALL_MOLECULE, Modality.UNCLASSIFIED})


@dataclass(frozen=True)
class ModalityVerdict:
    modality: Modality
    rule: str
    source_declared: Optional[str] = None

    @property
    def is_small_molecule(self) -> bool:
        return self.modality in SMALL_MOLECULE_MODALITIES


def _amide_bonds(mol: Chem.Mol) -> int:
    pattern = Chem.MolFromSmarts(_AMIDE_SMARTS)
    if pattern is None:  # pragma: no cover - fixed SMARTS
        return 0
    return len(mol.GetSubstructMatches(pattern))


def structure_modality_rule(smiles: str) -> tuple[Modality, str, dict]:
    """Classify a parsed structure. Returns (modality, rule, counts)."""
    mol = parse(smiles)
    amides = _amide_bonds(mol)
    phosphorus = sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() == "P")
    mw = Descriptors.MolWt(mol)
    counts = {"amide_bonds": amides, "phosphorus_atoms": phosphorus, "molecular_weight": round(mw, 2)}

    if phosphorus >= OLIGO_PHOSPHORUS_MIN and mw >= OLIGO_MW_MIN:
        return Modality.OLIGONUCLEOTIDE, "phosphodiester_backbone", counts
    if amides >= PEPTIDE_AMIDE_MIN:
        return Modality.PEPTIDE, "amide_bond_count", counts
    if amides >= PEPTIDE_AMIDE_MW_MIN and mw >= PEPTIDE_MW_MIN:
        return Modality.PEPTIDE, "amide_bond_count_with_mass", counts
    return Modality.SMALL_MOLECULE, "default_small_molecule", counts


def classify_modality(
    smiles: Optional[str],
    source_declared: Optional[str] = None,
    source_biotherapeutic: bool = False,
    source_has_helm: bool = False,
) -> ModalityVerdict:
    """Combine the source-declared type with deterministic structure rules.

    A source that declares a biologic/oligonucleotide is trusted over the
    structure (a declared antibody may have no SMILES at all); a source that
    declares "Small molecule" is *not* trusted, because peptides are commonly
    reported that way. Unparseable structures stay unclassified instead of
    being assumed inert.
    """
    declared = (source_declared or "").strip().lower() or None
    if source_biotherapeutic or source_has_helm:
        return ModalityVerdict(Modality.BIOLOGIC, "source_biotherapeutic", declared)
    if declared in _OLIGO_SOURCE_TYPES:
        return ModalityVerdict(Modality.OLIGONUCLEOTIDE, "source_declared_type", declared)
    if declared in _BIOLOGIC_SOURCE_TYPES:
        return ModalityVerdict(Modality.BIOLOGIC, "source_declared_type", declared)

    if not smiles:
        return ModalityVerdict(
            Modality.BIOLOGIC if declared else Modality.UNCLASSIFIED,
            "no_structure",
            declared,
        )
    try:
        modality, rule, _counts = structure_modality_rule(smiles)
    except StructureParseError:
        return ModalityVerdict(Modality.UNPARSEABLE, "structure_unparseable", declared)
    return ModalityVerdict(modality, rule, declared)


def is_small_molecule(
    smiles: Optional[str],
    source_declared: Optional[str] = None,
    source_biotherapeutic: bool = False,
    source_has_helm: bool = False,
) -> bool:
    return classify_modality(
        smiles,
        source_declared=source_declared,
        source_biotherapeutic=source_biotherapeutic,
        source_has_helm=source_has_helm,
    ).is_small_molecule
