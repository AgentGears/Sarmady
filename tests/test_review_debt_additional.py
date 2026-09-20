from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.context import ContextRequest
from sarmady.epistemic import Claim, Evidence, Event
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.memory import MemoryEntry, MemoryKind
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.values import FrozenMapping


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _MutableValue:
    pass


def test_canonical_value_boundary_rejects_non_json_mutables() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        Claim(uuid4(), "subject", "predicate", _MutableValue(), T0)


def test_unbound_dict_mutators_cannot_bypass_frozen_mapping() -> None:
    claim = Claim(uuid4(), "subject", "predicate", {"value": 1}, T0)
    assert isinstance(claim.value, FrozenMapping)
    with pytest.raises(TypeError):
        dict.__setitem__(claim.value, "value", 2)
    assert claim.value["value"] == 1


def test_preconstructed_frozen_mapping_detaches_mutable_descendants() -> None:
    original = ["before"]
    wrapped = FrozenMapping({"items": original})
    claim = Claim(uuid4(), "subject", "predicate", wrapped, T0)

    original.append("after")
    assert claim.value["items"] == ("before",)


def test_new_context_request_still_requires_positive_latency_budget() -> None:
    with pytest.raises(ValueError, match="latency_budget_ms must be positive"):
        ContextRequest(uuid4(), "new request", 512, latency_budget_ms=-1)


def test_claim_cannot_reference_evidence_learned_after_claim_admission(tmp_path) -> None:
    path = tmp_path / "knowledge-time-evidence.db"
    with SQLiteCanonicalStore(path) as store:
        later_known_claim = EpistemicMemoryService(store).observe_claim(
            subject="sensor:late",
            predicate="reading",
            value=1,
            source_ref="late-source",
            observed_at=T0,
            recorded_at=T0 + timedelta(hours=2),
        )
        later_known_evidence_id = later_known_claim.evidence_refs[0]

        event = Event(uuid4(), "OBSERVATION", T0, T0 + timedelta(hours=1), {})
        evidence = Evidence(uuid4(), event.id, "present-source", T0)
        claim = Claim(
            uuid4(),
            "machine:primary",
            "memory_gb",
            64,
            T0 + timedelta(hours=1),
            (evidence.id, later_known_evidence_id),
        )
        memory = MemoryEntry(
            uuid4(), "Claim", claim.id, MemoryKind.SEMANTIC, T0 + timedelta(hours=1)
        )

        with pytest.raises(ValueError, match="learned after claim admission"):
            store.commit_claim_bundle(
                event=event, evidence=evidence, claim=claim, memory=memory
            )
