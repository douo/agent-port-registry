"""SQLite connection and transaction helpers."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


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
        self.initialize()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def initialize(self) -> None:
        """Create the one current schema.

        APR has not released a stable database format, so development schema
        changes replace this baseline instead of accumulating compatibility
        migrations.
        """
        with self._lock:
            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            self._conn.executescript(schema_sql)
            # CREATE TABLE IF NOT EXISTS does not add columns to an existing
            # development database. Keep this additive sync next to the single
            # current schema instead of introducing a migration history.
            service_columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(services)")
            }
            if "auto_start" not in service_columns:
                self._conn.execute(
                    "ALTER TABLE services ADD COLUMN auto_start "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            forward_columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(port_forwards)")
            }
            if "auto_start" not in forward_columns:
                self._conn.execute(
                    "ALTER TABLE port_forwards ADD COLUMN auto_start "
                    "INTEGER NOT NULL DEFAULT 1"
                )
                # Preserve the old intent: stopped legacy rules were disabled,
                # while every other rule was restored after an APR restart.
                self._conn.execute(
                    "UPDATE port_forwards SET auto_start = 0 WHERE state = 'stopped'"
                )

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
