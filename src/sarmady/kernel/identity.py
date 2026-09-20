from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Agent:
    """Persistent artificial identity, independent of any model binding."""

    id: UUID
    name: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("agent name is required")
        _require_aware(self.created_at, "created_at")
