from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import UUID

from ._codec import iso
from .cognitive_store import CognitiveStoreMixin
from .epistemic_store import EpistemicStoreMixin
from .identity_store import IdentityStoreMixin
from .memory_store import MemoryStoreMixin
from .projection_store import ProjectionStoreMixin
from .schema import initialize_schema


class SQLiteCanonicalStore(IdentityStoreMixin, EpistemicStoreMixin, MemoryStoreMixin, ProjectionStoreMixin, CognitiveStoreMixin):
    """SQLite adapter for Sarmady's canonical M1 semantic state."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        initialize_schema(self.db)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SQLiteCanonicalStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self.db.in_transaction:
            raise RuntimeError("nested write transaction is not supported")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    @contextmanager
    def read_snapshot(self) -> Iterator[int]:
        """Pin all reads in the block to one SQLite WAL snapshot."""

        if self.db.in_transaction:
            raise RuntimeError("nested read snapshot is not supported")
        self.db.execute("BEGIN")
        try:
            frontier = self.frontier()
            yield frontier
        finally:
            self.db.rollback()

    def _log(self, kind: str, ref_id: UUID, recorded_at: datetime) -> None:
        self.db.execute(
            "INSERT INTO semantic_log(kind, ref_id, recorded_at) VALUES (?, ?, ?)",
            (kind, str(ref_id), iso(recorded_at)),
        )

    def frontier(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS frontier FROM semantic_log"
        ).fetchone()
        return int(row["frontier"])
