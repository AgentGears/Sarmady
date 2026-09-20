from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from sarmady.values import freeze_value


class EffectStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    PROVIDER_ACKNOWLEDGED = "PROVIDER_ACKNOWLEDGED"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"
    CONFIRMED = "CONFIRMED"
    NO_EFFECT = "NO_EFFECT"
    REVERSED = "REVERSED"


@dataclass(frozen=True, slots=True)
class ActionIntent:
    id: UUID
    principal_id: UUID
    capability: str
    fingerprint: str
    parameters: Mapping[str, Any]
    proposed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze_value(self.parameters))


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    id: UUID
    action_intent_id: UUID
    started_at: datetime
    idempotency_key: str | None = None
    completed_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class Effect:
    id: UUID
    action_intent_id: UUID
    status: EffectStatus
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EffectEvidence:
    id: UUID
    effect_id: UUID
    source: str
    observed_at: datetime
    digest: str | None = None


def effect_allows_automatic_retry(effect: Effect) -> bool:
    """Only proven NO_EFFECT is intrinsically safe to retry at the semantic level.

    Provider-specific idempotency may add stronger guarantees, but UNKNOWN_EFFECT
    is never interpreted as NO_EFFECT here.
    """

    return effect.status is EffectStatus.NO_EFFECT
