from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class MemoryKind(str, Enum):
    SEMANTIC = "SEMANTIC"
    EPISODIC = "EPISODIC"
    SOURCE = "SOURCE"
    PROCEDURAL = "PROCEDURAL"
    DECISION = "DECISION"
    EXPERIENTIAL = "EXPERIENTIAL"


class MemoryLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    TOMBSTONED = "TOMBSTONED"
    DELETED = "DELETED"


class MemoryAccessKind(str, Enum):
    SEEN = "SEEN"
    USED = "USED"


class MemoryLifecycleEventKind(str, Enum):
    CREATED = "CREATED"
    SEEN = "SEEN"
    USED = "USED"
    CONSOLIDATED = "CONSOLIDATED"
    ARCHIVED = "ARCHIVED"
    RESTORED = "RESTORED"
    TOMBSTONED = "TOMBSTONED"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """Admission of a canonical artifact into long-term recall, not a second truth record."""

    id: UUID
    target_type: str
    target_id: UUID
    kind: MemoryKind
    created_at: datetime
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE

    def __post_init__(self) -> None:
        if not self.target_type:
            raise ValueError("target_type is required")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class MemoryLifecycleEvent:
    id: UUID
    memory_entry_id: UUID
    event_kind: MemoryLifecycleEventKind
    occurred_at: datetime
    source: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source is required")
        _require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class MemoryHealthSnapshot:
    """Derived policy output. Health is distinct from relevance, utility, and truth."""

    memory_entry_id: UUID
    computed_at: datetime
    policy_id: str
    health: float
    seen_count: int
    used_count: int
