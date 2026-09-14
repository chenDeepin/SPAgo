"""Deterministic chemistry via RDKit (AGENTS.md §11).

All chemical identity decisions (canonicalization, InChIKey, depictions) happen
here, never in LLM output or client code. Malformed input is returned as a
recorded issue, never silently dropped or coerced.
"""
from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

# Fixture/adapters may hold intentionally malformed rows; RDKit's stderr noise is
# replaced by our structured issue records.
RDLogger.DisableLog("rdApp.warning")
RDLogger.DisableLog("rdApp.error")


class StructureParseError(ValueError):
    """Raised when a SMILES cannot be parsed; callers must record it as an issue."""


@dataclass(frozen=True)
class NormalizedStructure:
    canonical_smiles: str
    inchikey: str
    inchi: str
    molecular_formula: str
    molecular_weight: float
    hbd: int
    hba: int
    tpsa: float
    logp: float
    has_stereo: bool
    is_multi_component: bool


def parse(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        raise StructureParseError(f"RDKit failed to parse SMILES: {smiles!r}")
    return mol


def normalize(smiles: str) -> NormalizedStructure:
    """Canonicalize a structure and compute identity + descriptors.

    Stereochemistry is preserved (isomeric canonical SMILES and InChIKey);
    multi-component records (salts) stay multi-component at M0.
    """
    mol = parse(smiles)
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    canonical = Chem.MolToSmiles(mol, isomericSmiles=True)
    inchi = Chem.MolToInchi(mol)
    if not inchi:
        raise StructureParseError(f"RDKit produced no InChI for SMILES: {smiles!r}")
    inchikey = Chem.MolToInchiKey(mol)
    if not inchikey:
        raise StructureParseError(f"RDKit produced no InChIKey for SMILES: {smiles!r}")

    has_stereo = _has_specified_stereo(mol)
    frags = Chem.GetMolFrags(mol)

    return NormalizedStructure(
        canonical_smiles=canonical,
        inchikey=inchikey,
        inchi=inchi,
        molecular_formula=Chem.rdMolDescriptors.CalcMolFormula(mol),
        molecular_weight=round(Descriptors.MolWt(mol), 2),
        hbd=Lipinski.NumHDonors(mol),
        hba=Lipinski.NumHAcceptors(mol),
        tpsa=round(Descriptors.TPSA(mol), 1),
        logp=round(Crippen.MolLogP(mol), 2),
        has_stereo=has_stereo,
        is_multi_component=len(frags) > 1,
    )


def _has_specified_stereo(mol: Chem.Mol) -> bool:
    centers = Chem.FindMolChiralCenters(mol, includeUnassigned=False, includeCIP=False)
    if centers:
        return True
    for bond in mol.GetBonds():
        if bond.GetStereo() in (Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOZ, Chem.BondStereo.STEREOCIS, Chem.BondStereo.STEREOTRANS):
            return True
    return False


def depict_svg(smiles: str, width: int = 280, height: int = 160) -> str:
    """Render a 2D depiction as SVG. Coordinates are recomputed per request;
    callers are expected to cache the result (AGENTS.md §14)."""
    mol = parse(smiles)
    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = drawer.drawOptions()
    opts.padding = 0.12
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def murcko_scaffold(smiles: str) -> str:
    """Canonical SMILES of the Bemis-Murcko scaffold (deterministic, RDKit)."""
    from rdkit.Chem.Scaffolds import MurckoScaffold

    mol = parse(smiles)
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    return Chem.MolToSmiles(scaffold)


def chemistry_ok() -> bool:
    """Sanity check used by /healthz."""
    try:
        return normalize("CC(=O)Oc1ccccc1C(=O)O").inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    except StructureParseError:
        return False
