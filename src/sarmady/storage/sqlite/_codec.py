from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from sarmady.epistemic import Claim, ClaimRelation, ClaimRelationKind
from sarmady.memory import (
    MemoryEntry,
    MemoryKind,
    MemoryLifecycle,
    MemoryLifecycleEvent,
    MemoryLifecycleEventKind,
)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def claim_from_row(row: sqlite3.Row) -> Claim:
    return Claim(
        id=UUID(row["id"]),
        subject=row["subject"],
        predicate=row["predicate"],
        value=json.loads(row["value_json"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        evidence_refs=tuple(
            UUID(value) for value in json.loads(row["evidence_refs_json"])
        ),
        valid_from=dt(row["valid_from"]),
        valid_to=dt(row["valid_to"]),
        derivation_ref=UUID(row["derivation_ref"]) if row["derivation_ref"] else None,
    )


def relation_from_row(row: sqlite3.Row) -> ClaimRelation:
    return ClaimRelation(
        id=UUID(row["id"]),
        source_claim_id=UUID(row["source_claim_id"]),
        target_claim_id=UUID(row["target_claim_id"]),
        kind=ClaimRelationKind(row["kind"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
    )


def memory_from_row(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=UUID(row["id"]),
        target_type=row["target_type"],
        target_id=UUID(row["target_id"]),
        kind=MemoryKind(row["kind"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        lifecycle=MemoryLifecycle(row["lifecycle"]),
    )


def memory_event_from_row(row: sqlite3.Row) -> MemoryLifecycleEvent:
    return MemoryLifecycleEvent(
        id=UUID(row["id"]),
        memory_entry_id=UUID(row["memory_entry_id"]),
        event_kind=MemoryLifecycleEventKind(row["event_kind"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        source=row["source"],
        reason=row["reason"],
    )
