from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


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


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """Admission of a canonical artifact into long-term recall, not a second truth record."""

    id: UUID
    target_type: str
    target_id: UUID
    kind: MemoryKind
    created_at: datetime
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE


@dataclass(frozen=True, slots=True)
class MemoryLifecycleEvent:
    id: UUID
    memory_entry_id: UUID
    event_kind: str
    occurred_at: datetime
    source: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryHealthSnapshot:
    """Derived policy output. Health is distinct from relevance, utility, and truth."""

    memory_entry_id: UUID
    computed_at: datetime
    policy_id: str
    health: float
    seen_count: int
    used_count: int
