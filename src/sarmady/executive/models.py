from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class WorkRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class Goal:
    id: UUID
    description: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    goal_id: UUID | None
    description: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Commitment:
    id: UUID
    task_id: UUID
    principal_id: UUID
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class WorkRun:
    id: UUID
    task_id: UUID
    status: WorkRunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
