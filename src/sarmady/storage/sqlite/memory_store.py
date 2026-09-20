from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sarmady.memory import (
    MemoryEntry,
    MemoryLifecycle,
    MemoryLifecycleEvent,
    MemoryLifecycleEventKind,
)

from ._codec import iso, memory_event_from_row, memory_from_row
from .errors import CanonicalIntegrityError
from .memory_state import next_memory_state


class MemoryStoreMixin:
    def memory_entry(self, memory_entry_id: UUID) -> MemoryEntry | None:
        row = self.db.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (str(memory_entry_id),)
        ).fetchone()
        return memory_from_row(row) if row else None

    def memory_entry_for_target(
        self, target_type: str, target_id: UUID
    ) -> MemoryEntry | None:
        row = self.db.execute(
            """
            SELECT * FROM memory_entries
            WHERE target_type = ? AND target_id = ?
            LIMIT 1
            """,
            (target_type, str(target_id)),
        ).fetchone()
        return memory_from_row(row) if row else None

    def active_memory_entry_for_target(
        self, target_type: str, target_id: UUID
    ) -> MemoryEntry | None:
        row = self.db.execute(
            """
            SELECT * FROM memory_entries
            WHERE target_type = ? AND target_id = ? AND lifecycle = ?
            LIMIT 1
            """,
            (target_type, str(target_id), MemoryLifecycle.ACTIVE.value),
        ).fetchone()
        return memory_from_row(row) if row else None

    def is_active_memory_target(self, target_type: str, target_id: UUID) -> bool:
        return self.active_memory_entry_for_target(target_type, target_id) is not None

    def memory_lifecycle_events(
        self, memory_entry_id: UUID
    ) -> tuple[MemoryLifecycleEvent, ...]:
        rows = self.db.execute(
            """
            SELECT e.* FROM memory_lifecycle_events e
            JOIN semantic_log l
              ON l.kind = 'MemoryLifecycleEvent' AND l.ref_id = e.id
            WHERE e.memory_entry_id = ?
            ORDER BY l.seq
            """,
            (str(memory_entry_id),),
        ).fetchall()
        return tuple(memory_event_from_row(row) for row in rows)

    def memory_access_counts(self, memory_entry_id: UUID) -> tuple[int, int]:
        row = self.db.execute(
            """
            SELECT
              SUM(CASE WHEN event_kind = ? THEN 1 ELSE 0 END) AS seen_count,
              SUM(CASE WHEN event_kind = ? THEN 1 ELSE 0 END) AS used_count
            FROM memory_lifecycle_events
            WHERE memory_entry_id = ?
            """,
            (
                MemoryLifecycleEventKind.SEEN.value,
                MemoryLifecycleEventKind.USED.value,
                str(memory_entry_id),
            ),
        ).fetchone()
        return int(row["seen_count"] or 0), int(row["used_count"] or 0)

    def record_memory_event(
        self,
        memory_entry_id: UUID,
        event_kind: MemoryLifecycleEventKind,
        *,
        occurred_at: datetime,
        source: str,
        reason: str | None = None,
    ) -> MemoryLifecycleEvent:
        if event_kind is MemoryLifecycleEventKind.CREATED:
            raise ValueError("CREATED is emitted only by memory admission")

        event = MemoryLifecycleEvent(
            id=uuid4(),
            memory_entry_id=memory_entry_id,
            event_kind=event_kind,
            occurred_at=occurred_at,
            source=source,
            reason=reason,
        )
        with self._write_transaction():
            self._record_memory_event_in_tx(event, update_state=True)
        return event

    def _record_memory_event_in_tx(
        self, event: MemoryLifecycleEvent, *, update_state: bool
    ) -> None:
        entry = self.memory_entry(event.memory_entry_id)
        if entry is None:
            raise ValueError(f"unknown memory entry {event.memory_entry_id}")

        next_state = entry.lifecycle
        if update_state:
            try:
                next_state = next_memory_state(entry.lifecycle, event.event_kind)
            except CanonicalIntegrityError as exc:
                raise ValueError(str(exc)) from exc

        self.db.execute(
            """
            INSERT INTO memory_lifecycle_events
            (id, memory_entry_id, event_kind, occurred_at, source, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.id),
                str(event.memory_entry_id),
                event.event_kind.value,
                iso(event.occurred_at),
                event.source,
                event.reason,
            ),
        )
        self._log("MemoryLifecycleEvent", event.id, event.occurred_at)

        if next_state is not entry.lifecycle:
            self.db.execute(
                "UPDATE memory_entries SET lifecycle = ? WHERE id = ?",
                (next_state.value, str(event.memory_entry_id)),
            )
            self._invalidate_projection_dependencies_in_tx(
                (self.memory_dependency_key(event.memory_entry_id),),
                reason=f"memory-lifecycle:{event.event_kind.value}",
            )

    def rebuild_memory_lifecycle_states(self) -> int:
        """Rebuild mutable lifecycle columns from canonical lifecycle events."""

        with self._write_transaction():
            entries = self.db.execute(
                "SELECT id FROM memory_entries ORDER BY rowid"
            ).fetchall()
            for row in entries:
                entry_id = UUID(row["id"])
                events = self.memory_lifecycle_events(entry_id)
                if not events:
                    raise CanonicalIntegrityError(
                        f"memory entry {entry_id} has no CREATED lifecycle event"
                    )
                if events[0].event_kind is not MemoryLifecycleEventKind.CREATED:
                    raise CanonicalIntegrityError(
                        f"memory entry {entry_id} does not begin with CREATED"
                    )

                state = MemoryLifecycle.ACTIVE
                for event in events[1:]:
                    state = next_memory_state(state, event.event_kind)

                self.db.execute(
                    "UPDATE memory_entries SET lifecycle = ? WHERE id = ?",
                    (state.value, str(entry_id)),
                )
            return len(entries)
