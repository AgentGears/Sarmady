from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AdoptedOutput:
    id: UUID
    source_artifact_id: UUID
    adopted_at: datetime
    rendering_directive: str | None = None


@dataclass(frozen=True, slots=True)
class PresentationAttempt:
    id: UUID
    adopted_output_id: UUID
    target_ref: str
    attempted_at: datetime


@dataclass(frozen=True, slots=True)
class PresentationReceipt:
    id: UUID
    presentation_attempt_id: UUID
    confirmed_at: datetime
    provider_ref: str | None = None
