"""Manually added literature rows for a target (ONLINE-07).

Ported from the author's ``BindingDB_IO`` process, where a target whose retrieved set
is empty or all-weak is supplemented by hand from literature or a patent. What travels
across is the *contract*, not the code:

- a row is a statement by a person, so it carries a **mandatory note**; nothing fills
  a default note in, because that would assert a provenance check the user may not have
  made (AGENTS.md §10);
- the structure goes through exactly the same path as a retrieved one — RDKit
  normalization, deterministic modality, InChIKey identity, cartridge descriptors — so
  a user-added compound is one compound, not a parallel one (AGENTS.md §11);
- the stored row is labelled ``source_name='user_supplement'`` and
  ``provenance_state='user_curated'`` and never becomes a source fact;
- a row with no public structure is kept as a **remark** (its own table) so a thin set
  is not read as a negative result, and it is never counted as a measurement.

Every submitted row is answered for: stored as a measurement, stored as a remark, or
rejected with its reasons. Nothing is dropped silently.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.chemistry import (
    StructureParseError,
    classify_modality,
    clean_external_smiles,
    murcko_scaffold,
    normalize,
)
from spago_core.chemistry.activities import (
    DEFAULT_THRESHOLD_NM,
    ActivityClass,
    classify_activity,
)
from spago_core.domain import (
    EvidenceClass,
    ProvenanceState,
    SupplementBundle,
    SupplementBundleImport,
    SupplementConfirmation,
    SupplementImport,
    SupplementImportReport,
    SupplementRemark,
    SupplementRow,
    SupplementRowOutcome,
    SuppliedRowState,
    USER_SUPPLEMENT_SOURCE,
    WithdrawalResult,
    WithdrawnSupplement,
)
from spago_core.domain.patent_numbers import normalize_patent_number
from spago_core.services import NotFoundError
from spago_core.services.compound_store import (
    COMPOUND_NAMESPACE,
    CandidateStructure,
    compound_id_for_inchikey,
    persist_compounds,
)

#: Version stamped on every stored row, so an artifact can say which import produced
#: it. Bump when the *meaning* of a stored row changes.
SUPPLEMENT_DATASET_VERSION = "user-supplement:v1"

#: How the row was produced. `extraction_method` is NOT NULL and this is the honest
#: answer: a person typed it.
EXTRACTION_METHOD = "user_supplement"

#: Candidate ids live in the same uuid5 space as compounds and assays (the name
#: prefix keeps them apart), exactly as the discovery path does it.
CANDIDATE_NAMESPACE = COMPOUND_NAMESPACE

#: How a bundle's producer decides the state its rows are stored with (B-25). This is
#: the *whole* difference between a person's own rows and a model's proposal: the rows
#: are identical, the provenance is not, and a proposal does not join the investigation
#: until a human confirms it (AGENTS.md §10/§12).
BUNDLE_PRODUCER_STATES: dict[str, ProvenanceState] = {
    "human": ProvenanceState.USER_CURATED,
    "agent": ProvenanceState.LLM_INFERRED,
    "external": ProvenanceState.MACHINE_EXTRACTED,
}

#: The keys a bundle record may use instead of the canonical ones, mapped
#: deterministically. This is a schema adapter, not keyword guessing: a number is never
#: read as an endpoint by a model, only by this table, and an activity key that would
#: collide with an explicitly stated value is refused rather than chosen between.
ACTIVITY_ALIASES: dict[str, tuple[str, str]] = {
    "ki_nm": ("Ki", "nM"),
    "ic50_nm": ("IC50", "nM"),
    "kd_nm": ("Kd", "nM"),
    "ec50_nm": ("EC50", "nM"),
}

#: A bundle record's URL. SPAgo has no column for it, so it is appended to the note the
#: reader will re-find the row by (AGENTS.md §12) — never generated, only carried.
REFERENCE_KEYS = ("reference", "url")

#: Canonical key order for a record, so the same bundle has one hash and a
#: re-import is recognisable as the same artifact.
_BUNDLE_HASH_KEYS = (
    "name",
    "note",
    "smiles",
    "activity_type",
    "value",
    "unit",
    "relation",
    "doi",
    "pmid",
    "patent_number",
)


def _row_id(target_key: str, row: SupplementRow, identity: str) -> str:
    """A stable id for a submitted row: the same row posted twice is one claim.

    A content hash, not a counter, so a retried import (or the same literature row
    added twice) updates the stored row instead of creating a second copy of one
    experiment (AGENTS.md §22).
    """
    payload = {
        "target": target_key,
        "identity": identity,
        "activity_type": (row.activity_type or "").strip().lower(),
        "value": row.value,
        "unit": (row.unit or "").strip(),
        "relation": (row.relation or "=").strip(),
        "doi": (row.doi or "").strip().lower(),
        "pmid": (row.pmid or "").strip(),
        "patent": normalize_patent_number(row.patent_number),
        "name": row.name.strip(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{USER_SUPPLEMENT_SOURCE}:{digest[:24]}"


def _validation_reasons(exc: ValidationError) -> list[str]:
    """Readable per-row reasons from a pydantic validation error."""
    reasons: list[str] = []
    for error in exc.errors():
        location = ".".join(
            str(part) for part in error.get("loc", ()) if isinstance(part, (str, int))
        )
        message = str(error.get("msg", "invalid value"))
        reasons.append(f"{location}: {message}" if location else message)
    return reasons


def _target_row(conn, target_id: uuid.UUID) -> Mapping[str, Any]:
    row = conn.execute(
        text(
            "SELECT id, target_key, name, organism, uniprot_accession "
            "FROM targets WHERE id = :tid"
        ),
        {"tid": target_id},
    ).mappings().first()
    if row is None:
        raise NotFoundError(f"Target {target_id} not found")
    return row


def _assay_id(conn, target: Mapping[str, Any], cache: dict[str, uuid.UUID]) -> uuid.UUID:
    """One assay per target for user-added rows.

    Grouping them keeps the evidence panel readable and states what they have in
    common: rows a person added, each carrying its own note and document reference.
    The assay is never presented as a source's assay.
    """
    key = f"{USER_SUPPLEMENT_SOURCE}:{target['target_key']}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    assay_id = uuid.uuid5(COMPOUND_NAMESPACE, f"assay:{key}")
    cache[key] = assay_id
    conn.execute(
        text(
            """
            INSERT INTO assays (id, assay_key, target_id, assay_type, description,
                                source_name, dataset_version, retrieved_at)
            VALUES (:id, :assay_key, :target_id, :assay_type, :description,
                    :source_name, :dataset_version, :retrieved_at)
            ON CONFLICT (assay_key) DO UPDATE
              SET target_id = EXCLUDED.target_id,
                  description = EXCLUDED.description,
                  retrieved_at = EXCLUDED.retrieved_at
            """
        ),
        {
            "id": assay_id,
            "assay_key": key,
            "target_id": target["id"],
            "assay_type": "user_supplement",
            "description": (
                "Rows added by hand from literature or a patent. Each measurement "
                "carries its own note and document reference; no source retrieval "
                "produced them."
            ),
            "source_name": USER_SUPPLEMENT_SOURCE,
            "dataset_version": SUPPLEMENT_DATASET_VERSION,
            "retrieved_at": datetime.now(timezone.utc),
        },
    )
    return assay_id


def _store_remark(
    conn,
    target: Mapping[str, Any],
    row: SupplementRow,
    index: int,
    record_id: str,
    provenance_state: ProvenanceState = ProvenanceState.USER_CURATED,
) -> tuple[SupplementRowOutcome, bool]:
    """Keep a structure-less row as a remark (never as a compound).

    Returns the row's answer and whether it replaced a row already stored for the same
    claim, so the run can say "this import updated a row that was already here" instead
    of reporting every re-post as new (B-25).

    A re-posted row is current again *and* keeps the strongest provenance it ever had:
    a person's statement is never downgraded to a model's by a later import (B-25).
    """
    existing = conn.execute(
        text(
            "SELECT 1 FROM target_supplement_remarks "
            "WHERE target_id = :tid AND source_record_id = :rid"
        ),
        {"tid": target["id"], "rid": record_id},
    ).first()
    conn.execute(
        text(
            """
            INSERT INTO target_supplement_remarks (id, target_id, source_record_id, name,
                                                   note, activity_type, value, unit,
                                                   relation, doi, pmid, patent_number,
                                                   source_name, provenance_state,
                                                   dataset_version)
            VALUES (:id, :target_id, :source_record_id, :name,
                    :note, :activity_type, :value, :unit,
                    :relation, :doi, :pmid, :patent_number,
                    :source_name, :provenance_state,
                    :dataset_version)
            ON CONFLICT (target_id, source_record_id) DO UPDATE
              SET name = EXCLUDED.name,
                  note = EXCLUDED.note,
                  activity_type = EXCLUDED.activity_type,
                  value = EXCLUDED.value,
                  unit = EXCLUDED.unit,
                  relation = EXCLUDED.relation,
                  doi = EXCLUDED.doi,
                  pmid = EXCLUDED.pmid,
                  patent_number = EXCLUDED.patent_number,
                  -- Provenance never downgrades: a human's row stays the person's,
                  -- whatever a later import claims (B-25).
                  provenance_state = CASE
                      WHEN target_supplement_remarks.provenance_state = 'user_curated'
                          THEN target_supplement_remarks.provenance_state
                      ELSE EXCLUDED.provenance_state
                  END,
                  -- A re-posted row is current again (ONLINE-08).
                  retracted_at = NULL,
                  retracted_reason = NULL
            """
        ),
        {
            "id": uuid.uuid5(COMPOUND_NAMESPACE, f"supplement-remark:{record_id}"),
            "target_id": target["id"],
            "source_record_id": record_id,
            "name": row.name.strip(),
            "note": row.note.strip(),
            "activity_type": row.activity_type,
            "value": row.value,
            "unit": row.unit,
            "relation": row.relation,
            "doi": row.doi,
            "pmid": row.pmid,
            "patent_number": normalize_patent_number(row.patent_number) or row.patent_number,
            "source_name": USER_SUPPLEMENT_SOURCE,
            "provenance_state": provenance_state.value,
            "dataset_version": SUPPLEMENT_DATASET_VERSION,
        },
    )
    reasons = [
        "stored without a structure: no public SMILES was supplied, so the row is "
        "kept as a remark with its potency and cannot be drawn or exported as a compound"
    ]
    if provenance_state is not ProvenanceState.USER_CURATED:
        reasons.append(
            f"proposed by its producer ({provenance_state.value}): it is readable and "
            "counted separately, and it is not part of this investigation until a person "
            "confirms the import"
        )
    if row.value is None:
        reasons.append("no value was supplied, so this row carries only the note")
    return (
        SupplementRowOutcome(
            index=index,
            status="remark",
            name=row.name.strip(),
            record_id=record_id,
            reasons=reasons,
        ),
        existing is not None,
    )


def import_supplements(
    engine: Engine,
    target_id: uuid.UUID,
    rows: Sequence[Mapping[str, Any]],
    *,
    threshold_nm: float = DEFAULT_THRESHOLD_NM,
    provenance_state: ProvenanceState = ProvenanceState.USER_CURATED,
) -> SupplementImport:
    """Store literature rows for one target.

    Each row is validated on its own, so one bad row cannot refuse the batch, and
    every row is answered for in the result.

    ``provenance_state`` is what the stored rows are labelled with, and it decides one
    more thing: a row that a person has not asserted (anything but ``user_curated``)
    creates **no** candidate row, and migration 0015 defines investigation scope through
    `target_candidates`. So an unreviewed proposal cannot move a verdict, a selection,
    an export or a summary — not because four code paths filter it, but because it has
    not joined the investigation (B-25, AGENTS.md §12).
    """
    reviewed = provenance_state is ProvenanceState.USER_CURATED
    result = SupplementImport(target_id=target_id, received=len(rows))
    if not rows:
        return result

    outcomes: list[SupplementRowOutcome] = []
    with engine.begin() as conn:
        target = _target_row(conn, target_id)
        target_key = str(target["target_key"])
        assay_cache: dict[str, uuid.UUID] = {}
        normalized: dict[str, CandidateStructure] = {}
        prepared: list[tuple[int, SupplementRow, str, CandidateStructure]] = []

        for index, raw in enumerate(rows):
            try:
                row = SupplementRow.model_validate(dict(raw))
            except ValidationError as exc:
                outcomes.append(
                    SupplementRowOutcome(
                        index=index,
                        status="rejected",
                        name=str(raw.get("name") or "")[:300],
                        reasons=_validation_reasons(exc),
                    )
                )
                continue

            if not (row.smiles or "").strip():
                outcome, replaced = _store_remark(
                    conn,
                    target,
                    row,
                    index,
                    _row_id(target_key, row, ""),
                    provenance_state,
                )
                outcomes.append(outcome)
                result.remarks += 1
                if replaced:
                    result.updated += 1
                continue
            cleaned, notes = clean_external_smiles(row.smiles or "")
            try:
                structure = normalize(cleaned)
            except StructureParseError as exc:
                outcomes.append(
                    SupplementRowOutcome(
                        index=index,
                        status="rejected",
                        name=row.name.strip(),
                        reasons=[
                            f"unparseable_structure: {exc}",
                            "the row was not stored; correct the structure and re-submit",
                        ],
                    )
                )
                continue
            # A producer may state the identity it believes it is sending. It is
            # checked against the structure SPAgo computed, never trusted: a row whose
            # stated identity and drawn structure disagree is refused, because storing
            # it would mean storing a structure nobody can vouch for (B-25, §11).
            if (row.inchikey or "").strip():
                stated = (row.inchikey or "").strip().upper()
                if stated != structure.inchikey.upper():
                    outcomes.append(
                        SupplementRowOutcome(
                            index=index,
                            status="rejected",
                            name=row.name.strip(),
                            reasons=[
                                f"inchikey_mismatch: the row states {stated} but its "
                                f"structure normalizes to {structure.inchikey}",
                                "the row was not stored: correct the structure or the "
                                "stated identity and re-submit",
                            ],
                        )
                    )
                    continue
            verdict = classify_modality(structure.canonical_smiles)
            try:
                scaffold = murcko_scaffold(structure.canonical_smiles)
            except StructureParseError:
                scaffold = None
            candidate = CandidateStructure(
                raw_smiles=(row.smiles or "").strip(),
                structure=structure,
                modality=verdict.modality,
                modality_rule=verdict.rule + (";" + ";".join(notes) if notes else ""),
                modality_source="rdkit",
                scaffold=scaffold,
            )
            record_id = _row_id(target_key, row, f"inchikey:{structure.inchikey}")
            prepared.append((index, row, record_id, candidate))
            normalized.setdefault(structure.inchikey, candidate)

        # Identity is global: a structure already in the corpus (from ChEMBL, BindingDB
        # or a patent) is reused, never re-created, and the response says which rows hit
        # that case.
        pre_existing: set[str] = set()
        if normalized:
            pre_existing = set(
                conn.execute(
                    text("SELECT inchikey FROM compounds WHERE inchikey = ANY(:keys)"),
                    {"keys": list(normalized)},
                )
                .scalars()
                .all()
            )
        stored, reused = persist_compounds(conn, normalized)
        result.compounds_created = stored
        result.compounds_reused = reused

        for index, row, record_id, candidate in prepared:
            compound_id = compound_id_for_inchikey(candidate.inchikey)
            # How the same row keyed *without* a structure: if it was stored earlier as
            # a remark, this submission supersedes it. One claim stays one row, so the
            # verdict cannot count the same paper twice (AGENTS.md §22).
            remark_key = _row_id(target_key, row, "")
            superseded = conn.execute(
                text(
                    "DELETE FROM target_supplement_remarks "
                    "WHERE target_id = :tid AND source_record_id = :rid"
                ),
                {"tid": target["id"], "rid": remark_key},
            ).rowcount
            activity_class = ActivityClass.NOT_APPLICABLE
            rule = "no_value"
            if row.value is not None:
                activity_class, rule = classify_activity(
                    row.value,
                    row.unit or "",
                    row.relation or "=",
                    row.activity_type or "",
                    threshold_nm,
                )
                assay_id = _assay_id(conn, target, assay_cache)
                existing = conn.execute(
                    text(
                        "SELECT 1 FROM measurements WHERE compound_id = :cid "
                        "AND assay_id = :aid AND standard_type = :st "
                        "AND source_record_id = :sid"
                    ),
                    {
                        "cid": compound_id,
                        "aid": assay_id,
                        "st": (row.activity_type or "").strip(),
                        "sid": record_id,
                    },
                ).first()
                conn.execute(
                    text(
                        """
                        INSERT INTO measurements (id, compound_id, assay_id, standard_type,
                                                  value, unit, relation, source_record_id,
                                                  source_name, extraction_method,
                                                  provenance_state, confidence,
                                                  dataset_version, retrieved_at,
                                                  evidence_class, raw_value,
                                                  assay_description, assay_format, species,
                                                  document_ref, document_doi,
                                                  document_pmid, document_patent_number)
                        VALUES (:id, :compound_id, :assay_id, :standard_type,
                                :value, :unit, :relation, :source_record_id,
                                :source_name, :extraction_method,
                                :provenance_state, NULL,
                                :dataset_version, :retrieved_at,
                                :evidence_class, :raw_value,
                                :assay_description, NULL, NULL,
                                :document_ref, :document_doi,
                                :document_pmid, :document_patent_number)
                        ON CONFLICT (compound_id, assay_id, standard_type, source_record_id)
                          DO UPDATE SET
                            value = EXCLUDED.value,
                            unit = EXCLUDED.unit,
                            relation = EXCLUDED.relation,
                            -- Provenance never downgrades: a person's own row is not
                            -- turned into a model's proposal by a later import (B-25).
                            provenance_state = CASE
                                WHEN measurements.provenance_state = 'user_curated'
                                    THEN measurements.provenance_state
                                ELSE EXCLUDED.provenance_state
                            END,
                            dataset_version = EXCLUDED.dataset_version,
                            raw_value = EXCLUDED.raw_value,
                            assay_description = EXCLUDED.assay_description,
                            document_ref = EXCLUDED.document_ref,
                            document_doi = EXCLUDED.document_doi,
                            document_pmid = EXCLUDED.document_pmid,
                            document_patent_number = EXCLUDED.document_patent_number,
                            retrieved_at = EXCLUDED.retrieved_at,
                            -- Re-posting a row that was withdrawn makes it current
                            -- again: the user's re-post is the statement (ONLINE-08).
                            retracted_at = NULL,
                            retracted_reason = NULL
                        """
                    ),
                    {
                        "id": uuid.uuid5(
                            COMPOUND_NAMESPACE,
                            f"measurement:{target_key}:{USER_SUPPLEMENT_SOURCE}:{record_id}",
                        ),
                        "compound_id": compound_id,
                        "assay_id": assay_id,
                        "standard_type": (row.activity_type or "").strip(),
                        "value": row.value,
                        "unit": (row.unit or "").strip(),
                        "relation": (row.relation or "=").strip(),
                        "source_record_id": record_id,
                        "source_name": USER_SUPPLEMENT_SOURCE,
                        "extraction_method": EXTRACTION_METHOD,
                        "provenance_state": provenance_state.value,
                        "dataset_version": SUPPLEMENT_DATASET_VERSION,
                        "retrieved_at": datetime.now(timezone.utc),
                        "evidence_class": EvidenceClass.UNSPECIFIED.value,
                        "raw_value": f"{row.value:g} {row.unit}",
                        # The note is the row's provenance and is shown with it in the
                        # evidence panel; it is not a source's assay description.
                        "assay_description": row.note.strip(),
                        "document_ref": (
                            (row.doi or "").strip()
                            or (row.pmid or "").strip()
                            or normalize_patent_number(row.patent_number)
                            or None
                        ),
                        "document_doi": (row.doi or "").strip() or None,
                        "document_pmid": (row.pmid or "").strip() or None,
                        "document_patent_number": (
                            normalize_patent_number(row.patent_number) or None
                        ),
                    },
                )
                if existing:
                    result.updated += 1
                result.measurements += 1

            # Only a row a human has asserted joins the investigation. Migration 0015
            # defines scope through this table, so skipping it here is what keeps an
            # unreviewed proposal out of every verdict, selection, export and summary
            # at once (B-25) — and confirmation is exactly the act that inserts it.
            if reviewed:
                conn.execute(
                    text(
                        """
                        INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                       source_record_id, source_molecule_id,
                                                       evidence_class, modality, retrieval_id,
                                                       dataset_version, retrieved_at)
                        VALUES (:id, :target_id, :compound_id, :source_name,
                                :source_record_id, NULL,
                                :evidence_class, :modality, NULL,
                                :dataset_version, :retrieved_at)
                        ON CONFLICT (target_id, source_name, source_record_id) DO UPDATE
                          SET evidence_class = EXCLUDED.evidence_class,
                              modality = EXCLUDED.modality,
                              retrieved_at = EXCLUDED.retrieved_at,
                              -- Withdrawing a row takes the compound out of this
                              -- investigation; re-posting it puts it back (defect D3).
                              retracted_at = NULL,
                              retracted_reason = NULL
                        """
                    ),
                    {
                        "id": uuid.uuid5(
                            CANDIDATE_NAMESPACE,
                            f"candidate:{target['id']}:{USER_SUPPLEMENT_SOURCE}:{record_id}",
                        ),
                        "target_id": target["id"],
                        "compound_id": compound_id,
                        "source_name": USER_SUPPLEMENT_SOURCE,
                        "source_record_id": record_id,
                        "evidence_class": EvidenceClass.UNSPECIFIED.value,
                        "modality": candidate.modality.value,
                        "dataset_version": SUPPLEMENT_DATASET_VERSION,
                        "retrieved_at": datetime.now(timezone.utc),
                    },
                )

            reasons = [
                (
                    "stored as a user-curated measurement"
                    if row.value is not None
                    else "stored as a candidate without a value: no potency to classify"
                )
                if reviewed
                else (
                    "stored as an unreviewed measurement / candidate: it is readable and "
                    "counted separately, and it does not join this investigation until a "
                    "person confirms the import"
                ),
                (
                    f"class {activity_class.value} ({rule}) under the stated threshold"
                ),
            ]
            if superseded:
                reasons.append(
                    "replaced an earlier structure-less remark for the same row, so the "
                    "claim is counted once"
                )
            outcomes.append(
                SupplementRowOutcome(
                    index=index,
                    status="measurement",
                    name=row.name.strip(),
                    record_id=record_id,
                    compound_id=compound_id,
                    inchikey=candidate.inchikey,
                    activity_class=activity_class,
                    reused_compound=candidate.inchikey in pre_existing,
                    reasons=reasons,
                )
            )

    result.rows = sorted(outcomes, key=lambda outcome: outcome.index)
    return result


def list_supplement_remarks(
    engine: Engine, target_id: uuid.UUID, *, include_withdrawn: bool = False
) -> list[SupplementRemark]:
    """Stored structure-less rows for one target (newest first).

    Withdrawn rows stay readable — a user must be able to see what they took back
    and why — so they are included only when the caller asks for them, and the
    verdict counts them separately (AGENTS.md §10).
    """
    scope = "" if include_withdrawn else "AND retracted_at IS NULL"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, target_id, source_record_id, name, note, activity_type, value,
                       unit, relation, doi, pmid, patent_number, provenance_state,
                       created_at, retracted_at, retracted_reason
                FROM target_supplement_remarks
                WHERE target_id = :tid {scope}
                ORDER BY created_at DESC, name
                """
            ),
            {"tid": target_id},
        ).mappings().all()
    return [SupplementRemark(**dict(row)) for row in rows]


def count_supplement_remarks(
    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Asserted remark count per target, for the reference verdict.

    Withdrawn remarks are not counted: the verdict says what the target holds now.
    ``count_withdrawn_supplements`` reports them separately so a withdrawal is
    visible rather than looking like a row that never existed.

    A remark a person has not asserted (an unreviewed proposal from a bundle, B-25) is
    not counted either: the verdict's supplement count is a count of *the user's own
    additions*, and ``count_unreviewed_supplements`` reports proposals beside it, the
    same way withdrawn rows are reported rather than hidden.
    """
    ids = list(target_ids)
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT target_id, count(*) AS n FROM target_supplement_remarks "
                "WHERE target_id = ANY(:tids) AND retracted_at IS NULL "
                "AND provenance_state = 'user_curated' GROUP BY target_id"
            ),
            {"tids": ids},
        ).mappings().all()
    return {row["target_id"]: int(row["n"]) for row in rows}


def withdraw_supplement(
    engine: Engine,
    target_id: uuid.UUID,
    record_id: str,
    reason: str,
) -> WithdrawalResult:
    """Take back a hand-added row the user owns (ONLINE-08).

    Only rows this service created can be withdrawn: a source row is not the
    user's to remove, and a withdrawal is never a way to edit a database fact.
    The row is retracted rather than deleted, so its note, its provenance and the
    reason for the withdrawal stay readable.

    Taking back the last live measurement of a hand-added compound also takes that
    compound out of the investigation's candidate list; the compound record itself
    stays, because another target or a patent occurrence may still refer to it.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A withdrawal must state why the row is being taken back.")
    with engine.begin() as conn:
        target = _target_row(conn, target_id)
        measurement = conn.execute(
            text(
                """
                SELECT id, compound_id FROM measurements
                WHERE source_name = :source AND source_record_id = :rid
                  AND assay_id IN (SELECT id FROM assays WHERE target_id = :tid)
                """
            ),
            {"source": USER_SUPPLEMENT_SOURCE, "rid": record_id, "tid": target["id"]},
        ).mappings().first()
        remark = None
        if measurement is None:
            remark = conn.execute(
                text(
                    "SELECT id FROM target_supplement_remarks "
                    "WHERE target_id = :tid AND source_record_id = :rid"
                ),
                {"tid": target["id"], "rid": record_id},
            ).mappings().first()
        if measurement is None and remark is None:
            raise NotFoundError(
                f"No hand-added row {record_id!r} for this target. Source rows cannot "
                "be withdrawn here."
            )
        if measurement is not None:
            conn.execute(
                text(
                    "UPDATE measurements SET retracted_at = now(), retracted_reason = :reason "
                    "WHERE id = :id AND retracted_at IS NULL"
                ),
                {"id": measurement["id"], "reason": reason},
            )
            live = conn.execute(
                text(
                    "SELECT count(*) FROM measurements WHERE compound_id = :cid "
                    "AND assay_id IN (SELECT id FROM assays WHERE target_id = :tid) "
                    "AND retracted_at IS NULL"
                ),
                {"cid": measurement["compound_id"], "tid": target["id"]},
            ).scalar_one()
            candidates_retracted = 0
            if int(live) == 0:
                candidates_retracted = conn.execute(
                    text(
                        "UPDATE target_candidates SET retracted_at = now(), "
                        "retracted_reason = :reason WHERE target_id = :tid "
                        "AND compound_id = :cid AND retracted_at IS NULL"
                    ),
                    {
                        "reason": (
                            "every live measurement of this compound for this target was "
                            f"withdrawn: {reason}"
                        ),
                        "tid": target["id"],
                        "cid": measurement["compound_id"],
                    },
                ).rowcount
            return WithdrawalResult(
                kind="measurement",
                record_id=record_id,
                compound_id=str(measurement["compound_id"]),
                candidate_retracted=bool(candidates_retracted),
                reason=reason,
            )
        conn.execute(
            text(
                "UPDATE target_supplement_remarks SET retracted_at = now(), "
                "retracted_reason = :reason WHERE id = :id AND retracted_at IS NULL"
            ),
            {"id": remark["id"], "reason": reason},
        )
        return WithdrawalResult(kind="remark", record_id=record_id, reason=reason)


def list_withdrawn_supplements(
    engine: Engine, target_id: uuid.UUID
) -> list[WithdrawnSupplement]:
    """Hand-added rows the user took back, newest first (defect D3).

    Both kinds in one list: the reader's question is "what did I take back, and
    why", and that answer must not depend on whether the row had a structure. The
    rows are retracted, never deleted, so this list is the audit trail behind the
    verdict's `withdrawn_supplements` count.
    """
    with engine.begin() as conn:
        target = _target_row(conn, target_id)
        rows = conn.execute(
            text(
                """
                SELECT 'measurement' AS kind, m.source_record_id AS record_id,
                       coalesce(m.assay_description, '') AS name,
                       m.assay_description AS note,
                       m.standard_type AS activity_type,
                       m.value, m.unit, m.relation,
                       m.retracted_at, m.retracted_reason,
                       EXISTS (
                           SELECT 1 FROM target_candidates tc
                            WHERE tc.target_id = :tid AND tc.compound_id = m.compound_id
                              AND tc.retracted_at IS NOT NULL
                       ) AS candidate_retracted
                  FROM measurements m
                  JOIN assays a ON a.id = m.assay_id
                 WHERE m.source_name = :source AND m.retracted_at IS NOT NULL
                   AND a.target_id = :tid
                UNION ALL
                SELECT 'remark' AS kind, source_record_id AS record_id,
                       name, note, activity_type, value, unit, relation,
                       retracted_at, retracted_reason, false AS candidate_retracted
                  FROM target_supplement_remarks
                 WHERE target_id = :tid AND retracted_at IS NOT NULL
                 ORDER BY retracted_at DESC, record_id
                """
            ),
            {"tid": target["id"], "source": USER_SUPPLEMENT_SOURCE},
        ).mappings().all()
    return [WithdrawnSupplement(**dict(row)) for row in rows]


def count_withdrawn_supplements(    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Hand-added rows that were withdrawn, per target, for the verdict."""
    ids = list(target_ids)
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT target_id, sum(measurements + remarks) AS n FROM (
                    SELECT a.target_id AS target_id, count(*) AS measurements, 0 AS remarks
                    FROM measurements m
                    JOIN assays a ON a.id = m.assay_id
                    WHERE m.source_name = :source AND m.retracted_at IS NOT NULL
                      AND a.target_id = ANY(:tids)
                    GROUP BY a.target_id
                    UNION ALL
                    SELECT target_id, 0, count(*)
                    FROM target_supplement_remarks
                    WHERE target_id = ANY(:tids) AND retracted_at IS NOT NULL
                    GROUP BY target_id
                ) counts
                GROUP BY target_id
                """
            ),
            {"tids": ids, "source": USER_SUPPLEMENT_SOURCE},
        ).mappings().all()
    return {row["target_id"]: int(row["n"]) for row in rows}


# --- B-25: a bundle of rows, and the review that admits it -------------------------


class BundleRefused(ValueError):
    """The bundle cannot be imported as a whole, and saying so is the answer.

    Used for the envelope (an unsupported version, a declared target that is not this
    target) — never for one bad row, which is refused per row with its reasons so the
    rest of the file still arrives.
    """


class _RowRefused(ValueError):
    """One bundle record cannot be mapped; the rest of the file still imports."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def map_bundle_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One bundle record in canonical shape, before row validation.

    This is a *schema adapter*, not interpretation: it resolves the small set of keys a
    producer may reasonably use (``ic50_nm`` → ``value``/``unit``) by a fixed table, and
    refuses anything it cannot resolve that way rather than guessing (AGENTS.md §12).
    Unknown keys are passed through on purpose: the row validator refuses them by name,
    which tells the producer exactly what to fix.

    The producer's ``reference``/``url`` is carried into the note, because SPAgo has no
    column for it and a row without the link is a row the reader cannot re-find
    (AGENTS.md §12). Nothing here invents a value, a structure or an endpoint.
    """
    if not isinstance(raw, Mapping):
        raise _RowRefused([f"a record must be an object, got {type(raw).__name__}"])
    record = dict(raw)
    reasons: list[str] = []

    reference = None
    for key in REFERENCE_KEYS:
        value = record.pop(key, None)
        if isinstance(value, str) and value.strip():
            if reference and reference != value.strip():
                reasons.append(
                    f"states both a reference and a url ({reference} / {value.strip()}): "
                    "say where the row comes from in one place"
                )
            reference = reference or value.strip()

    for alias, (endpoint, unit) in ACTIVITY_ALIASES.items():
        if alias not in record:
            continue
        number = record.pop(alias)
        if number is None:
            continue
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            reasons.append(
                f"{alias}: expected a number in {unit}, got {number!r}; a value that "
                "cannot be compared with a threshold is not a potency"
            )
            continue
        if record.get("value") is not None and record.get("value") != number:
            reasons.append(
                f"states both value={record.get('value')} and {alias}={number}: which "
                "number is the potency is not a choice this importer makes"
            )
            continue
        stated_type = record.get("activity_type")
        if stated_type and str(stated_type).strip() != endpoint:
            reasons.append(
                f"states both activity_type={stated_type!r} and {alias}: one row is one "
                "endpoint, and the importer will not pick between them"
            )
            continue
        stated_unit = record.get("unit")
        if stated_unit and str(stated_unit).strip() != unit:
            reasons.append(
                f"states both unit={stated_unit!r} and {alias}: a converted number is not "
                "the reported number, so the row must state one of them"
            )
            continue
        record.setdefault("value", number)
        record.setdefault("activity_type", endpoint)
        record.setdefault("unit", unit)

    if reasons:
        raise _RowRefused(reasons)

    note = record.get("note")
    if not (isinstance(note, str) and note.strip()):
        # The row must keep the note a reader re-finds it by. A stated reference is
        # carried as that note; with neither, the row is refused by the row validator
        # ("note: Field required") rather than given a generated one.
        if reference:
            record["note"] = f"reference: {reference}"
    elif reference:
        record["note"] = f"{note.rstrip()}\nreference: {reference}"
    return record


def supplement_bundle_hash(bundle: SupplementBundle) -> str:
    """One hash for one artifact: the envelope plus the records, order-insensitively.

    The same file imported twice hashes the same, which is how a repeat import is
    recognisable as a repeat instead of looking like new work; a changed envelope (a new
    `generated_at`, a different producer) is a different run and hashes differently.
    """
    records = sorted(
        json.dumps(record, sort_keys=True, default=str) for record in bundle.records
    )
    payload = {
        "bundle_version": bundle.bundle_version,
        "produced_by": bundle.produced_by,
        "produced_by_kind": bundle.produced_by_kind,
        "searched": bundle.searched,
        "generated_at": bundle.generated_at,
        "uniprot": bundle.uniprot,
        "records": records,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _bundle_matches_target(conn, target_id: uuid.UUID, uniprot: Optional[str]) -> None:
    """Refuse a bundle that declares a different protein than the target it is sent to.

    The guard exists because the realistic mistake is not malice: an agent's file for
    target A pasted into target B's dialog would otherwise store A's rows under B, and
    every one of them would look like B's evidence (AGENTS.md §10).
    """
    target = _target_row(conn, target_id)
    if not uniprot:
        return
    declared = uniprot.strip().upper()
    accession = (target["uniprot_accession"] or "").strip().upper()
    if declared != accession:
        raise BundleRefused(
            f"bundle declares uniprot {uniprot.strip()} but this target is "
            f"{target['name']}"
            + (f" ({accession})" if accession else " (no UniProt accession on record)")
            + ": import it into the target it was produced for, or remove the field"
        )


def import_supplement_bundle(
    engine: Engine,
    target_id: uuid.UUID,
    bundle: SupplementBundle,
    *,
    threshold_nm: float = DEFAULT_THRESHOLD_NM,
    submitted_by: Optional[str] = None,
) -> SupplementBundleImport:
    """Import a whole artifact and record the run that brought it in.

    The rows are stored exactly as the one-row path stores them; what differs is the
    provenance they carry and one consequence: rows from an ``agent`` or ``external``
    producer create no candidate row, so they are outside every count, verdict,
    selection and export until a person confirms the import (B-25, AGENTS.md §10/§12).

    A refused row is not a lost row: its reasons are stored in the import's outcomes,
    because "what did this file propose that SPAgo would not store" is part of the run.
    """
    state = BUNDLE_PRODUCER_STATES[bundle.produced_by_kind]
    mapped: list[tuple[int, dict[str, Any]]] = []
    refused: list[SupplementRowOutcome] = []
    for index, raw in enumerate(bundle.records):
        try:
            mapped.append((index, map_bundle_record(raw)))
        except _RowRefused as exc:
            refused.append(
                SupplementRowOutcome(
                    index=index,
                    status="rejected",
                    name=str(raw.get("name") or "")[:300] if isinstance(raw, Mapping) else "",
                    reasons=exc.reasons + [
                        "the row was not stored; the rest of the bundle was imported"
                    ],
                )
            )

    with engine.connect() as conn:
        _bundle_matches_target(conn, target_id, bundle.uniprot)

    result = import_supplements(
        engine,
        target_id,
        [record for _index, record in mapped],
        threshold_nm=threshold_nm,
        provenance_state=state,
    )
    # Row outcomes come back indexed by *imported* position; the reader is looking at
    # the file, so every answer is re-indexed to the record it belongs to.
    for outcome in result.rows:
        if 0 <= outcome.index < len(mapped):
            outcome.index = mapped[outcome.index][0]
    outcomes = sorted(result.rows + refused, key=lambda outcome: outcome.index)
    rejected = sum(1 for outcome in outcomes if outcome.status == "rejected")
    record_ids = [outcome.record_id for outcome in outcomes if outcome.record_id]

    bundle_hash = supplement_bundle_hash(bundle)
    with engine.begin() as conn:
        import_id = uuid.uuid4()
        conn.execute(
            text(
                """
                INSERT INTO supplement_imports (id, target_id, bundle_hash, bundle_version,
                                                produced_by, produced_by_kind, searched,
                                                generated_at, received, measurements,
                                                remarks, rejected, compounds_created,
                                                compounds_reused, updated_rows, record_ids,
                                                outcomes, provenance_state, submitted_by)
                VALUES (:id, :tid, :hash, :version, :produced_by, :kind, :searched,
                        :generated_at, :received, :measurements, :remarks, :rejected,
                        :created, :reused, :updated, CAST(:record_ids AS jsonb),
                        CAST(:outcomes AS jsonb), :provenance_state, :submitted_by)
                """
            ),
            {
                "id": import_id,
                "tid": target_id,
                "hash": bundle_hash,
                "version": bundle.bundle_version,
                "produced_by": bundle.produced_by.strip(),
                "kind": bundle.produced_by_kind,
                "searched": bundle.searched.strip(),
                "generated_at": bundle.generated_at,
                "received": len(bundle.records),
                "measurements": result.measurements,
                "remarks": result.remarks,
                "rejected": rejected,
                "created": result.compounds_created,
                "reused": result.compounds_reused,
                "updated": result.updated,
                "record_ids": json.dumps(record_ids),
                "outcomes": json.dumps(
                    [outcome.model_dump(mode="json") for outcome in outcomes]
                ),
                "provenance_state": state.value,
                "submitted_by": submitted_by,
            },
        )
        report = _supplement_import_report(conn, import_id, threshold_nm)
        stored = _stored_rows(conn, target_id, record_ids, outcomes, threshold_nm)
    report.stored = stored
    return SupplementBundleImport(
        report=report, awaiting_review=state is not ProvenanceState.USER_CURATED
    )


def _stored_rows(
    conn,
    target_id: uuid.UUID,
    record_ids: Sequence[str],
    outcomes: Sequence[SupplementRowOutcome],
    threshold_nm: float,
) -> list[SuppliedRowState]:
    """What the given record ids are *now*, read back rather than remembered.

    Read back on purpose: a row may have been withdrawn, or superseded by a matching
    structure, since the import ran, and a report that repeated the import's own answer
    would hide exactly the change a reviewer needs to see.
    """
    if not record_ids:
        return []
    # The submitted name lives in the outcomes (a measurement has no name column), so a
    # reviewer sees the label the file used without a schema change for it.
    names = {
        outcome.record_id: outcome.name
        for outcome in outcomes
        if outcome.record_id and outcome.name
    }
    rows = conn.execute(
        text(
            """
            SELECT 'measurement' AS kind, m.source_record_id AS record_id,
                   NULL AS name,
                   m.assay_description AS note,
                   m.standard_type AS activity_type, m.value, m.unit, m.relation,
                   m.document_doi AS doi, m.document_pmid AS pmid,
                   m.document_patent_number AS patent_number,
                   m.compound_id, c.inchikey, m.provenance_state,
                   m.retracted_at, m.retracted_reason
              FROM measurements m
              JOIN assays a ON a.id = m.assay_id
              LEFT JOIN compounds c ON c.id = m.compound_id
             WHERE a.target_id = :tid AND m.source_name = :source
               AND m.source_record_id = ANY(:ids)
            UNION ALL
            SELECT 'remark' AS kind, source_record_id AS record_id, name, note,
                   activity_type, value, unit, relation, doi, pmid, patent_number,
                   NULL AS compound_id, NULL AS inchikey, provenance_state,
                   retracted_at, retracted_reason
              FROM target_supplement_remarks
             WHERE target_id = :tid AND source_record_id = ANY(:ids)
            """
        ),
        {"tid": target_id, "source": USER_SUPPLEMENT_SOURCE, "ids": list(record_ids)},
    ).mappings().all()

    stored: list[SuppliedRowState] = []
    for row in rows:
        activity_class = None
        rule = None
        if row["value"] is not None:
            activity_class, rule = classify_activity(
                float(row["value"]),
                row["unit"] or "",
                row["relation"] or "=",
                row["activity_type"] or "",
                threshold_nm,
            )
        stored.append(
            SuppliedRowState(
                kind=row["kind"],
                record_id=row["record_id"],
                name=row["name"] or names.get(row["record_id"], "") or "",
                note=row["note"],
                activity_type=row["activity_type"],
                value=row["value"],
                unit=row["unit"],
                relation=row["relation"],
                doi=row["doi"],
                pmid=row["pmid"],
                patent_number=row["patent_number"],
                compound_id=row["compound_id"],
                inchikey=row["inchikey"],
                activity_class=activity_class,
                activity_class_rule=rule,
                live=row["retracted_at"] is None,
                retracted_at=row["retracted_at"],
                retracted_reason=row["retracted_reason"],
            )
        )
    return sorted(stored, key=lambda state: (state.kind, state.name, state.record_id))


def _supplement_import_report(
    conn,
    import_id: uuid.UUID,
    threshold_nm: float,
) -> SupplementImportReport:
    """One stored import row as the contract model (stored rows filled separately)."""
    row = conn.execute(
        text(
            """
            SELECT id, target_id, bundle_hash, bundle_version, produced_by,
                   produced_by_kind, searched, generated_at, received, measurements,
                   remarks, rejected, compounds_created, compounds_reused, updated_rows,
                   record_ids, outcomes, provenance_state, submitted_by, created_at,
                   confirmed_at, confirmed_by
              FROM supplement_imports WHERE id = :id
            """
        ),
        {"id": import_id},
    ).mappings().one()
    # "The same file was imported before" is derived from the runs themselves, never
    # remembered at insert time: the answer is the earlier run with this hash for this
    # target, so it is still there when the import is read back later and cannot dangle
    # if that earlier run is removed.
    repeated = conn.execute(
        text(
            "SELECT id FROM supplement_imports WHERE target_id = :tid "
            "AND bundle_hash = :h AND (created_at, id) < (:created, :id) "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {
            "tid": row["target_id"],
            "h": row["bundle_hash"],
            "created": row["created_at"],
            "id": row["id"],
        },
    ).scalar()
    return SupplementImportReport(
        id=row["id"],
        target_id=row["target_id"],
        bundle_hash=row["bundle_hash"],
        bundle_version=row["bundle_version"],
        produced_by=row["produced_by"],
        produced_by_kind=row["produced_by_kind"],
        searched=row["searched"],
        generated_at=row["generated_at"],
        received=row["received"],
        measurements=row["measurements"],
        remarks=row["remarks"],
        rejected=row["rejected"],
        compounds_created=row["compounds_created"],
        compounds_reused=row["compounds_reused"],
        updated_rows=row["updated_rows"],
        record_ids=list(row["record_ids"] or []),
        outcomes=[SupplementRowOutcome(**outcome) for outcome in (row["outcomes"] or [])],
        provenance_state=ProvenanceState(row["provenance_state"]),
        submitted_by=row["submitted_by"],
        created_at=row["created_at"],
        confirmed_at=row["confirmed_at"],
        confirmed_by=row["confirmed_by"],
        repeated_of=repeated,
    )


def list_supplement_imports(
    engine: Engine, target_id: uuid.UUID, *, limit: int = 20, threshold_nm: float = DEFAULT_THRESHOLD_NM
) -> list[SupplementImportReport]:
    """Import runs for one target, newest first, each with its rows as they stand now."""
    with engine.begin() as conn:
        _target_row(conn, target_id)
        ids = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT id FROM supplement_imports WHERE target_id = :tid "
                    "ORDER BY created_at DESC, id LIMIT :limit"
                ),
                {"tid": target_id, "limit": limit},
            ).all()
        ]
        reports: list[SupplementImportReport] = []
        for import_id in ids:
            report = _supplement_import_report(conn, import_id, threshold_nm)
            report.stored = _stored_rows(
                conn, target_id, report.record_ids, report.outcomes, threshold_nm
            )
            reports.append(report)
    return reports


def confirm_supplement_import(
    engine: Engine,
    target_id: uuid.UUID,
    import_id: uuid.UUID,
    *,
    confirmed_by: Optional[str] = None,
) -> SupplementConfirmation:
    """A person has read an import's rows: they become the target's own rows.

    This is the single transition between a proposal and evidence, and it does exactly
    two things: the rows' provenance becomes ``user_curated`` and the live compounds
    join `target_candidates` — the table migration 0015 defines scope by. So the rows
    enter the verdict, the tables, the exports and the summaries together, and a
    half-admitted import is not a state this system can be left in (AGENTS.md §10).
    """
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT provenance_state, confirmed_at, confirmed_by FROM supplement_imports "
                "WHERE id = :id AND target_id = :tid"
            ),
            {"id": import_id, "tid": target_id},
        ).mappings().first()
        if row is None:
            raise NotFoundError(f"Supplement import {import_id} not found for this target")
        import_ids = list(
            conn.execute(
                text("SELECT record_ids FROM supplement_imports WHERE id = :id"),
                {"id": import_id},
            ).scalar()
            or []
        )
        if row["confirmed_at"] is not None:
            # Answering "already confirmed" is not a second confirmation: re-posting a
            # review must not look like a new act (AGENTS.md §22).
            return SupplementConfirmation(
                import_id=import_id,
                target_id=target_id,
                rows=len(import_ids),
                confirmed_at=row["confirmed_at"],
                confirmed_by=row["confirmed_by"],
                already_confirmed=True,
            )

        rows = len(import_ids)
        conn.execute(
            text(
                """
                UPDATE measurements SET provenance_state = 'user_curated'
                 WHERE source_name = :source AND source_record_id = ANY(:ids)
                   AND provenance_state <> 'user_curated'
                """
            ),
            {"source": USER_SUPPLEMENT_SOURCE, "ids": import_ids},
        ).rowcount
        conn.execute(
            text(
                """
                UPDATE target_supplement_remarks SET provenance_state = 'user_curated'
                 WHERE target_id = :tid AND source_record_id = ANY(:ids)
                   AND provenance_state <> 'user_curated'
                """
            ),
            {"tid": target_id, "ids": import_ids},
        )
        # Only live rows of this import join the investigation: a row the reviewer just
        # took back stays taken back (migration 0015).
        candidates = conn.execute(
            text(
                """
                SELECT m.compound_id, m.source_record_id,
                       COALESCE(c.modality, 'unclassified') AS modality
                  FROM measurements m
                  JOIN assays a ON a.id = m.assay_id
                  LEFT JOIN compounds c ON c.id = m.compound_id
                 WHERE a.target_id = :tid AND m.source_name = :source
                   AND m.source_record_id = ANY(:ids)
                   AND m.retracted_at IS NULL AND m.compound_id IS NOT NULL
                """
            ),
            {"tid": target_id, "source": USER_SUPPLEMENT_SOURCE, "ids": import_ids},
        ).mappings().all()
        for candidate in candidates:
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, source_molecule_id,
                                                   evidence_class, modality, retrieval_id,
                                                   dataset_version, retrieved_at)
                    VALUES (:id, :target_id, :compound_id, :source_name,
                            :source_record_id, NULL,
                            :evidence_class, :modality, NULL,
                            :dataset_version, :retrieved_at)
                    ON CONFLICT (target_id, source_name, source_record_id) DO UPDATE
                      SET evidence_class = EXCLUDED.evidence_class,
                          modality = EXCLUDED.modality,
                          retrieved_at = EXCLUDED.retrieved_at,
                          retracted_at = NULL,
                          retracted_reason = NULL
                    """
                ),
                {
                    "id": uuid.uuid5(
                        CANDIDATE_NAMESPACE,
                        f"candidate:{target_id}:{USER_SUPPLEMENT_SOURCE}:"
                        f"{candidate['source_record_id']}",
                    ),
                    "target_id": target_id,
                    "compound_id": candidate["compound_id"],
                    "source_name": USER_SUPPLEMENT_SOURCE,
                    "source_record_id": candidate["source_record_id"],
                    "evidence_class": EvidenceClass.UNSPECIFIED.value,
                    "modality": candidate["modality"],
                    "dataset_version": SUPPLEMENT_DATASET_VERSION,
                    "retrieved_at": datetime.now(timezone.utc),
                },
            )
        confirmed_at = datetime.now(timezone.utc)
        conn.execute(
            text(
                "UPDATE supplement_imports SET confirmed_at = :at, confirmed_by = :by "
                "WHERE id = :id"
            ),
            {"id": import_id, "by": confirmed_by, "at": confirmed_at},
        )
        return SupplementConfirmation(
            import_id=import_id,
            target_id=target_id,
            rows=rows,
            candidates_created=len(candidates),
            confirmed_at=confirmed_at,
            confirmed_by=confirmed_by,
            already_confirmed=False,
        )


def count_unreviewed_supplements(
    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Stored rows no person has asserted, per target (B-25), for the verdict.

    Both kinds are counted, because the reader's question is one question: does this
    target hold rows that a model or a script put there and nobody has read. They are
    reported beside the verdict's counts and never merged into them.
    """
    ids = list(target_ids)
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT target_id, sum(measurements + remarks) AS n FROM (
                    SELECT a.target_id AS target_id, count(*) AS measurements, 0 AS remarks
                    FROM measurements m
                    JOIN assays a ON a.id = m.assay_id
                    WHERE m.source_name = :source AND m.retracted_at IS NULL
                      AND m.provenance_state <> 'user_curated'
                      AND a.target_id = ANY(:tids)
                    GROUP BY a.target_id
                    UNION ALL
                    SELECT target_id, 0, count(*)
                    FROM target_supplement_remarks
                    WHERE target_id = ANY(:tids) AND retracted_at IS NULL
                      AND provenance_state <> 'user_curated'
                    GROUP BY target_id
                ) counts
                GROUP BY target_id
                """
            ),
            {"tids": ids, "source": USER_SUPPLEMENT_SOURCE},
        ).mappings().all()
    return {row["target_id"]: int(row["n"]) for row in rows}
