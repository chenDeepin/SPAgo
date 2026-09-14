"""Project save/read services (Milestone 1).

Saving is idempotent: re-saving the same scope never duplicates rows. The
response tells the caller whether rows were newly created or already present.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

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
    added_at: str


@dataclass(frozen=True)
class SaveResult:
    created_rows: int
    already_present_rows: int
    scope_family: bool


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
                SELECT i.id, i.family_id, f.family_key, i.compound_id,
                       c.inchikey, c.canonical_smiles, i.dataset_version, i.added_at
                FROM project_items i
                JOIN patent_families f ON f.id = i.family_id
                LEFT JOIN compounds c ON c.id = i.compound_id
                WHERE i.project_id = :id
                ORDER BY i.added_at, c.inchikey
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


def save_scope(
    engine: Engine,
    project_id: uuid.UUID,
    family_id: uuid.UUID,
    compound_ids: list[uuid.UUID] | None,
    dataset_version: str,
) -> SaveResult:
    """Persist a family-wide save (compound_ids None/empty) or selected compounds.

    Verifies the family and every compound belong to the family's data before
    writing. Re-saving an existing scope changes nothing (idempotent).
    """
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
        if not compound_ids:
            result = conn.execute(
                text(
                    """
                    INSERT INTO project_items (id, project_id, family_id, compound_id, dataset_version)
                    VALUES (:id, :pid, :fid, NULL, :dv)
                    ON CONFLICT (project_id, family_id) WHERE compound_id IS NULL DO NOTHING
                    RETURNING id
                    """
                ),
                {"id": uuid.uuid4(), "pid": project_id, "fid": family_id, "dv": dataset_version},
            ).first()
            if result is None:
                exists = conn.execute(
                    text(
                        """
                        SELECT 1 FROM project_items
                        WHERE project_id = :pid AND family_id = :fid AND compound_id IS NULL
                        """
                    ),
                    {"pid": project_id, "fid": family_id},
                ).first()
                if exists:
                    already = 1
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
            for cid in compound_ids:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO project_items (id, project_id, family_id, compound_id, dataset_version)
                        VALUES (:id, :pid, :fid, :cid, :dv)
                        ON CONFLICT (project_id, family_id, compound_id) WHERE compound_id IS NOT NULL DO NOTHING
                        RETURNING id
                        """
                    ),
                    {"id": uuid.uuid4(), "pid": project_id, "fid": family_id, "cid": cid, "dv": dataset_version},
                ).first()
                if result is None:
                    already += 1
                else:
                    created += 1
    return SaveResult(created_rows=created, already_present_rows=already, scope_family=not compound_ids)


def remove_item(engine: Engine, project_id: uuid.UUID, item_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM project_items WHERE id = :iid AND project_id = :pid"),
            {"iid": item_id, "pid": project_id},
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Item {item_id} not found in project {project_id}")
