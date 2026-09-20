from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

from sarmady.epistemic import (
    Claim,
    ClaimRelation,
    Evidence,
    Event,
    ResolvedState,
)
from sarmady.memory import (
    MemoryEntry,
    MemoryLifecycle,
    MemoryLifecycleEvent,
    MemoryLifecycleEventKind,
)

from ._codec import claim_from_row, iso, relation_from_row
from .resolution import HEAD_MOVING_RELATIONS, rebuild_claim_heads, resolve_state


class EpistemicStoreMixin:
    @staticmethod
    def epistemic_dependency_key(subject: str, predicate: str) -> str:
        return f"epistemic-key:{subject}:{predicate}"

    @staticmethod
    def memory_dependency_key(memory_entry_id: UUID) -> str:
        return f"memory-entry:{memory_entry_id}"

    def commit_claim_bundle(
        self,
        *,
        event: Event,
        evidence: Evidence,
        claim: Claim,
        memory: MemoryEntry,
        relation: ClaimRelation | None = None,
    ) -> None:
        """Atomically admit one event/evidence/claim/memory bundle.

        The current head is re-read only after the SQLite write lock is held.
        A stale caller therefore cannot revise an obsolete head after a racing
        writer commits first.
        """

        if evidence.event_id != event.id:
            raise ValueError("evidence must reference the bundled event")
        if evidence.id not in claim.evidence_refs:
            raise ValueError("claim must reference the bundled evidence")
        if memory.target_type != "Claim" or memory.target_id != claim.id:
            raise ValueError("memory entry must target the bundled claim")
        if memory.lifecycle is not MemoryLifecycle.ACTIVE:
            raise ValueError("new memory admission must begin ACTIVE")
        if event.recorded_at != claim.recorded_at or memory.created_at != claim.recorded_at:
            raise ValueError(
                "event, claim, and memory admission must share one recorded_at"
            )
        if relation is not None and relation.recorded_at != claim.recorded_at:
            raise ValueError(
                "claim relation must share the bundled claim recorded_at"
            )
        if evidence.captured_at > claim.recorded_at:
            raise ValueError("evidence cannot be captured after claim admission")
        if claim.valid_from is not None and claim.valid_from > claim.recorded_at:
            raise ValueError(
                "future-valid claims require scheduled activation and are not supported in M1"
            )

        with self._write_transaction():
            current = self.current_claim(claim.subject, claim.predicate)
            if current is None and relation is not None:
                raise ValueError("initial claim cannot revise a missing current claim")
            if current is not None:
                if claim.recorded_at < current.recorded_at:
                    raise ValueError(
                        "new claim recorded_at cannot precede the locked current claim"
                    )
                if relation is None:
                    raise ValueError(
                        "a claim over existing current state requires an explicit relation"
                    )
                if (
                    relation.source_claim_id != claim.id
                    or relation.target_claim_id != current.id
                ):
                    raise ValueError(
                        "revision relation must point from new claim to the locked current claim"
                    )

            for ref in claim.evidence_refs:
                if ref == evidence.id:
                    continue
                referenced_evidence = self.evidence(ref)
                if referenced_evidence is None:
                    raise ValueError(f"claim references unknown evidence {ref}")
                if referenced_evidence.captured_at > claim.recorded_at:
                    raise ValueError(
                        f"claim references evidence captured after claim admission: {ref}"
                    )
                referenced_event = self.db.execute(
                    "SELECT recorded_at FROM events WHERE id = ?",
                    (str(referenced_evidence.event_id),),
                ).fetchone()
                if referenced_event is None:
                    raise ValueError(
                        f"evidence references unknown event {referenced_evidence.event_id}"
                    )
                if datetime.fromisoformat(referenced_event["recorded_at"]) > claim.recorded_at:
                    raise ValueError(
                        f"claim references evidence learned after claim admission: {ref}"
                    )

            self.db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                (
                    str(event.id),
                    event.kind,
                    iso(event.occurred_at),
                    iso(event.recorded_at),
                    json.dumps(dict(event.payload), sort_keys=True),
                ),
            )
            self._log("Event", event.id, event.recorded_at)

            self.db.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?)",
                (
                    str(evidence.id),
                    str(evidence.event_id),
                    evidence.source_ref,
                    iso(evidence.captured_at),
                    evidence.digest,
                ),
            )
            self._log("Evidence", evidence.id, event.recorded_at)

            self.db.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(claim.id),
                    claim.subject,
                    claim.predicate,
                    json.dumps(claim.value, sort_keys=True),
                    iso(claim.recorded_at),
                    json.dumps([str(ref) for ref in claim.evidence_refs]),
                    iso(claim.valid_from),
                    iso(claim.valid_to),
                    str(claim.derivation_ref) if claim.derivation_ref else None,
                ),
            )
            self._log("Claim", claim.id, claim.recorded_at)

            move_head = current is None
            if relation is not None:
                self.db.execute(
                    "INSERT INTO claim_relations VALUES (?, ?, ?, ?, ?)",
                    (
                        str(relation.id),
                        str(relation.source_claim_id),
                        str(relation.target_claim_id),
                        relation.kind.value,
                        iso(relation.recorded_at),
                    ),
                )
                self._log("ClaimRelation", relation.id, relation.recorded_at)
                move_head = relation.kind in HEAD_MOVING_RELATIONS

            if move_head:
                self.db.execute(
                    """
                    INSERT INTO claim_heads(subject, predicate, claim_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(subject, predicate)
                    DO UPDATE SET claim_id = excluded.claim_id
                    """,
                    (claim.subject, claim.predicate, str(claim.id)),
                )

            self.db.execute(
                "INSERT INTO memory_entries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(memory.id),
                    memory.target_type,
                    str(memory.target_id),
                    memory.kind.value,
                    iso(memory.created_at),
                    memory.lifecycle.value,
                ),
            )
            self._log("MemoryEntry", memory.id, memory.created_at)
            self._record_memory_event_in_tx(
                MemoryLifecycleEvent(
                    id=uuid4(),
                    memory_entry_id=memory.id,
                    event_kind=MemoryLifecycleEventKind.CREATED,
                    occurred_at=memory.created_at,
                    source="memory-admission",
                ),
                update_state=False,
            )

            self._invalidate_projection_dependencies_in_tx(
                (self.epistemic_dependency_key(claim.subject, claim.predicate),),
                reason="epistemic-state-changed",
            )

    # --- Epistemic reads and reconstruction ---------------------------------

    def current_claim(self, subject: str, predicate: str) -> Claim | None:
        row = self.db.execute(
            """
            SELECT c.* FROM claim_heads h
            JOIN claims c ON c.id = h.claim_id
            WHERE h.subject = ? AND h.predicate = ?
            """,
            (subject, predicate),
        ).fetchone()
        return claim_from_row(row) if row else None

    def claim(self, claim_id: UUID) -> Claim | None:
        row = self.db.execute(
            "SELECT * FROM claims WHERE id = ?", (str(claim_id),)
        ).fetchone()
        return claim_from_row(row) if row else None

    def claim_history(self, subject: str, predicate: str) -> tuple[Claim, ...]:
        rows = self.db.execute(
            """
            SELECT c.* FROM claims c
            JOIN semantic_log l ON l.kind = 'Claim' AND l.ref_id = c.id
            WHERE c.subject = ? AND c.predicate = ?
            ORDER BY l.seq
            """,
            (subject, predicate),
        ).fetchall()
        return tuple(claim_from_row(row) for row in rows)

    def relation(self, relation_id: UUID) -> ClaimRelation | None:
        row = self.db.execute(
            "SELECT * FROM claim_relations WHERE id = ?", (str(relation_id),)
        ).fetchone()
        return relation_from_row(row) if row else None

    def relations_for(self, claim_id: UUID) -> tuple[ClaimRelation, ...]:
        rows = self.db.execute(
            """
            SELECT r.* FROM claim_relations r
            JOIN semantic_log l ON l.kind = 'ClaimRelation' AND l.ref_id = r.id
            WHERE r.source_claim_id = ? OR r.target_claim_id = ?
            ORDER BY l.seq
            """,
            (str(claim_id), str(claim_id)),
        ).fetchall()
        return tuple(relation_from_row(row) for row in rows)

    def evidence(self, evidence_id: UUID) -> Evidence | None:
        row = self.db.execute(
            "SELECT * FROM evidence WHERE id = ?", (str(evidence_id),)
        ).fetchone()
        if row is None:
            return None
        return Evidence(
            id=UUID(row["id"]),
            event_id=UUID(row["event_id"]),
            source_ref=row["source_ref"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            digest=row["digest"],
        )

    def resolved_state(
        self,
        subject: str,
        predicate: str,
        *,
        known_at: datetime | None = None,
        valid_at: datetime | None = None,
        snapshot_frontier: int | None = None,
    ) -> ResolvedState:
        if snapshot_frontier is None and not self.db.in_transaction:
            with self.read_snapshot() as frontier:
                return resolve_state(
                    self.db,
                    subject,
                    predicate,
                    frontier=frontier,
                    known_at=known_at,
                    valid_at=valid_at,
                )

        if snapshot_frontier is not None:
            if not self.db.in_transaction:
                raise RuntimeError(
                    "snapshot_frontier is valid only inside an active pinned transaction"
                )
            actual_frontier = self.frontier()
            if actual_frontier != snapshot_frontier:
                raise RuntimeError(
                    "snapshot_frontier does not match the active transaction snapshot"
                )
            frontier = actual_frontier
        else:
            frontier = self.frontier()

        return resolve_state(
            self.db,
            subject,
            predicate,
            frontier=frontier,
            known_at=known_at,
            valid_at=valid_at,
        )

    def claim_as_known_at(
        self, subject: str, predicate: str, known_at: datetime
    ) -> ResolvedState:
        return self.resolved_state(subject, predicate, known_at=known_at)

    def claim_valid_at(
        self, subject: str, predicate: str, valid_at: datetime
    ) -> ResolvedState:
        return self.resolved_state(subject, predicate, valid_at=valid_at)

    def rebuild_claim_heads(self) -> int:
        with self._write_transaction():
            return rebuild_claim_heads(self.db)
