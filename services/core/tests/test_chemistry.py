"""Chemistry correctness tests (real RDKit, no mocks — AGENTS.md §27/§28)."""
from __future__ import annotations

import pytest

from spago_core.chemistry import (
    StructureParseError,
    chemistry_ok,
    depict_svg,
    normalize,
)


def test_identical_molecule_different_smiles_same_identity():
    a = normalize("CC(=O)Oc1ccccc1C(=O)O")
    b = normalize("O=C(O)c1ccccc1OC(C)=O")
    assert a.inchikey == b.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert a.canonical_smiles == b.canonical_smiles


def test_tautomer_writing_converges_to_same_inchikey():
    # Two common tautomer-style writings of caffeine.
    a = normalize("Cn1c(=O)c2c(ncn2C)n(C)c1=O")
    b = normalize("Cn1cnc2c1c(=O)n(C)c(=O)n2C")
    assert a.inchikey == b.inchikey


def test_stereoisomers_are_distinct_compounds():
    racemic = normalize("CC(C)Cc1ccc(cc1)C(C)C(=O)O")
    single = normalize("CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O")
    assert racemic.inchikey != single.inchikey
    assert single.has_stereo is True
    assert racemic.has_stereo is False
    # Stereochemistry must survive canonicalization.
    assert "@" in single.canonical_smiles


def test_salt_is_multi_component_and_distinct_from_parent():
    salt = normalize("[Na+].O=C([O-])c1ccccc1O")
    parent = normalize("O=C(O)c1ccccc1O")
    assert salt.is_multi_component is True
    assert parent.is_multi_component is False
    assert salt.inchikey != parent.inchikey


def test_malformed_smiles_raises_recordable_error():
    with pytest.raises(StructureParseError):
        normalize("N=C(N)this-is-not-valid-smiles")
    with pytest.raises(StructureParseError):
        normalize("")
    with pytest.raises(StructureParseError):
        normalize("C1CC2")  # unclosed ring


def test_descriptors_are_computed():
    n = normalize("CC(=O)Oc1ccccc1C(=O)O")
    assert n.molecular_formula == "C9H8O4"
    assert 180.0 < n.molecular_weight < 181.0
    assert n.hbd == 1
    assert n.hba == 3  # includes the amide/amino O/N acceptor set per RDKit definition
    assert n.tpsa > 50
    assert 0 < n.logp < 3


def test_depiction_is_svg():
    svg = depict_svg("CC(=O)Oc1ccccc1C(=O)O", width=200, height=120)
    assert svg.lstrip().startswith("<?xml")
    assert "<svg" in svg


def test_chemistry_health_check():
    assert chemistry_ok() is True
