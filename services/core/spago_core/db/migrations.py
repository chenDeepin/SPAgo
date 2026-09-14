"""Plain-SQL versioned migration runner (ADR-0001 decision 4).

Migrations are ordered `NNNN_name.sql` files in the migrations directory.
Applied versions are recorded in `schema_migrations`. Forward-only: never edit
an applied migration, add a new one.
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

_VERSION_RE = re.compile(r"^(\d+)_.*\.sql$")


def _migration_files(migrations_dir: Path) -> list[tuple[int, Path]]:
    if not migrations_dir.is_dir():
        raise FileNotFoundError(
            f"Migrations directory not found: {migrations_dir} "
            "(set SPAGO_MIGRATIONS_DIR; silently skipping migrations would corrupt state)"
        )
    files: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _VERSION_RE.match(path.name)
        if not match:
            raise ValueError(f"Migration file name must be 'NNNN_name.sql': {path.name}")
        files.append((int(match.group(1)), path))
    return files


def applied_versions(engine: Engine) -> set[int]:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     integer PRIMARY KEY,
                    filename    text NOT NULL,
                    applied_at  timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {int(r[0]) for r in rows}


def run_migrations(engine: Engine, migrations_dir: Path) -> list[int]:
    """Apply all pending migrations in order; returns versions applied this run."""
    pending = [
        (version, path)
        for version, path in _migration_files(migrations_dir)
        if version not in applied_versions(engine)
    ]
    for version, path in pending:
        sql = path.read_text()
        with engine.begin() as conn:
            conn.execute(text(sql))
            conn.execute(
                text("INSERT INTO schema_migrations (version, filename) VALUES (:v, :f)"),
                {"v": version, "f": path.name},
            )
    return [version for version, _ in pending]
