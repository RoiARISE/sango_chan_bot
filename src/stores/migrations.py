"""A very small, dependency-free migration runner for SQLite.

Each migration is applied once and recorded in ``schema_migrations``. The runner
is deliberately tiny because the project only needs ordered, append-only
migrations; it is not a general-purpose migration framework.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MigrationFunc = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunc


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def run_migrations(
    conn: sqlite3.Connection, migrations: Iterable[Migration]
) -> None:
    """Apply every migration that has not been recorded yet.

    Migrations run in ascending version order. Each migration and its version
    row are committed together so a failure cannot mark a migration as applied.
    """

    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)

    for migration in sorted(migrations, key=lambda item: item.version):
        if migration.version in applied:
            continue

        logger.info(
            "マイグレーションを適用します: %d %s",
            migration.version,
            migration.name,
        )
        conn.execute("BEGIN")
        try:
            migration.apply(conn)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(
                "マイグレーションに失敗しました: %d %s",
                migration.version,
                migration.name,
            )
            raise
