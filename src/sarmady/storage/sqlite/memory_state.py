from __future__ import annotations

from sarmady.memory import MemoryLifecycle, MemoryLifecycleEventKind

from .errors import CanonicalIntegrityError


def next_memory_state(
    current: MemoryLifecycle,
    event_kind: MemoryLifecycleEventKind,
) -> MemoryLifecycle:
    if event_kind in {
        MemoryLifecycleEventKind.CREATED,
        MemoryLifecycleEventKind.SEEN,
        MemoryLifecycleEventKind.USED,
        MemoryLifecycleEventKind.CONSOLIDATED,
    }:
        return current

    if event_kind is MemoryLifecycleEventKind.ARCHIVED:
        if current is not MemoryLifecycle.ACTIVE:
            raise CanonicalIntegrityError("only ACTIVE memory can be archived")
        return MemoryLifecycle.ARCHIVED

    if event_kind is MemoryLifecycleEventKind.RESTORED:
        if current is not MemoryLifecycle.ARCHIVED:
            raise CanonicalIntegrityError("only ARCHIVED memory can be restored")
        return MemoryLifecycle.ACTIVE

    if event_kind is MemoryLifecycleEventKind.TOMBSTONED:
        if current not in {MemoryLifecycle.ACTIVE, MemoryLifecycle.ARCHIVED}:
            raise CanonicalIntegrityError(
                "only ACTIVE or ARCHIVED memory can be tombstoned"
            )
        return MemoryLifecycle.TOMBSTONED

    if event_kind is MemoryLifecycleEventKind.DELETED:
        if current is not MemoryLifecycle.TOMBSTONED:
            raise CanonicalIntegrityError(
                "memory must be TOMBSTONED before DELETED"
            )
        return MemoryLifecycle.DELETED

    raise CanonicalIntegrityError(f"unsupported lifecycle event {event_kind}")
