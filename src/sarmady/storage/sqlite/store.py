from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from ._codec import iso
from .cognitive_store import CognitiveStoreMixin
from .epistemic_store import EpistemicStoreMixin
from .identity_store import IdentityStoreMixin
from .memory_store import MemoryStoreMixin
from .projection_store import ProjectionStoreMixin, _UNPROVEN_CONTEXT_DEPENDENCY
from .reasoning_store import ReasoningStoreMixin
from .schema import initialize_schema


@dataclass(slots=True)
class _ContextDependencyCapture:
    frontier: int
    _store: Any = field(repr=False)
    _store_token: object = field(repr=False)
    _keys: set[str] = field(default_factory=set, repr=False)
    _closed: bool = field(default=False, repr=False)
    _consumed: bool = field(default=False, repr=False)

    def resolved_state(
        self,
        subject: str,
        predicate: str,
        *,
        known_at: datetime | None = None,
        valid_at: datetime | None = None,
    ):
        self._keys.add(self._store.epistemic_dependency_key(subject, predicate))
        return self._store.resolved_state(
            subject,
            predicate,
            known_at=known_at,
            valid_at=valid_at,
            snapshot_frontier=self.frontier,
        )

    def claim(self, claim_id: UUID):
        return self._store.claim(claim_id)

    def evidence(self, evidence_id: UUID):
        return self._store.evidence(evidence_id)

    def memory_entry_for_target(self, target_type: str, target_id: UUID):
        entry = self._store.memory_entry_for_target(target_type, target_id)
        if entry is not None:
            self._keys.add(self._store.memory_dependency_key(entry.id))
        return entry

    def is_active_memory_target(self, target_type: str, target_id: UUID) -> bool:
        entry = self._store.memory_entry_for_target(target_type, target_id)
        if entry is not None:
            self._keys.add(self._store.memory_dependency_key(entry.id))
        return self._store.is_active_memory_target(target_type, target_id)

    @property
    def dependency_keys(self) -> tuple[str, ...]:
        if not self._closed:
            raise RuntimeError(
                "context dependency keys are available only after the snapshot closes"
            )
        return tuple(sorted(self._keys))


class SQLiteCanonicalStore(
    IdentityStoreMixin,
    EpistemicStoreMixin,
    MemoryStoreMixin,
    ProjectionStoreMixin,
    ReasoningStoreMixin,
    CognitiveStoreMixin,
):
    """SQLite adapter for Sarmady's canonical semantic and cognitive state."""

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
        self._context_dependency_token = object()
        self._active_context_dependency_capture: _ContextDependencyCapture | None = None

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

    @contextmanager
    def context_read_snapshot(self) -> Iterator[_ContextDependencyCapture]:
        """Pin context reads and capture their semantic dependencies.

        Context compilers must perform semantic reads through the yielded
        snapshot proxy. The resulting one-shot capture proves which dependency
        keys were actually consulted and can therefore support dependency-aware
        registration without trusting a caller-supplied declaration.
        """

        if self._active_context_dependency_capture is not None:
            raise RuntimeError("nested context dependency capture is not supported")

        with self.read_snapshot() as frontier:
            capture = _ContextDependencyCapture(
                frontier=frontier,
                _store=self,
                _store_token=self._context_dependency_token,
            )
            self._active_context_dependency_capture = capture
            try:
                yield capture
            finally:
                self._active_context_dependency_capture = None
                capture._closed = True

    def _consume_context_dependency_capture(
        self,
        capture: object | None,
        *,
        frontier: int,
    ) -> frozenset[str] | None:
        if capture is None:
            return None
        if not isinstance(capture, _ContextDependencyCapture):
            raise ValueError("invalid context dependency capture")
        if capture._store_token is not self._context_dependency_token:
            raise ValueError("context dependency capture belongs to another store")
        if not capture._closed:
            raise ValueError("context dependency capture is still active")
        if capture._consumed:
            raise ValueError("context dependency capture has already been consumed")
        if capture.frontier != frontier:
            raise ValueError(
                "context dependency capture frontier does not match projection frontier"
            )
        capture._consumed = True
        return frozenset(capture._keys)

    def _log(self, kind: str, ref_id: UUID, recorded_at: datetime) -> None:
        cursor = self.db.execute(
            "INSERT INTO semantic_log(kind, ref_id, recorded_at) VALUES (?, ?, ?)",
            (kind, str(ref_id), iso(recorded_at)),
        )
        semantic_frontier = int(cursor.lastrowid)
        self.db.execute(
            """
            UPDATE context_projections
            SET stale = 1,
                stale_reason = 'unproven-lineage-semantic-state-changed',
                stale_at_frontier = ?
            WHERE stale = 0
              AND id IN (
                SELECT projection_id
                FROM context_projection_dependencies
                WHERE dependency_key = ?
              )
            """,
            (semantic_frontier, _UNPROVEN_CONTEXT_DEPENDENCY),
        )

    def frontier(self) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS frontier FROM semantic_log"
        ).fetchone()
        return int(row["frontier"])
