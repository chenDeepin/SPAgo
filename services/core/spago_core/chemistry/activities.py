"""Deterministic potency classification for a measurement (ONLINE-06).

Why this exists
---------------
A stored measurement answers "what was reported"; it does not answer "does this
target have a usable starting point?". Those are different questions, and the
second one has a deterministic answer that must not be left to a model or to a
reader's eye: a compound is *active* only when its reported value supports a
value at or below an explicit threshold, *weak* when the report excludes that,
and *unknown* when the censoring or the endpoint does not decide either way.

This is deliberately **not** a ranking or a selectivity number. Values from
different endpoint types are never compared, and nothing here changes a stored
value: the class is a property of one measurement under one stated policy, and
it is recomputed from the stored row rather than persisted, so a threshold
change can never leave a stale class behind (AGENTS.md §10/§11).

Rules (each branch is a statement about the *true* value implied by the report):

===========================  ==================================================
report                       class
===========================  ==================================================
``= v``, ``~ v``, v ≤ T      active            (measured at or below threshold)
``= v``, ``~ v``, v > T      weak              (measured above threshold)
``< v``, v ≤ T               active            (true value is below an upper bound)
``< v``, v > T               unknown           (true value may still be ≤ T)
``> v``, v ≥ T               weak              (true value exceeds the threshold)
``> v``, v < T               unknown           (true value may still be ≤ T)
non-potency endpoint         not_applicable    (e.g. kon, koff, % inhibition)
non-concentration unit       not_applicable    (e.g. %, ratio, µg/mL is not potency)
non-finite / non-positive    not_applicable    (a 0 nM IC50 is a data error)
===========================  ==================================================

The potency-endpoint list is intentionally narrower than the affinity/kinetic
list in :mod:`spago_core.adapters.chembl_discovery`: a kinetic constant or a
percent readout is real data, but it is not a potency, and calling it "active"
would be exactly the kind of silent upgrade AGENTS.md forbids.

Provenance: the classification semantics (censored values, a single explicit
threshold, a deterministic reason string) are adapted from the author's local
``BindingDB_IO`` project (``bindingdb_io/activity.py``), reviewed 2026-09-15.
The unit handling is new here because SPAgo stores the unit a source reported
instead of converting on ingest.
"""
from __future__ import annotations

import enum
import math
from typing import Optional

#: Unit → factor that converts the value to nanomolar. Keys are lower-cased and
#: µ/μ are folded to "u" before lookup. A unit that is not a concentration is
#: absent on purpose: absence means "not a potency", never "assume nM".
CONCENTRATION_UNITS: dict[str, float] = {
    "nm": 1.0,
    "nanomolar": 1.0,
    "um": 1_000.0,
    "micromolar": 1_000.0,
    "mm": 1_000_000.0,
    "millimolar": 1_000_000.0,
    "pm": 1e-3,
    "picomolar": 1e-3,
    "fm": 1e-6,
    "femtomolar": 1e-6,
    "m": 1e9,
    "molar": 1e9,
}

#: Endpoint types whose value is a concentration that can be compared with a
#: potency threshold. Kinetic constants (kon/koff), percent-effect readouts and
#: ratios are absent deliberately (see the module docstring).
POTENCY_ENDPOINTS: frozenset[str] = frozenset(
    {
        "ic50",
        "ic 50",
        "ki",
        "kd",
        "ec50",
        "ec 50",
        "ac50",
        "potency",
        "kd_app",
        "ki_app",
        "apparent kd",
        "apparent ki",
        "dissociation constant",
        "inhibition constant",
    }
)

#: Default reference threshold: 10 µM. A compound measured weaker than this is
#: still stored (it is counter-evidence); it is not a starting point.
DEFAULT_THRESHOLD_NM = 10_000.0

#: A set that fails the gate is described as sparse when it holds at most this
#: many compounds. Like the source project's ``--min-compounds``, it shapes the
#: *reason* only: a single potent compound still qualifies.
DEFAULT_MIN_COMPOUNDS = 10


class ActivityClass(str, enum.Enum):
    """What one reported measurement implies under the stated threshold."""

    ACTIVE = "active"
    WEAK = "weak"
    UNKNOWN = "unknown"
    #: The endpoint or the unit is not a potency, so no class applies.
    NOT_APPLICABLE = "not_applicable"


def normalize_unit(unit: Optional[str]) -> str:
    """Fold a reported unit to its lookup key (case, µ/μ, spaces)."""
    text = (unit or "").strip().lower().replace("µ", "u").replace("μ", "u")
    return text.replace(" ", "")


def normalize_relation(relation: Optional[str]) -> str:
    """Fold a reported relation to one of ``= < > ~``.

    ``<=`` becomes ``<`` and ``>=`` becomes ``>``: the *censor direction* is what
    the classification needs, and a strict reading of a non-strict bound is the
    conservative one (``<=10 µM`` under a 10 µM threshold reads as "at most",
    which is the active case anyway).
    """
    text = (relation or "").strip()
    if not text or text == "=":
        return "="
    if text in {"<", "<=", "≤", "≦"}:
        return "<"
    if text in {">", ">=", "≥", "≧"}:
        return ">"
    if text in {"~", "≈"}:
        return "~"
    return "="


def is_potency_endpoint(standard_type: Optional[str]) -> bool:
    return (standard_type or "").strip().lower() in POTENCY_ENDPOINTS


def to_nanomolar(value: float, unit: Optional[str]) -> Optional[float]:
    """Convert a reported value to nM, or None when the unit is not a concentration."""
    factor = CONCENTRATION_UNITS.get(normalize_unit(unit))
    if factor is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric * factor


def classify_activity(
    value: float,
    unit: Optional[str],
    relation: Optional[str] = "=",
    standard_type: Optional[str] = None,
    threshold_nm: float = DEFAULT_THRESHOLD_NM,
) -> tuple[ActivityClass, str]:
    """Classify one measurement. Returns ``(class, rule)``.

    The rule string is stored with the class in API responses so a reader can see
    *why* a value was called active, and it is stable enough to assert on.
    """
    if threshold_nm is None or threshold_nm <= 0:
        return ActivityClass.NOT_APPLICABLE, "no_threshold"
    if not is_potency_endpoint(standard_type):
        return ActivityClass.NOT_APPLICABLE, "endpoint_not_a_potency"

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ActivityClass.NOT_APPLICABLE, "value_not_numeric"
    if not math.isfinite(numeric) or numeric <= 0:
        return ActivityClass.NOT_APPLICABLE, "value_not_positive"

    nm = to_nanomolar(numeric, unit)
    if nm is None:
        return ActivityClass.NOT_APPLICABLE, "unit_not_a_concentration"

    rel = normalize_relation(relation)
    if rel == "<":
        if nm <= threshold_nm:
            return ActivityClass.ACTIVE, "upper_bound_at_or_below_threshold"
        return ActivityClass.UNKNOWN, "upper_bound_above_threshold_cannot_be_decided"
    if rel == ">":
        if nm >= threshold_nm:
            return ActivityClass.WEAK, "lower_bound_at_or_above_threshold"
        return ActivityClass.UNKNOWN, "lower_bound_below_threshold_cannot_be_decided"
    if nm <= threshold_nm:
        return ActivityClass.ACTIVE, "value_at_or_below_threshold"
    return ActivityClass.WEAK, "value_above_threshold"


def format_nanomolar(value_nm: float) -> str:
    """Human-readable threshold/value: ``10 µM``, ``250 nM``, ``0.5 nM``."""
    if value_nm >= 1_000:
        return f"{value_nm / 1000:g} µM"
    if value_nm < 0.1:
        return f"{value_nm * 1000:g} pM"
    return f"{value_nm:g} nM"


def potency_label(
    standard_type: Optional[str],
    value: float,
    unit: Optional[str],
    relation: Optional[str] = "=",
) -> str:
    """As-reported label, e.g. ``IC50 4 nM`` / ``Ki >10000 nM``.

    The value is shown in the unit the source reported (never silently
    converted) so the label always matches the evidence panel.
    """
    endpoint = (standard_type or "").strip() or "value"
    rel = normalize_relation(relation)
    prefix = "" if rel == "=" else ("<" if rel == "<" else ">" if rel == ">" else "~")
    try:
        shown = f"{float(value):g}"
    except (TypeError, ValueError):
        shown = str(value)
    return f"{endpoint.upper()} {prefix}{shown} {unit or ''}".strip()
