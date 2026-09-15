"""ONLINE-06: deterministic potency classification.

The scientific point: "3 compounds, none better than 10 µM" and "3 compounds, one
at 4 nM" are different facts about a target, and the difference must come from a
stated rule rather than from a reader's eye. These tests pin the censor rules,
the unit handling, and the cases where the classifier deliberately declines to
classify (a kinetic constant or a percent readout is not a potency).
"""
from __future__ import annotations

import pytest

from spago_core.chemistry.activities import (
    ActivityClass,
    classify_activity,
    format_nanomolar,
    is_potency_endpoint,
    normalize_relation,
    normalize_unit,
    potency_label,
    to_nanomolar,
)

THRESHOLD = 10_000.0  # 10 µM


def cls(value, unit="nM", relation="=", standard_type="IC50", threshold=THRESHOLD):
    return classify_activity(value, unit, relation, standard_type, threshold)[0]


def rule(value, unit="nM", relation="=", standard_type="IC50", threshold=THRESHOLD):
    return classify_activity(value, unit, relation, standard_type, threshold)[1]


class TestUncensoredValues:
    def test_value_at_the_threshold_is_active(self):
        assert cls(10_000.0) is ActivityClass.ACTIVE

    def test_value_below_the_threshold_is_active(self):
        assert cls(4.0) is ActivityClass.ACTIVE

    def test_value_above_the_threshold_is_weak(self):
        assert cls(43_000.0) is ActivityClass.WEAK
        assert rule(43_000.0) == "value_above_threshold"

    def test_micromolar_value_is_converted_before_comparing(self):
        # 8 µM is below a 10 µM threshold; a unit-blind comparison would call it weak.
        assert cls(8.0, unit="µM") is ActivityClass.ACTIVE
        assert cls(8.0, unit="uM") is ActivityClass.ACTIVE
        assert cls(80.0, unit="µM") is ActivityClass.WEAK

    def test_picomolar_and_millimolar_units_convert(self):
        assert cls(5000.0, unit="pM") is ActivityClass.ACTIVE
        assert cls(5.0, unit="pM") is ActivityClass.ACTIVE
        assert cls(0.05, unit="mM") is ActivityClass.WEAK
        assert cls(0.005, unit="mM") is ActivityClass.ACTIVE

    def test_approximate_relation_is_treated_as_a_measurement(self):
        assert cls(4000.0, relation="~") is ActivityClass.ACTIVE


class TestCensoredValues:
    def test_upper_bound_at_or_below_threshold_is_active(self):
        # "<10 µM" asserts the true value is below the threshold.
        assert cls(10_000.0, relation="<") is ActivityClass.ACTIVE
        assert cls(1000.0, relation="<=") is ActivityClass.ACTIVE

    def test_upper_bound_above_threshold_cannot_be_decided(self):
        assert cls(50_000.0, relation="<") is ActivityClass.UNKNOWN
        assert rule(50_000.0, relation="<") == "upper_bound_above_threshold_cannot_be_decided"

    def test_lower_bound_at_or_above_threshold_is_weak(self):
        # ">10 µM" excludes activity at the threshold.
        assert cls(10_000.0, relation=">") is ActivityClass.WEAK
        assert cls(100_000.0, relation=">=") is ActivityClass.WEAK

    def test_lower_bound_below_threshold_cannot_be_decided(self):
        # ">5 µM" leaves the true value possibly below 10 µM.
        assert cls(5_000.0, relation=">") is ActivityClass.UNKNOWN
        assert rule(5_000.0, relation=">") == "lower_bound_below_threshold_cannot_be_decided"


class TestDeclinedClassifications:
    @pytest.mark.parametrize("endpoint", ["kon", "koff", "inhibition", "% inhibition", "ratio", ""])
    def test_non_potency_endpoints_are_not_applicable(self, endpoint):
        assert cls(50.0, standard_type=endpoint) is ActivityClass.NOT_APPLICABLE

    def test_kinetic_units_are_not_concentrations(self):
        assert cls(4.0, unit="1/s", standard_type="koff") is ActivityClass.NOT_APPLICABLE
        assert cls(50.0, unit="%") is ActivityClass.NOT_APPLICABLE

    def test_zero_or_negative_value_is_a_data_error_not_a_potent_compound(self):
        assert cls(0.0) is ActivityClass.NOT_APPLICABLE
        assert cls(-1.0) is ActivityClass.NOT_APPLICABLE
        assert rule(0.0) == "value_not_positive"

    def test_missing_threshold_disables_classification(self):
        assert cls(4.0, threshold=0) is ActivityClass.NOT_APPLICABLE

    def test_unknown_unit_is_not_assumed_to_be_nanomolar(self):
        assert cls(4.0, unit="µg/mL") is ActivityClass.NOT_APPLICABLE
        assert rule(4.0, unit="µg/mL") == "unit_not_a_concentration"


class TestHelpers:
    def test_unit_and_relation_normalization(self):
        assert normalize_unit(" µM ") == "um"
        assert normalize_unit("μM") == "um"
        assert normalize_unit(None) == ""
        assert normalize_relation("") == "="
        assert normalize_relation("<=") == "<"
        assert normalize_relation("≥") == ">"
        assert normalize_relation("~") == "~"

    def test_nanomolar_conversion(self):
        assert to_nanomolar(4, "nM") == 4
        assert to_nanomolar(4, "µM") == 4000
        assert to_nanomolar(4, "%") is None

    def test_potency_endpoint_list_is_narrow(self):
        assert is_potency_endpoint("IC50")
        assert is_potency_endpoint("kd")
        assert not is_potency_endpoint("kon")
        assert not is_potency_endpoint("inhibition")

    def test_threshold_formatting(self):
        assert format_nanomolar(10_000.0) == "10 µM"
        assert format_nanomolar(250.0) == "250 nM"
        assert format_nanomolar(0.05) == "50 pM"

    def test_potency_label_keeps_the_reported_unit(self):
        assert potency_label("IC50", 4.0, "nM") == "IC50 4 nM"
        assert potency_label("Ki", 10000.0, "nM", ">") == "KI >10000 nM"
