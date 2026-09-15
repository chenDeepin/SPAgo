"""Project save/read services (Milestone 1 + product readiness PROD-03).

Saving is idempotent: re-saving the same scope never duplicates rows. The
response tells the caller whether rows were newly created or already present.

Version contract (PROD-03): the dataset versions of a saved scope are derived
server-side from the rows actually saved — a client-supplied version label is
never trusted. Each item stores an identity snapshot (inchikey, canonical
SMILES) and the full version list at save time; reading joins the live rows
only to detect and report drift, never to silently replace the saved meaning.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.services import NotFoundError


@dataclass(frozen=True)
class ProjectSummary:
    id: uuid.UUID
    name: str
    description: str | None
    item_count: int
    created_at: str


@dataclass(frozen=True)
class ProjectItem:
    id: uuid.UUID
    #: A saved patent item names its family; a saved target candidate does not
    #: (ONLINE-00 C: a compound with no patent mapping is still savable).
    family_id: uuid.UUID | None
    family_key: str | None
    compound_id: uuid.UUID | None
    inchikey: str | None
    canonical_smiles: str | None
    dataset_version: str
    dataset_versions: list[dict] = field(default_factory=list)
    # Drift reporting (PROD-03): the saved reference stays readable even when
    # the underlying data changed or was replaced.
    record_missing: bool = False
    source_updated: bool = False
    added_at: str = ""
    # --- ONLINE-00: candidate scope -----------------------------------------
    target_id: uuid.UUID | None = None
    target_key: str | None = None
    target_name: str | None = None
    evidence_class: str | None = None


class ProjectScopeError(ValueError):
    """A requested save scope is not valid for the stated owner/object."""


@dataclass(frozen=True)
class SaveResult:
    created_rows: int
    already_present_rows: int
    scope_family: bool
    dataset_versions: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSaveResult:
    created_rows: int
    already_present_rows: int
    target_key: str
    dataset_versions: list[dict] = field(default_factory=list)


def require_project(conn, project_id: uuid.UUID, owner_id: uuid.UUID | None) -> None:
    """Fail closed when a project is not the caller's (ONLINE-03, ADR-0002).

    A project belonging to another owner, or an unassigned legacy project in
    hosted mode, is reported as not found: distinguishing "not yours" from
    "does not exist" would leak the existence of other users' projects.
    """
    row = conn.execute(
        text(
            """
            SELECT id FROM projects
            WHERE id = :id
              AND ((CAST(:owner AS uuid) IS NULL AND owner_id IS NULL) OR owner_id = :owner)
            """
        ),
        {"id": project_id, "owner": owner_id},
    ).first()
    if row is None:
        raise NotFoundError(f"Project {project_id} not found")


def create_project(
    engine: Engine,
    name: str,
    description: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> ProjectSummary:
    pid = uuid.uuid4()
    with engine.begin() as conn:
        # Names are unique per owner: two scientists may each have a "TSLP
        # screen". Unassigned legacy rows keep their global uniqueness.
        row = conn.execute(
            text(
                """
                INSERT INTO projects (id, name, description, owner_id)
                VALUES (:id, :name, :description, :owner)
                ON CONFLICT DO NOTHING
                RETURNING id, name, description, created_at
                """
            ),
            {"id": pid, "name": name, "description": description, "owner": owner_id},
        ).mappings().first()
        if row is None:
            row = conn.execute(
                text(
                    """
                    SELECT id, name, description, created_at FROM projects
                    WHERE name = :name
                      AND ((CAST(:owner AS uuid) IS NULL AND owner_id IS NULL) OR owner_id = :owner)
                    """
                ),
                {"name": name, "owner": owner_id},
            ).mappings().first()
            if row is None:
                raise ProjectScopeError(
                    "A project with this name already exists in another workspace; "
                    "choose a different name."
                )
            conn.execute(
                text("UPDATE projects SET description = COALESCE(:d, description) WHERE id = :id"),
                {"d": description, "id": row["id"]},
            )
        count = conn.execute(
            text("SELECT count(*) FROM project_items WHERE project_id = :id"),
            {"id": row["id"]},
        ).scalar_one()
    return ProjectSummary(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        item_count=int(count),
        created_at=row["created_at"].isoformat(),
    )


def list_projects(engine: Engine, owner_id: uuid.UUID | None = None) -> list[ProjectSummary]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT p.id, p.name, p.description, p.created_at,
                       count(i.id) AS item_count
                FROM projects p
                LEFT JOIN project_items i ON i.project_id = p.id
                WHERE ((CAST(:owner AS uuid) IS NULL AND p.owner_id IS NULL) OR p.owner_id = :owner)
                GROUP BY p.id
                ORDER BY p.created_at
                """
            ),
            {"owner": owner_id},
        ).mappings().all()
    return [
        ProjectSummary(
            id=r["id"],
            name=r["name"],
            description=r["description"],
            item_count=int(r["item_count"]),
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


def _as_version_list(value) -> list[dict]:
    if isinstance(value, (str, bytes, bytearray)):
        value = json.loads(value)
    return value or []


def get_project(
    engine: Engine, project_id: uuid.UUID, owner_id: uuid.UUID | None = None
) -> tuple[ProjectSummary, list[ProjectItem]]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT p.id, p.name, p.description, p.created_at,
                       count(i.id) AS item_count
                FROM projects p
                LEFT JOIN project_items i ON i.project_id = p.id
                WHERE p.id = :id
                  AND ((CAST(:owner AS uuid) IS NULL AND p.owner_id IS NULL) OR p.owner_id = :owner)
                GROUP BY p.id
                """
            ),
            {"id": project_id, "owner": owner_id},
        ).mappings().first()
        if row is None:
            raise NotFoundError(f"Project {project_id} not found")
        item_rows = conn.execute(
            text(
                """
                SELECT i.id, i.family_id, COALESCE(i.family_key, f.family_key) AS family_key, i.compound_id,
                       COALESCE(i.inchikey, c.inchikey) AS inchikey,
                       COALESCE(i.canonical_smiles, c.canonical_smiles) AS canonical_smiles,
                       i.dataset_version, i.dataset_versions, i.added_at,
                       c.id AS live_compound_id, f.id AS live_family_id,
                       c.inchikey AS live_inchikey, c.canonical_smiles AS live_smiles,
                       c.dataset_version AS live_version, i.compound_dataset_version,
                       i.target_id, i.target_key, i.target_name, i.evidence_class,
                       t.id AS live_target_id,
                       EXISTS (
                           SELECT 1 FROM current_compound_mentions m
                           JOIN patent_documents d ON d.id = m.document_id
                           WHERE m.compound_id = i.compound_id AND d.family_id = i.family_id
                       ) AS live_membership,
                       (SELECT COALESCE(jsonb_agg(v ORDER BY v.dataset_version, v.source_name), '[]'::jsonb)
                        FROM (
                            SELECT DISTINCT d.source_name, d.dataset_version
                            FROM patent_documents d
                            WHERE d.family_id = i.family_id AND i.compound_id IS NULL
                            UNION
                            SELECT DISTINCT m.source_name, m.dataset_version
                            FROM current_compound_mentions m
                            JOIN patent_documents d ON d.id = m.document_id
                            WHERE d.family_id = i.family_id AND m.compound_id = i.compound_id
                        ) v) AS live_versions
                FROM project_items i
                LEFT JOIN patent_families f ON f.id = i.family_id
                LEFT JOIN compounds c ON c.id = i.compound_id
                LEFT JOIN targets t ON t.id = i.target_id
                WHERE i.project_id = :id
                ORDER BY i.added_at, i.id
                """
            ),
            {"id": project_id},
        ).mappings().all()
    items = [
        ProjectItem(
            id=r["id"],
            family_id=r["family_id"],
            family_key=r["family_key"],
            compound_id=r["compound_id"],
            inchikey=r["inchikey"],
            canonical_smiles=r["canonical_smiles"],
            dataset_version=r["dataset_version"],
            dataset_versions=_as_version_list(r["dataset_versions"]),
            # A selected-compound item whose live row vanished stays readable
            # through its saved snapshot; the drift is reported, not hidden.
            # Candidate items (no family) are missing when their compound or
            # target row is gone, by the same rule.
            record_missing=(
                (r["family_id"] is not None and r["live_family_id"] is None)
                or (r["family_id"] is None and (r["live_target_id"] is None or r["live_compound_id"] is None))
                or (r["family_id"] is not None
                    and r["compound_id"] is not None
                    and (r["live_compound_id"] is None or not r["live_membership"]))
            ),
            source_updated=(
                r["family_id"] is not None
                and r["live_family_id"] is not None
                and (
                    (r["dataset_versions"] is not None
                     and _as_version_list(r["dataset_versions"]) != _as_version_list(r["live_versions"]))
                    or (r["dataset_versions"] is None and r["dataset_version"] not in ("mixed", "unknown")
                        and r["dataset_version"] != _version_label(_as_version_list(r["live_versions"])))
                    or (r["compound_id"] is not None and r["live_compound_id"] is not None
                        and (r["inchikey"] != r["live_inchikey"]
                             or r["canonical_smiles"] != r["live_smiles"]
                             or (r["compound_dataset_version"] is not None
                                 and r["compound_dataset_version"] != r["live_version"])))
                )
            ),
            added_at=r["added_at"].isoformat(),
            target_id=r["target_id"],
            target_key=r["target_key"],
            target_name=r["target_name"],
            evidence_class=r["evidence_class"],
        )
        for r in item_rows
    ]
    summary = ProjectSummary(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        item_count=int(row["item_count"]),
        created_at=row["created_at"].isoformat(),
    )
    return summary, items


def _derive_family_versions(conn, family_id: uuid.UUID) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT source_name, dataset_version
            FROM patent_documents WHERE family_id = :fid
            ORDER BY dataset_version, source_name
            """
        ),
        {"fid": family_id},
    ).all()
    return [{"source_name": r[0], "dataset_version": r[1]} for r in rows]


def _derive_compound_versions(conn, family_id: uuid.UUID, compound_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    # compounds carry only dataset_version; the source name lives on the
    # mentions that linked the compound into this dataset.
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT m.compound_id, m.source_name, m.dataset_version
            FROM current_compound_mentions m
            JOIN patent_documents d ON d.id = m.document_id
            WHERE m.compound_id = ANY(:ids) AND d.family_id = :fid
            ORDER BY m.compound_id, m.dataset_version, m.source_name
            """
        ),
        {"ids": compound_ids, "fid": family_id},
    ).all()
    versions: dict[uuid.UUID, list[dict]] = {}
    for cid, source, version in rows:
        versions.setdefault(cid, []).append({"source_name": source, "dataset_version": version})
    return versions


def _version_label(versions: list[dict]) -> str:
    labels = sorted({v["dataset_version"] for v in versions})
    if not labels:
        return "unknown"
    return labels[0] if len(labels) == 1 else "mixed"


def save_scope(
    engine: Engine,
    project_id: uuid.UUID,
    family_id: uuid.UUID,
    compound_ids: list[uuid.UUID] | None,
    dataset_version: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> SaveResult:
    """Persist a family-wide save (compound_ids None/empty) or selected compounds.

    Verifies the family and every compound belong to the family's data before
    writing. Re-saving an existing scope changes nothing (idempotent). Dataset
    versions are derived from the saved rows server-side; the client label
    argument is accepted for request compatibility and ignored (PROD-03)."""
    from spago_core.services import get_family_overview  # local import to avoid cycle

    overview = get_family_overview(engine, family_id)  # raises NotFoundError

    with engine.begin() as conn:
        require_project(conn, project_id, owner_id)

        created = 0
        already = 0
        versions: list[dict] = []
        if not compound_ids:
            versions = _derive_family_versions(conn, family_id)
            label = _version_label(versions)
            result = conn.execute(
                text(
                    """
                    INSERT INTO project_items (id, project_id, family_id, family_key, compound_id,
                                               dataset_version, dataset_versions)
                    VALUES (:id, :pid, :fid, :fkey, NULL, :dv, CAST(:dvs AS jsonb))
                    ON CONFLICT (project_id, family_id) WHERE compound_id IS NULL DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": project_id,
                    "fid": family_id,
                    "fkey": overview.family.family_key,
                    "dv": label,
                    "dvs": json.dumps(versions),
                },
            ).first()
            if result is None:
                exists = conn.execute(
                    text(
                        """
                        SELECT dataset_versions FROM project_items
                        WHERE project_id = :pid AND family_id = :fid AND compound_id IS NULL
                        """
                    ),
                    {"pid": project_id, "fid": family_id},
                ).first()
                if exists:
                    already = 1
                    versions = _as_version_list(exists[0])
            else:
                created = 1
        else:
            member_ids = {d.id for d in overview.documents}
            valid = conn.execute(
                text(
                    """
                    SELECT DISTINCT m.compound_id FROM current_compound_mentions m
                    WHERE m.compound_id = ANY(:ids)
                      AND m.document_id = ANY(:doc_ids)
                    """
                ),
                {"ids": compound_ids, "doc_ids": list(member_ids)},
            ).scalars().all()
            unknown = set(compound_ids) - set(valid)
            if unknown:
                raise NotFoundError(
                    f"{len(unknown)} selected compound(s) are not in family {overview.family.family_key}"
                )
            compound_ids = list(dict.fromkeys(compound_ids))
            versions_by_id = _derive_compound_versions(conn, family_id, compound_ids)
            snapshots = conn.execute(
                text(
                    "SELECT id, inchikey, canonical_smiles, dataset_version FROM compounds WHERE id = ANY(:ids)"
                ),
                {"ids": list(compound_ids)},
            ).mappings().all()
            snapshot_by_id = {r["id"]: r for r in snapshots}
            for cid in compound_ids:
                snapshot = snapshot_by_id[cid]
                item_versions = versions_by_id.get(cid, [])
                label = _version_label(item_versions)
                result = conn.execute(
                    text(
                        """
                        INSERT INTO project_items (id, project_id, family_id, family_key, compound_id,
                                                   inchikey, canonical_smiles, compound_dataset_version,
                                                   dataset_version, dataset_versions)
                        VALUES (:id, :pid, :fid, :fkey, :cid, :ik, :smi, :cdv, :dv, CAST(:dvs AS jsonb))
                        ON CONFLICT (project_id, family_id, compound_id) WHERE compound_id IS NOT NULL DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "pid": project_id,
                        "fid": family_id,
                        "cid": cid,
                        "fkey": overview.family.family_key,
                        "ik": snapshot["inchikey"],
                        "smi": snapshot["canonical_smiles"],
                        "cdv": snapshot["dataset_version"],
                        "dv": label,
                        "dvs": json.dumps(item_versions),
                    },
                ).first()
                if result is None:
                    already += 1
                    saved = conn.execute(
                        text("SELECT dataset_versions FROM project_items "
                             "WHERE project_id = :pid AND family_id = :fid AND compound_id = :cid"),
                        {"pid": project_id, "fid": family_id, "cid": cid},
                    ).scalar_one()
                    item_versions = _as_version_list(saved)
                else:
                    created += 1
                versions.extend(item_versions)
            versions = [dict(source_name=source, dataset_version=version)
                        for version, source in sorted({
                            (v["dataset_version"], v["source_name"]) for v in versions
                        })]
    return SaveResult(
        created_rows=created,
        already_present_rows=already,
        scope_family=not compound_ids,
        dataset_versions=versions,
    )


def remove_item(
    engine: Engine,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    owner_id: uuid.UUID | None = None,
) -> None:
    with engine.begin() as conn:
        require_project(conn, project_id, owner_id)
        result = conn.execute(
            text("DELETE FROM project_items WHERE id = :iid AND project_id = :pid"),
            {"iid": item_id, "pid": project_id},
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Item {item_id} not found in project {project_id}")


def save_candidates(
    engine: Engine,
    project_id: uuid.UUID,
    target_id: uuid.UUID,
    compound_ids: list[uuid.UUID],
    evidence_class: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> CandidateSaveResult:
    """Save target candidates, including compounds with no patent occurrence.

    Scope is verified server-side: every compound must be a recorded candidate
    of *this* target, so a project cannot be filled with unrelated ids. The item
    keeps the target scope, the source versions of the retrieval that produced
    it, and an identity snapshot, so reopening the project still shows what was
    saved even if the external source later changes (ONLINE-00 C).
    """
    with engine.begin() as conn:
        require_project(conn, project_id, owner_id)

        target = conn.execute(
            text(
                """
                SELECT t.id, t.target_key, t.name, t.dataset_version,
                       (SELECT count(DISTINCT tc.compound_id) FROM target_candidates tc
                         WHERE tc.target_id = t.id AND tc.compound_id = ANY(:ids)) AS matches
                FROM targets t WHERE t.id = :tid
                """
            ),
            {"tid": target_id, "ids": list(compound_ids)},
        ).mappings().first()
        if target is None:
            raise NotFoundError(f"Target {target_id} not found")
        if int(target["matches"]) != len(set(compound_ids)):
            raise ProjectScopeError(
                "One or more compounds are not recorded candidates of this target; "
                "refresh the investigation before saving."
            )

        versions = [
            {"source_name": r[0], "dataset_version": r[1]}
            for r in conn.execute(
                text(
                    """
                    SELECT DISTINCT source_name, dataset_version
                    FROM source_retrievals
                    WHERE target_id = :tid AND dataset_version IS NOT NULL
                    ORDER BY dataset_version, source_name
                    """
                ),
                {"tid": target_id},
            ).all()
        ]
        label = _version_label(versions) if versions else (target["dataset_version"] or "unknown")

        snapshots = {
            r["id"]: r
            for r in conn.execute(
                text(
                    "SELECT id, inchikey, canonical_smiles, dataset_version FROM compounds "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": list(compound_ids)},
            ).mappings().all()
        }
        created = 0
        already = 0
        for compound_id in dict.fromkeys(compound_ids):
            snapshot = snapshots.get(compound_id)
            if snapshot is None:
                raise ProjectScopeError(f"Compound {compound_id} no longer exists in the data.")
            per_item_class = evidence_class or _candidate_evidence_class(
                conn, target_id, compound_id
            )
            result = conn.execute(
                text(
                    """
                    INSERT INTO project_items (id, project_id, family_id, target_id,
                                               candidate_id, target_key, target_name,
                                               evidence_class, compound_id, inchikey,
                                               canonical_smiles, compound_dataset_version,
                                               dataset_version, dataset_versions)
                    VALUES (:id, :pid, NULL, :tid, :cand, :tkey, :tname,
                            :eclass, :cid, :ik, :smi, :cdv, :dv, CAST(:dvs AS jsonb))
                    ON CONFLICT (project_id, target_id, compound_id)
                        WHERE family_id IS NULL AND compound_id IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": project_id,
                    "tid": target_id,
                    "cand": _candidate_id(conn, target_id, compound_id),
                    "tkey": target["target_key"],
                    "tname": target["name"],
                    "eclass": per_item_class,
                    "cid": compound_id,
                    "ik": snapshot["inchikey"],
                    "smi": snapshot["canonical_smiles"],
                    "cdv": snapshot["dataset_version"],
                    "dv": label,
                    "dvs": json.dumps(versions),
                },
            ).first()
            if result is None:
                already += 1
            else:
                created += 1
    return CandidateSaveResult(
        created_rows=created,
        already_present_rows=already,
        target_key=target["target_key"],
        dataset_versions=versions,
    )


def _candidate_id(conn, target_id: uuid.UUID, compound_id: uuid.UUID):
    """The stable candidate id for a (target, compound) pair.

    `min(uuid)` is not a PostgreSQL aggregate, so the row is selected explicitly.
    A pair can legitimately have several candidate rows (one per source), and any
    of them identifies the same scientific object; the lowest id is chosen so the
    reference is deterministic.
    """
    return conn.execute(
        text(
            "SELECT id FROM target_candidates WHERE target_id = :tid AND compound_id = :cid "
            "ORDER BY id LIMIT 1"
        ),
        {"tid": target_id, "cid": compound_id},
    ).scalar()


def _candidate_evidence_class(conn, target_id: uuid.UUID, compound_id: uuid.UUID) -> str | None:
    """The strongest evidence class recorded for this candidate.

    Ordered conservatively: a measured direct binding outranks an interaction
    disruption readout, which outranks a functional effect, which outranks a
    screening hit. The stored label is a summary of what exists, never a claim
    that the compound inhibits the target.
    """
    order = [
        "measured_direct_binding",
        "interaction_disruption",
        "functional_effect",
        "screening_assay",
        "computational_prediction",
        "unspecified",
    ]
    rows = conn.execute(
        text(
            "SELECT DISTINCT coalesce(evidence_class, 'unspecified') AS c "
            "FROM target_candidates WHERE target_id = :tid AND compound_id = :cid"
        ),
        {"tid": target_id, "cid": compound_id},
    ).scalars().all()
    for candidate in order:
        if candidate in rows:
            return candidate
    return "unspecified" if rows else None
