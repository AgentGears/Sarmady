from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sarmady.memory import MemoryEntry, MemoryKind
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import Claim, ClaimRelation, ClaimRelationKind, Evidence, Event


class EpistemicMemoryService:
    """Small write-side service for the M1 vertical slice.

    Extraction is intentionally outside this service. Callers supply an already
    interpreted proposition; this service assigns semantic objects and commits
    them atomically.
    """

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def observe_claim(
        self,
        *,
        subject: str,
        predicate: str,
        value: Any,
        source_ref: str,
        observed_at: datetime,
        payload: Mapping[str, Any] | None = None,
        valid_from: datetime | None = None,
        supersede_current: bool = False,
    ) -> Claim:
        current = self.store.current_claim(subject, predicate)
        if current is not None and not supersede_current:
            raise ValueError("existing current claim requires an explicit revision choice")
        if current is None and supersede_current:
            raise ValueError("cannot supersede when no current claim exists")

        event = Event(
            id=uuid4(),
            kind="OBSERVATION",
            occurred_at=observed_at,
            recorded_at=observed_at,
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
            recorded_at=observed_at,
            evidence_refs=(evidence.id,),
            valid_from=valid_from,
        )
        memory = MemoryEntry(
            id=uuid4(),
            target_type="Claim",
            target_id=claim.id,
            kind=MemoryKind.SEMANTIC,
            created_at=observed_at,
        )
        relation = None
        if current is not None:
            relation = ClaimRelation(
                id=uuid4(),
                source_claim_id=claim.id,
                target_claim_id=current.id,
                kind=ClaimRelationKind.SUPERSEDES,
                recorded_at=observed_at,
            )

        self.store.commit_claim_bundle(
            event=event,
            evidence=evidence,
            claim=claim,
            memory=memory,
            relation=relation,
        )
        return claim
