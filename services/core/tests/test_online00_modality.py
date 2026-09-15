"""ONLINE-00 C: deterministic modality classification and SMILES hygiene.

The scientific point: a source that reports a 9-residue peptide as
`molecule_type: "Small molecule"` (observed on ChEMBL for the TSLP acceptance
target, 2026-09-15) must not be presented as a small-molecule inhibitor. These
tests pin the classification rules, including the cases the rules deliberately
decline to classify.
"""
from __future__ import annotations

import pytest

from spago_core.chemistry import (
    Modality,
    classify_modality,
    clean_external_smiles,
    is_small_molecule,
    structure_modality_rule,
)

#: A real ChEMBL record for human TSLP (activity 18218879): 9 residues, and
#: reported by the source as a small molecule.
TSLP_PEPTIDE = (
    "CC(=O)N[C@@H](CCCNC(=N)N)C(=O)N[C@@H](C)C(=O)N[C@@H](C)C(=O)N"
    "[C@@H](Cc1cnc[nH]1)C(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)NCC(=O)N"
    "[C@@H](CC(C)C)C(=O)N[C@@H](CCC(=O)O)C(=O)N[C@@H](C)C(=O)O"
)

IMATINIB = "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1"
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
GLUTATHIONE = "NCC(=O)N[C@@H](CS)C(=O)N[C@@H](CCC(=O)O)C(=O)O"
OLIGONUCLEOTIDE = "O=P(O)(O)OCC1OC(n2cnc3c(N)ncnc32)C(O)C1OP(=O)(O)OCC1OC(n2cnc3c(N)ncnc32)C(O)C1OP(=O)(O)OCC1OC(n2cnc3c(N)ncnc32)C(O)C1O"


class TestStructureRules:
    def test_source_small_molecule_label_does_not_override_a_peptide_structure(self):
        verdict = classify_modality(TSLP_PEPTIDE, "Small molecule")
        assert verdict.modality is Modality.PEPTIDE
        assert verdict.rule == "amide_bond_count"
        assert verdict.source_declared == "small molecule"

    def test_drug_like_small_molecules_stay_small_molecules(self):
        for smiles in (IMATINIB, ASPIRIN):
            assert classify_modality(smiles).modality is Modality.SMALL_MOLECULE

    def test_short_peptide_like_amides_are_not_peptides_without_mass(self):
        # Glutathione has two amide bonds and MW 307: still a small molecule.
        verdict = structure_modality_rule(GLUTATHIONE)
        assert verdict[0] is Modality.SMALL_MOLECULE

    def test_oligonucleotide_backbone_is_recognised(self):
        verdict = classify_modality(OLIGONUCLEOTIDE, "Small molecule")
        assert verdict.modality is Modality.OLIGONUCLEOTIDE
        assert verdict.rule == "phosphodiester_backbone"

    def test_counts_are_reported_for_review(self):
        _modality, _rule, counts = structure_modality_rule(TSLP_PEPTIDE)
        assert counts["amide_bonds"] >= 5
        assert counts["molecular_weight"] > 700


class TestSourceDeclarations:
    def test_declared_biologic_outranks_an_absent_structure(self):
        verdict = classify_modality(None, "Protein")
        assert verdict.modality is Modality.BIOLOGIC
        assert verdict.rule == "source_declared_type"

    def test_biotherapeutic_flag_is_enough(self):
        assert classify_modality(None, None, source_biotherapeutic=True).modality is Modality.BIOLOGIC
        assert classify_modality("CC(=O)O", None, source_has_helm=True).modality is Modality.BIOLOGIC

    def test_declared_antibody_outranks_a_parsable_structure(self):
        assert classify_modality("CC(=O)O", "Antibody").modality is Modality.BIOLOGIC

    def test_missing_structure_without_a_declaration_is_unclassified_not_small(self):
        verdict = classify_modality(None)
        assert verdict.modality is Modality.UNCLASSIFIED
        # Unclassified stays in the default view but is labelled as such.
        assert verdict.is_small_molecule is True

    def test_unparseable_structure_is_labelled_not_assumed(self):
        verdict = classify_modality("this is not a smiles")
        assert verdict.modality is Modality.UNPARSEABLE
        assert verdict.rule == "structure_unparseable"

    def test_helper_matches_the_verdict(self):
        assert is_small_molecule(IMATINIB) is True
        assert is_small_molecule(TSLP_PEPTIDE) is False
        assert is_small_molecule(None, "Protein") is False


class TestExternalSmilesHygiene:
    def test_bindingdb_relative_stereo_marker_is_stripped_and_reported(self):
        cleaned, notes = clean_external_smiles(
            "Cc1ncccc1NC(=O)c1ccc2c(c1)C(=O)C[C@@H]1C[C@](O)(CC[C@@]21Cc1ccccc1)C(F)(F)F |r|"
        )
        assert cleaned.endswith("C(F)(F)F")
        assert "|r|" not in cleaned
        assert notes and "CXSMILES" in notes[0]

    def test_a_clean_smiles_is_returned_unchanged_with_no_notes(self):
        assert clean_external_smiles(" CC(=O)O ") == ("CC(=O)O", [])

    def test_a_stripped_structure_still_parses_and_keeps_stereochemistry(self):
        from spago_core.chemistry import normalize

        raw = "Cc1ncccc1NC(=O)c1ccc2c(c1)C(=O)C[C@@H]1C[C@](O)(CC[C@@]21Cc1ccccc1)C(F)(F)F |r|"
        cleaned, _ = clean_external_smiles(raw)
        norm = normalize(cleaned)
        assert norm.has_stereo is True
        assert norm.is_multi_component is False
