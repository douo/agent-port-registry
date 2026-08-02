"""SQLite connection, migrations, and transaction helpers."""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")

#: Version represented by schema.sql on its own (the Local v1 baseline).
BASELINE_SCHEMA_VERSION = 1

_MIGRATION_NAME = re.compile(r"^(\d+)_[A-Za-z0-9_.\-]*\.sql$")


def discover_migrations() -> list[tuple[int, Path]]:
    """Return [(version, path), ...] ascending, from ``migrations/NNN_*.sql``."""
    if not MIGRATIONS_DIR.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            continue
        version = int(match.group(1))
        if version <= BASELINE_SCHEMA_VERSION:
            raise ValueError(
                f"Migration {path.name} must use a version above the baseline "
                f"({BASELINE_SCHEMA_VERSION}); schema.sql owns everything up to it."
            )
        found.append((version, path))
    found.sort(key=lambda item: item[0])
    versions = [v for v, _ in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"Duplicate migration version under {MIGRATIONS_DIR}")
    return found


def latest_schema_version() -> int:
    migrations = discover_migrations()
    return migrations[-1][0] if migrations else BASELINE_SCHEMA_VERSION


#: Schema version this build expects: baseline plus every bundled migration.
CURRENT_SCHEMA_VERSION = latest_schema_version()


class Database:
    """Thin wrapper around a SQLite database file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,  # manual transactions
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self.migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def migrate(self) -> None:
        """Apply the baseline schema, then every pending incremental migration."""
        with self._lock:
            # schema.sql is all CREATE IF NOT EXISTS: a no-op on existing databases,
            # and it is what creates schema_version on a fresh one.
            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            self._conn.executescript(schema_sql)
            row = self._conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)",
                    (BASELINE_SCHEMA_VERSION,),
                )
                current = BASELINE_SCHEMA_VERSION
            else:
                current = int(row["version"])

            for version, path in discover_migrations():
                if version <= current:
                    continue
                self._apply_migration(version, path)
                current = version

    def _apply_migration(self, version: int, path: Path) -> None:
        """Run one migration and bump schema_version in the same transaction."""
        sql = path.read_text(encoding="utf-8")
        # executescript() would COMMIT any pending transaction before running, so
        # transaction control has to live inside the script itself.
        script = (
            f"BEGIN;\n{sql}\nUPDATE schema_version SET version = {version};\nCOMMIT;"
        )
        try:
            self._conn.executescript(script)
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE transaction (serialize writers)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq: list) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executemany(sql, seq)

    def fetchone(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())
