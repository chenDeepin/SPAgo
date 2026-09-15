"""ONLINE-06: publication-number normalization for source-declared identifiers.

The point: ChEMBL stores a patent id in its own formatting, the loaded corpus
stores SureChEMBL formatting (``US-5153197-A``), and a link between the two must
not depend on punctuation. The pattern is lenient on purpose, but it never
invents a number: a string without a country code and at least six digits is
reported as carrying none.
"""
from __future__ import annotations

from spago_core.domain.patent_numbers import (
    normalize_patent_number,
    patent_number_match,
    patent_tokens,
    unique_patent_numbers,
)


class TestExtraction:
    def test_chembl_style_patent_id(self):
        assert normalize_patent_number("WO2019047734A1") == "WO2019047734"

    def test_surechembl_style_publication_number(self):
        assert normalize_patent_number("US-5153197-A") == "US5153197"

    def test_spaced_and_slashed_forms_normalize_the_same(self):
        assert normalize_patent_number("WO 2019/047734") == "WO2019047734"
        assert normalize_patent_number("wo-2019-047734-a1") == "WO2019047734"

    def test_grouping_commas_are_punctuation(self):
        assert normalize_patent_number("US 10,123,456 B2") == "US10123456"

    def test_several_numbers_are_all_returned_in_order(self):
        tokens = patent_tokens("WO2019047734A1; US10123456B2")
        assert tokens == ["WO2019047734", "US10123456"]

    def test_short_or_absent_numbers_are_not_invented(self):
        assert normalize_patent_number("") == ""
        assert normalize_patent_number("not a patent") == ""
        assert normalize_patent_number("US12345") == ""      # body below the six-digit floor
        assert normalize_patent_number("1234567") == ""      # no country code
        # Synthetic demo identifiers must not be read as publication numbers.
        assert normalize_patent_number("DEMO-PATENT-A") == ""


class TestMatching:
    def test_kind_code_does_not_break_a_match(self):
        assert patent_number_match("WO2019047734A1", "WO-2019-047734-A1")
        assert patent_number_match("US-5153197-A", "US5153197B1")

    def test_different_publications_do_not_match(self):
        assert not patent_number_match("WO2019047734A1", "WO2019047735A1")
        assert not patent_number_match("", "WO2019047734A1")

    def test_unique_tokens_are_deduplicated_and_sorted(self):
        assert unique_patent_numbers(
            ["WO2019047734A1", "WO2019047734A2", None, "US10123456B2"]
        ) == ["US10123456", "WO2019047734"]
