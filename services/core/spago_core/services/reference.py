"""Potency-reference verdict for a target (ONLINE-06).

Answers one question deterministically: *can this target's retrieved compound
set serve as a potency reference, and if not, why not?*

    "3 compounds, none better than 10 µM"  and  "3 compounds, best 4 nM"

are different facts, and the difference must not be left to a reader's eye or
to a model's paraphrase. The verdict is:

- **Computed from stored rows, never persisted.** The class of a measurement is
  a property of that measurement under one stated policy; storing it would let a
  threshold change leave a stale `active` behind (AGENTS.md §10).
- **Deterministic.** :mod:`spago_core.chemistry.activities` owns the rule; this
  module only counts.
- **Explicit about scope.** The default scope is small molecules and
  unclassified entities (the same labelled filter the candidate table uses), and
  potency actives that the scope excludes are *counted and reported*, never
  dropped.
- **Explicit about gaps.** Records that carried a value but no public structure
  (from the per-source retrieval records) are reported next to the counts, so a
  thin set is not read as a negative result (AGENTS.md §12/§22).

The verdict is a count, not a biological conclusion and not a claim about the
literature: `qualifies` means "at least one in-scope compound was reported at or
below the threshold", nothing more.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.chemistry.activities import (
    ActivityClass,
    DEFAULT_MIN_COMPOUNDS,
    DEFAULT_THRESHOLD_NM,
    classify_activity,
    format_nanomolar,
    potency_label,
    to_nanomolar,
)
from spago_core.chemistry.modality import Modality
from spago_core.domain import (
    ActiveCompound,
    EvidenceClass,
    ReferencePolicy,
    ReferenceVerdict,
)

#: Policy version travels with every verdict and every export, so an artifact
#: can be read back against the rule that produced it (AGENTS.md §25).
ACTIVITY_POLICY_VERSION = "potency-gate-v1"

#: Compounds shown in the verdict's `actives` list (the headline evidence).
MAX_ACTIVE_DETAILS = 5

#: Hard bound on measurement rows one verdict reads. Exceeding it is reported
#: as `truncated` instead of silently producing counts from a partial set.
MAX_VERDICT_MEASUREMENTS = 5000

#: Hard bound on the measurement rows read for one candidate page.
MAX_CANDIDATE_ROWS = 5000

#: Modality scope of the default verdict. Same set as the candidate table's
#: default filter, so the two never disagree about what is being counted. A
#: policy with `all_modalities` set counts every modality instead.
SCOPED_MODALITIES = {Modality.SMALL_MOLECULE.value, Modality.UNCLASSIFIED.value}

#: Rejection reasons that mean "the source reported a value without a structure
#: SPAgo can draw" — reported in the verdict so a thin set is not read as a
#: negative result.
_STRUCTURELESS_REJECTIONS = ("missing_structure", "unparseable_structure")

_CLASS_RANK = {
    ActivityClass.ACTIVE: 0,
    ActivityClass.WEAK: 1,
    ActivityClass.UNKNOWN: 2,
    ActivityClass.NOT_APPLICABLE: 3,
}

_EVIDENCE_CLASSES = {member.value for member in EvidenceClass}
_INFINITY = float("inf")


@dataclass(frozen=True)
class _ClassifiedRow:
    """One measurement with the class its own report supports."""

    measurement_id: uuid.UUID
    target_id: uuid.UUID
    compound_id: uuid.UUID
    inchikey: str
    modality: str
    standard_type: str
    value: float
    unit: str
    relation: str
    evidence_class: str
    source_name: str
    potential_duplicate: bool
    document_patent_number: Optional[str]
    activity_class: ActivityClass
    rule: str
    value_nm: Optional[float]

    @property
    def in_scope(self) -> bool:
        """Whether the *default* modality scope counts this row.

        The policy decides: a verdict computed with `all_modalities` counts every
        row, which is why the callers below use `_in_scope(row, policy)` and not
        this property directly.
        """
        return self.modality in SCOPED_MODALITIES

    @property
    def sort_key(self) -> tuple:
        return (
            self.value_nm if self.value_nm is not None else _INFINITY,
            str(self.measurement_id),
        )

    def as_active(self) -> ActiveCompound:
        return ActiveCompound(
            compound_id=self.compound_id,
            inchikey=self.inchikey,
            potency_label=self.label(),
            standard_type=self.standard_type,
            value=self.value,
            unit=self.unit,
            relation=self.relation,
            value_nm=self.value_nm or 0.0,
            evidence_class=(
                EvidenceClass(self.evidence_class)
                if self.evidence_class in _EVIDENCE_CLASSES
                else EvidenceClass.UNSPECIFIED
            ),
            source_name=self.source_name,
            measurement_id=self.measurement_id,
            potential_duplicate=self.potential_duplicate,
        )

    def label(self) -> str:
        return potency_label(self.standard_type, self.value, self.unit, self.relation)


def policy_from_settings(
    settings,
    *,
    threshold_nm: Optional[float] = None,
    min_compounds: Optional[int] = None,
    include_all_modalities: bool = False,
) -> ReferencePolicy:
    """Build the stated rule from deployment settings with request overrides.

    An override is validated by the API layer; this function only applies it, so
    a caller cannot end up classifying under a different rule than the response
    reports.
    """
    configured_threshold = float(
        getattr(settings, "activity_threshold_nm", DEFAULT_THRESHOLD_NM)
        or DEFAULT_THRESHOLD_NM
    )
    threshold = float(threshold_nm) if threshold_nm is not None else configured_threshold
    minimum = (
        int(min_compounds)
        if min_compounds is not None
        else int(getattr(settings, "activity_min_compounds", DEFAULT_MIN_COMPOUNDS))
    )
    scope = (
        "all modalities" if include_all_modalities
        else "small molecules and unclassified entities"
    )
    note = (
        "Counted over every modality the source returned."
        if include_all_modalities
        else (
            "Counted over small molecules and unclassified entities. Peptides, "
            "oligonucleotides and biologics are excluded from the counts, and their "
            "actives, if any, are reported separately."
        )
    )
    return ReferencePolicy(
        version=ACTIVITY_POLICY_VERSION,
        threshold_nm=threshold,
        threshold_label=format_nanomolar(threshold),
        min_compounds=minimum,
        all_modalities=include_all_modalities,
        modality_scope=scope,
        scope_note=note,
    )


def _rows(
    engine: Engine,
    target_ids: Optional[Sequence[uuid.UUID]],
    cap: int,
    compound_ids: Optional[Sequence[uuid.UUID]] = None,
) -> tuple[list[dict], bool]:
    """Measurement rows in candidate scope, bounded, with their owning target.

    Scope is `investigation_measurements`: the investigated target plus the
    interaction/complex targets the retrieval went through, minus retracted rows.
    A measurement of the same compound against an unrelated target is *not* in
    this target's verdict, drawer or export (migration 0015).
    """
    params: dict = {"cap": cap + 1}
    scope = ""
    if target_ids is not None:
        ids = list(target_ids)
        if not ids:
            return [], False
        scope += " AND m.investigation_target_id = ANY(:tids)"
        params["tids"] = ids
    if compound_ids is not None:
        ids = list(compound_ids)
        if not ids:
            return [], False
        scope += " AND m.compound_id = ANY(:cids)"
        params["cids"] = ids
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT
                       m.investigation_target_id AS target_id,
                       m.id AS measurement_id,
                       m.compound_id,
                       c.inchikey,
                       coalesce(c.modality, 'unclassified') AS modality,
                       m.standard_type, m.value, m.unit, m.relation,
                       coalesce(m.evidence_class, 'unspecified') AS evidence_class,
                       m.source_name, m.potential_duplicate,
                       m.document_patent_number
                FROM investigation_measurements m
                JOIN compounds c ON c.id = m.compound_id
                WHERE TRUE {scope}
                ORDER BY m.investigation_target_id, m.id
                LIMIT :cap
                """
            ),
            params,
        ).mappings().all()
    truncated = len(rows) > cap
    return [dict(row) for row in rows[:cap]], truncated


def _classify(rows: Iterable[dict], policy: ReferencePolicy) -> list[_ClassifiedRow]:
    classified: list[_ClassifiedRow] = []
    for row in rows:
        value = float(row["value"])
        unit = row["unit"]
        relation = row["relation"]
        standard_type = row["standard_type"]
        activity_class, rule = classify_activity(
            value, unit, relation, standard_type, policy.threshold_nm
        )
        classified.append(
            _ClassifiedRow(
                measurement_id=row["measurement_id"],
                target_id=row["target_id"],
                compound_id=row["compound_id"],
                inchikey=row["inchikey"],
                modality=row["modality"] or "",
                standard_type=standard_type,
                value=value,
                unit=unit,
                relation=relation,
                evidence_class=row["evidence_class"],
                source_name=row["source_name"],
                potential_duplicate=bool(row["potential_duplicate"]),
                document_patent_number=row["document_patent_number"],
                activity_class=activity_class,
                rule=rule,
                value_nm=to_nanomolar(value, unit),
            )
        )
    return classified


def _best_per_compound(rows: Sequence[_ClassifiedRow]) -> dict[uuid.UUID, _ClassifiedRow]:
    """The strongest class each compound's own records support.

    The class is the *claim* (active beats weak beats unknown); the row kept for
    a class is the most potent report of it, so the label a reader sees is the
    best evidence behind the claim, and ties break on the measurement id so the
    output is stable.
    """
    best: dict[uuid.UUID, _ClassifiedRow] = {}
    for row in rows:
        current = best.get(row.compound_id)
        if current is None:
            best[row.compound_id] = row
            continue
        if _CLASS_RANK[row.activity_class] < _CLASS_RANK[current.activity_class]:
            best[row.compound_id] = row
            continue
        if _CLASS_RANK[row.activity_class] == _CLASS_RANK[current.activity_class]:
            if row.sort_key < current.sort_key:
                best[row.compound_id] = row
    return best


def _counts(values: Iterable[Optional[str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = value or "unspecified"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda item: (-item[1], item[0])))


def _reason(
    *,
    policy: ReferencePolicy,
    compounds: int,
    actives: int,
    weak: int,
    unknown: int,
    not_applicable: int,
    measurements: int,
    records_without_structure: int,
    actives_outside_scope: int,
    truncated: bool,
    supplement_remarks: int = 0,
    withdrawn_supplements: int = 0,
) -> str:
    """A deterministic sentence with the numbers behind the verdict."""
    threshold = policy.threshold_label
    if actives:
        base = (
            f"{actives} of {compounds} in-scope compound(s) at or below {threshold}; "
            "the retrieved set can serve as a potency reference for this target."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if compounds == 0:
        base = "No stored measurement for this target."
        if records_without_structure:
            base += (
                f" {records_without_structure} source record(s) reported a value without a "
                "public structure and are counted as rejections, not as measurements."
            )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if actives_outside_scope:
        base = (
            f"Only {actives_outside_scope} compound(s) outside the modality scope are at or "
            f"below {threshold}; no in-scope compound is."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if measurements and measurements == not_applicable:
        base = (
            f"{compounds} compound(s) have {measurements} record(s) that are not potency "
            f"measurements (kinetic, percent or non-concentration units); none of them can "
            f"be compared with {threshold}."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if compounds < policy.min_compounds:
        base = (
            f"{compounds} in-scope compound(s) with {measurements} record(s): none at or "
            f"below {threshold}, and fewer than the {policy.min_compounds} compounds this "
            "policy treats as a usable set (sparse and weak)."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if weak:
        base = (
            f"{compounds} in-scope compound(s): none at or below {threshold} "
            f"({weak} measured above it, {unknown} undecided)."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if unknown:
        base = (
            f"{compounds} in-scope compound(s): no measurement decides {threshold} "
            f"({unknown} censored or undecided record(s))."
        )
        return base + _remark_suffix(supplement_remarks, withdrawn_supplements)
    if truncated:
        return (
            f"None of the first {MAX_VERDICT_MEASUREMENTS} records decides {threshold}; "
            "the measurement set was truncated, so this verdict is not complete."
        )
    return (
        f"{compounds} in-scope compound(s): no measurement at or below {threshold}."
        + _remark_suffix(supplement_remarks, withdrawn_supplements)
    )


def _remark_suffix(supplement_remarks: int, withdrawn: int = 0) -> str:
    """ONLINE-07/08: hand-added rows without a structure are part of the picture.

    Counted in the verdict rather than left in a dialog, because a reader who sees
    "no active" must also see that someone recorded a claim SPAgo cannot draw — and,
    since a user may take a row back, how many hand-added rows are no longer counted
    (migration 0015).
    """
    parts: list[str] = []
    if supplement_remarks:
        parts.append(
            f"{supplement_remarks} literature remark(s) added by hand also carry a "
            "value without a public structure."
        )
    if withdrawn:
        parts.append(
            f"{withdrawn} hand-added row(s) were withdrawn by the user and are not "
            "counted."
        )
    return (" " + " ".join(parts)) if parts else ""


def _records_without_structure_many(
    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Source records with a value but no drawable structure, per target."""
    if not target_ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT target_id, rejection_counts
                FROM source_retrievals
                WHERE target_id = ANY(:tids)
                """
            ),
            {"tids": list(target_ids)},
        ).mappings().all()
    without: dict[uuid.UUID, int] = {}
    for row in rows:
        counts = row["rejection_counts"] or {}
        if isinstance(counts, (str, bytes, bytearray)):
            counts = json.loads(counts)
        total = sum(
            int(value)
            for key, value in counts.items()
            if key in _STRUCTURELESS_REJECTIONS
        )
        without[row["target_id"]] = without.get(row["target_id"], 0) + total
    return without


def _in_scope(row: _ClassifiedRow, policy: ReferencePolicy) -> bool:
    """The modality scope the *policy* states, applied to one row."""
    if policy.all_modalities:
        return True
    return row.in_scope


def _supplement_remark_count(engine: Engine, target_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Hand-added rows without a structure, per target (ONLINE-07)."""
    from spago_core.services.supplements import count_supplement_remarks

    return count_supplement_remarks(engine, target_ids)


def _withdrawn_supplement_count(
    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Hand-added rows the user withdrew, per target (ONLINE-08)."""
    from spago_core.services.supplements import count_withdrawn_supplements

    return count_withdrawn_supplements(engine, target_ids)


def _verdict_for(
    *,
    target_id: uuid.UUID,
    target_key: str,
    target_name: Optional[str],
    rows: Sequence[_ClassifiedRow],
    policy: ReferencePolicy,
    records_without_structure: int,
    truncated: bool,
    supplement_remarks: int = 0,
    withdrawn_supplements: int = 0,
) -> ReferenceVerdict:
    in_scope = [row for row in rows if _in_scope(row, policy)]
    potency = [row for row in in_scope if row.activity_class is not ActivityClass.NOT_APPLICABLE]
    best = _best_per_compound(in_scope)

    by_class = {member: 0 for member in ActivityClass}
    for row in best.values():
        by_class[row.activity_class] += 1

    modality_counts: dict[str, int] = {}
    for compound_id, row in best.items():
        key = row.modality or Modality.UNCLASSIFIED.value
        modality_counts[key] = modality_counts.get(key, 0) + 1

    actives = sorted(
        (row for row in potency if row.activity_class is ActivityClass.ACTIVE),
        key=lambda row: row.sort_key,
    )
    active_details = [row.as_active() for row in actives[:MAX_ACTIVE_DETAILS]]
    outside_scope_actives = sum(
        1
        for row in rows
        if not _in_scope(row, policy) and row.activity_class is ActivityClass.ACTIVE
    )
    compounds_active = by_class[ActivityClass.ACTIVE]

    return ReferenceVerdict(
        target_id=target_id,
        target_key=target_key,
        target_name=target_name,
        qualifies=compounds_active > 0,
        reason=_reason(
            policy=policy,
            compounds=len(best),
            actives=compounds_active,
            weak=by_class[ActivityClass.WEAK],
            unknown=by_class[ActivityClass.UNKNOWN],
            not_applicable=by_class[ActivityClass.NOT_APPLICABLE],
            measurements=len(in_scope),
            records_without_structure=records_without_structure,
            actives_outside_scope=outside_scope_actives,
            truncated=truncated,
            supplement_remarks=supplement_remarks,
            withdrawn_supplements=withdrawn_supplements,
        ),
        policy=policy,
        compounds=len(best),
        compounds_active=compounds_active,
        compounds_weak=by_class[ActivityClass.WEAK],
        compounds_unknown=by_class[ActivityClass.UNKNOWN],
        compounds_not_applicable=by_class[ActivityClass.NOT_APPLICABLE],
        active_compounds_outside_scope=outside_scope_actives,
        measurements=len(in_scope),
        class_counts=_counts(row.activity_class.value for row in in_scope),
        endpoint_counts=_counts(row.standard_type for row in potency),
        evidence_class_counts=_counts(row.evidence_class for row in in_scope),
        modality_counts=dict(sorted(modality_counts.items())),
        actives=active_details,
        best_active=active_details[0] if active_details else None,
        potential_duplicates=sum(1 for row in in_scope if row.potential_duplicate),
        records_without_structure=records_without_structure,
        #: ONLINE-07: hand-added rows without a structure are counted too, so a thin
        #: set is not read as "nothing was recorded for this target".
        supplement_remarks=supplement_remarks,
        #: ONLINE-08: hand-added rows the user took back, reported rather than
        #: silently absent from the counts.
        withdrawn_supplements=withdrawn_supplements,
        source_declared_patents=sorted(
            {row.document_patent_number for row in in_scope if row.document_patent_number}
        ),
        truncated=truncated,
    )


@dataclass(frozen=True)
class CompoundActivity:
    """One candidate's own potency summary for the investigated target."""

    activity_class: ActivityClass
    rule: Optional[str]
    value_nm: Optional[float]
    label: Optional[str]
    sources: list[str]
    patents: list[str]


def compound_activity_summary(
    engine: Engine,
    target_id: uuid.UUID,
    compound_ids: Sequence[uuid.UUID],
    policy: ReferencePolicy,
    *,
    cap: int = MAX_CANDIDATE_ROWS,
) -> dict[uuid.UUID, CompoundActivity]:
    """Per-compound class, label, sources and source-declared patents.

    Used to annotate a candidate page. The class is computed with the same rule as
    :func:`reference_verdict`, over the compound's own records in this target's
    candidate scope.

    Modality scope is deliberately *not* applied here: a row describes one
    compound, and its class is what that compound's evidence supports. Modality
    scope is a property of the *set*, and the verdict applies it — reporting
    peptide actives separately instead of hiding them.
    """
    rows, _truncated = _rows(engine, [target_id], cap, compound_ids=compound_ids)
    classified = _classify(rows, policy)
    best = _best_per_compound(classified)

    by_compound: dict[uuid.UUID, list[_ClassifiedRow]] = {}
    for row in classified:
        by_compound.setdefault(row.compound_id, []).append(row)

    summary: dict[uuid.UUID, CompoundActivity] = {}
    for compound_id, compound_rows in by_compound.items():
        top = best.get(compound_id)
        display = top
        if top is not None and top.activity_class in (ActivityClass.ACTIVE, ActivityClass.WEAK):
            # The class is the claim; the label is the most potent report of it,
            # never a value from a weaker class.
            candidates = [
                row
                for row in compound_rows
                if row.activity_class is top.activity_class
            ]
            if candidates:
                display = min(candidates, key=lambda row: row.sort_key)
        summary[compound_id] = CompoundActivity(
            activity_class=top.activity_class if top else ActivityClass.NOT_APPLICABLE,
            rule=top.rule if top else None,
            value_nm=display.value_nm if display else None,
            label=display.label() if display else None,
            sources=sorted({row.source_name for row in compound_rows}),
            patents=sorted(
                {
                    row.document_patent_number
                    for row in compound_rows
                    if row.document_patent_number
                }
            ),
        )
    return summary


def reference_verdict(
    engine: Engine,
    target,
    policy: ReferencePolicy,
    *,
    cap: int = MAX_VERDICT_MEASUREMENTS,
) -> ReferenceVerdict:
    """Verdict for one target (a `ResolvedTarget` or any object with its fields)."""
    rows, truncated = _rows(engine, [target.id], cap)
    return _verdict_for(
        target_id=target.id,
        target_key=target.target_key,
        target_name=getattr(target, "name", None),
        rows=_classify(rows, policy),
        policy=policy,
        records_without_structure=_records_without_structure_many(engine, [target.id]).get(
            target.id, 0
        ),
        supplement_remarks=_supplement_remark_count(engine, [target.id]).get(target.id, 0),
        withdrawn_supplements=_withdrawn_supplement_count(engine, [target.id]).get(
            target.id, 0
        ),
        truncated=truncated,
    )


def reference_verdicts(
    engine: Engine,
    targets: Sequence,
    policy: ReferencePolicy,
    *,
    cap: int = MAX_VERDICT_MEASUREMENTS,
) -> dict[uuid.UUID, ReferenceVerdict]:
    """Verdicts for several targets from one bounded read (coverage matrix)."""
    if not targets:
        return {}
    rows, truncated = _rows(engine, [t.id for t in targets], cap * len(targets))
    by_target: dict[uuid.UUID, list[_ClassifiedRow]] = {}
    for row in _classify(rows, policy):
        by_target.setdefault(row.target_id, []).append(row)
    without = _records_without_structure_many(engine, [t.id for t in targets])
    remarks = _supplement_remark_count(engine, [t.id for t in targets])
    withdrawn = _withdrawn_supplement_count(engine, [t.id for t in targets])
    return {
        target.id: _verdict_for(
            target_id=target.id,
            target_key=target.target_key,
            target_name=getattr(target, "name", None),
            rows=by_target.get(target.id, []),
            policy=policy,
            records_without_structure=without.get(target.id, 0),
            supplement_remarks=remarks.get(target.id, 0),
            withdrawn_supplements=withdrawn.get(target.id, 0),
            # A shared cap can truncate one target's rows; every verdict from a
            # truncated read says so instead of reporting partial counts as final.
            truncated=truncated,
        )
        for target in targets
    }
