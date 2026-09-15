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
    family_id: uuid.UUID
    family_key: str
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


@dataclass(frozen=True)
class SaveResult:
    created_rows: int
    already_present_rows: int
    scope_family: bool
    dataset_versions: list[dict] = field(default_factory=list)


def create_project(engine: Engine, name: str, description: str | None = None) -> ProjectSummary:
    pid = uuid.uuid4()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO projects (id, name, description)
                VALUES (:id, :name, :description)
                ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description
                RETURNING id, name, description, created_at
                """
            ),
            {"id": pid, "name": name, "description": description},
        ).mappings().first()
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


def list_projects(engine: Engine) -> list[ProjectSummary]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT p.id, p.name, p.description, p.created_at,
                       count(i.id) AS item_count
                FROM projects p
                LEFT JOIN project_items i ON i.project_id = p.id
                GROUP BY p.id
                ORDER BY p.created_at
                """
            )
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


def get_project(engine: Engine, project_id: uuid.UUID) -> tuple[ProjectSummary, list[ProjectItem]]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT p.id, p.name, p.description, p.created_at,
                       count(i.id) AS item_count
                FROM projects p
                LEFT JOIN project_items i ON i.project_id = p.id
                WHERE p.id = :id
                GROUP BY p.id
                """
            ),
            {"id": project_id},
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
                       EXISTS (
                           SELECT 1 FROM compound_mentions m
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
                            FROM compound_mentions m
                            JOIN patent_documents d ON d.id = m.document_id
                            WHERE d.family_id = i.family_id AND m.compound_id = i.compound_id
                        ) v) AS live_versions
                FROM project_items i
                LEFT JOIN patent_families f ON f.id = i.family_id
                LEFT JOIN compounds c ON c.id = i.compound_id
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
            record_missing=(
                r["live_family_id"] is None
                or (r["compound_id"] is not None
                    and (r["live_compound_id"] is None or not r["live_membership"]))
            ),
            source_updated=(
                r["live_family_id"] is not None
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
            FROM compound_mentions m
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
) -> SaveResult:
    """Persist a family-wide save (compound_ids None/empty) or selected compounds.

    Verifies the family and every compound belong to the family's data before
    writing. Re-saving an existing scope changes nothing (idempotent). Dataset
    versions are derived from the saved rows server-side; the client label
    argument is accepted for request compatibility and ignored (PROD-03)."""
    from spago_core.services import get_family_overview  # local import to avoid cycle

    overview = get_family_overview(engine, family_id)  # raises NotFoundError

    with engine.begin() as conn:
        proj = conn.execute(
            text("SELECT id FROM projects WHERE id = :id"), {"id": project_id}
        ).first()
        if proj is None:
            raise NotFoundError(f"Project {project_id} not found")

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
                    SELECT DISTINCT m.compound_id FROM compound_mentions m
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


def remove_item(engine: Engine, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM project_items WHERE id = :iid AND project_id = :pid"),
            {"iid": item_id, "pid": project_id},
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Item {item_id} not found in project {project_id}")
