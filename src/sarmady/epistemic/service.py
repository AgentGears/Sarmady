from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sarmady.memory import MemoryEntry, MemoryKind
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import Claim, ClaimRelation, ClaimRelationKind, Evidence, Event


_HEAD_MOVING = {ClaimRelationKind.CORRECTS, ClaimRelationKind.SUPERSEDES}


class EpistemicMemoryService:
    """Write-side semantic admission service for M1.

    Extraction remains outside this service. Callers supply an interpreted
    proposition and the explicit relation, if any, to the currently operative
    claim. The service assigns durable semantic objects and commits them
    atomically.
    """

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    @staticmethod
    def _require_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    def observe_claim(
        self,
        *,
        subject: str,
        predicate: str,
        value: Any,
        source_ref: str,
        observed_at: datetime,
        recorded_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        relation_kind: ClaimRelationKind | None = None,
        supersede_current: bool = False,
    ) -> Claim:
        """Admit one observed claim.

        `observed_at` describes the source/world observation time.
        `recorded_at` is when Sarmady learned/admitted the observation and
        defaults to `observed_at` only for callers that do not need the
        distinction yet.

        Existing current state always requires an explicit semantic relation.
        `supersede_current=True` remains a compatibility shorthand for
        `relation_kind=SUPERSEDES`.
        """

        self._require_aware(observed_at, "observed_at")
        recorded_at = recorded_at or observed_at
        self._require_aware(recorded_at, "recorded_at")
        if recorded_at < observed_at:
            raise ValueError("recorded_at cannot precede observed_at")
        if valid_from is not None:
            self._require_aware(valid_from, "valid_from")
        if valid_to is not None:
            self._require_aware(valid_to, "valid_to")

        if supersede_current:
            if relation_kind is not None and relation_kind is not ClaimRelationKind.SUPERSEDES:
                raise ValueError(
                    "supersede_current conflicts with explicit relation_kind"
                )
            relation_kind = ClaimRelationKind.SUPERSEDES

        current = self.store.current_claim(subject, predicate)
        if current is None and relation_kind is not None:
            raise ValueError("cannot relate to current state when no current claim exists")
        if current is not None and relation_kind is None:
            raise ValueError("existing current claim requires an explicit relation choice")

        # M1 claim_heads represent state operative at admission time. Future-valid
        # propositions need scheduled activation semantics, which are deferred.
        if valid_from is not None and valid_from > recorded_at:
            raise ValueError(
                "future-valid claims require scheduled activation and are not supported in M1"
            )

        event = Event(
            id=uuid4(),
            kind="OBSERVATION",
            occurred_at=observed_at,
            recorded_at=recorded_at,
            payload=dict(payload or {}),
        )
        evidence = Evidence(
            id=uuid4(),
            event_id=event.id,
            source_ref=source_ref,
            captured_at=observed_at,
        )
        claim = Claim(
            id=uuid4(),
            subject=subject,
            predicate=predicate,
            value=value,
            recorded_at=recorded_at,
            evidence_refs=(evidence.id,),
            valid_from=valid_from,
            valid_to=valid_to,
        )
        memory = MemoryEntry(
            id=uuid4(),
            target_type="Claim",
            target_id=claim.id,
            kind=MemoryKind.SEMANTIC,
            created_at=recorded_at,
        )

        relation = None
        if current is not None:
            assert relation_kind is not None
            relation = ClaimRelation(
                id=uuid4(),
                source_claim_id=claim.id,
                target_claim_id=current.id,
                kind=relation_kind,
                recorded_at=recorded_at,
            )

        self.store.commit_claim_bundle(
            event=event,
            evidence=evidence,
            claim=claim,
            memory=memory,
            relation=relation,
        )
        return claim
