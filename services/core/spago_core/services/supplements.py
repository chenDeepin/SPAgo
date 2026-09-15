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
    SupplementImport,
    SupplementRemark,
    SupplementRow,
    SupplementRowOutcome,
    USER_SUPPLEMENT_SOURCE,
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
) -> SupplementRowOutcome:
    """Keep a structure-less row as a remark (never as a compound)."""
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
                  patent_number = EXCLUDED.patent_number
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
            "provenance_state": ProvenanceState.USER_CURATED.value,
            "dataset_version": SUPPLEMENT_DATASET_VERSION,
        },
    )
    reasons = [
        "stored without a structure: no public SMILES was supplied, so the row is "
        "kept as a remark with its potency and cannot be drawn or exported as a compound"
    ]
    if row.value is None:
        reasons.append("no value was supplied, so this row carries only the note")
    return SupplementRowOutcome(
        index=index, status="remark", name=row.name.strip(), reasons=reasons
    )


def import_supplements(
    engine: Engine,
    target_id: uuid.UUID,
    rows: Sequence[Mapping[str, Any]],
    *,
    threshold_nm: float = DEFAULT_THRESHOLD_NM,
) -> SupplementImport:
    """Store user-added literature rows for one target.

    Each row is validated on its own, so one bad row cannot refuse the batch, and
    every row is answered for in the result.
    """
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
                outcomes.append(
                    _store_remark(conn, target, row, index, _row_id(target_key, row, ""))
                )
                result.remarks += 1
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
                                'user_curated', NULL,
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
                            provenance_state = EXCLUDED.provenance_state,
                            dataset_version = EXCLUDED.dataset_version,
                            raw_value = EXCLUDED.raw_value,
                            assay_description = EXCLUDED.assay_description,
                            document_ref = EXCLUDED.document_ref,
                            document_doi = EXCLUDED.document_doi,
                            document_pmid = EXCLUDED.document_pmid,
                            document_patent_number = EXCLUDED.document_patent_number,
                            retrieved_at = EXCLUDED.retrieved_at
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
                          retrieved_at = EXCLUDED.retrieved_at
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
                    compound_id=compound_id,
                    inchikey=candidate.inchikey,
                    activity_class=activity_class,
                    reused_compound=candidate.inchikey in pre_existing,
                    reasons=reasons,
                )
            )

    result.rows = sorted(outcomes, key=lambda outcome: outcome.index)
    return result


def list_supplement_remarks(engine: Engine, target_id: uuid.UUID) -> list[SupplementRemark]:
    """Stored structure-less rows for one target (newest first)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, target_id, source_record_id, name, note, activity_type, value,
                       unit, relation, doi, pmid, patent_number, provenance_state,
                       created_at
                FROM target_supplement_remarks
                WHERE target_id = :tid
                ORDER BY created_at DESC, name
                """
            ),
            {"tid": target_id},
        ).mappings().all()
    return [SupplementRemark(**dict(row)) for row in rows]


def count_supplement_remarks(
    engine: Engine, target_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Stored remark count per target, for the reference verdict."""
    ids = list(target_ids)
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT target_id, count(*) AS n FROM target_supplement_remarks "
                "WHERE target_id = ANY(:tids) GROUP BY target_id"
            ),
            {"tids": ids},
        ).mappings().all()
    return {row["target_id"]: int(row["n"]) for row in rows}
