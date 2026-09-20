from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    id: UUID
    principal_id: UUID
    capability: str
    scope: str
    granted_at: datetime
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Approval:
    id: UUID
    principal_id: UUID
    action_fingerprint: str
    approved_at: datetime
    expires_at: datetime | None = None


def approval_authorizes(approval: Approval, action_fingerprint: str, now: datetime) -> bool:
    if approval.action_fingerprint != action_fingerprint:
        return False
    if approval.expires_at is not None and now > approval.expires_at:
        return False
    return True
