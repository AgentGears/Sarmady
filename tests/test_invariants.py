from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import DecisionRecord, GeneratedArtifact
from sarmady.context import ContextItem, ContextProjection, ContextRequest, CoverageStatus
from sarmady.epistemic import Claim, Evidence
from sarmady.kernel import (
    Approval,
    Effect,
    EffectStatus,
    approval_authorizes,
    effect_allows_automatic_retry,
)
from sarmady.memory import MemoryEntry, MemoryKind


NOW = datetime.now(UTC)


def test_evidence_and_claim_are_distinct_semantic_objects() -> None:
    evidence = Evidence(uuid4(), uuid4(), "user:statement", NOW)
    claim = Claim(uuid4(), "machine:primary", "memory_gb", 64, NOW, (evidence.id,))
    assert claim.evidence_refs == (evidence.id,)
    assert claim.id != evidence.id


def test_memory_entry_references_truth_instead_of_copying_it() -> None:
    claim_id = uuid4()
    memory = MemoryEntry(uuid4(), "Claim", claim_id, MemoryKind.SEMANTIC, NOW)
    assert memory.target_id == claim_id
    assert not hasattr(memory, "value")


def test_context_projection_is_immutable_and_snapshot_bound() -> None:
    request = ContextRequest(uuid4(), "What is the current memory?", token_budget=1024)
    projection = ContextProjection(
        id=uuid4(),
        request_id=request.id,
        snapshot_id="snapshot-7",
        canonical_frontier="frontier-42",
        items=(ContextItem("Claim", uuid4(), "essential_now"),),
        coverage_status=CoverageStatus.COMPLETE,
        manifest_digest="sha256:abc",
        compiler_version="context-v0.1",
    )
    with pytest.raises(FrozenInstanceError):
        projection.snapshot_id = "snapshot-8"  # type: ignore[misc]


def test_action_bound_approval_cannot_authorize_a_different_action() -> None:
    approval = Approval(uuid4(), uuid4(), "action:abc", NOW, NOW + timedelta(minutes=5))
    assert approval_authorizes(approval, "action:abc", NOW)
    assert not approval_authorizes(approval, "action:def", NOW)


def test_unknown_effect_is_not_safe_for_automatic_retry() -> None:
    unknown = Effect(uuid4(), uuid4(), EffectStatus.UNKNOWN_EFFECT, NOW)
    no_effect = Effect(uuid4(), uuid4(), EffectStatus.NO_EFFECT, NOW)
    assert not effect_allows_automatic_retry(unknown)
    assert effect_allows_automatic_retry(no_effect)


def test_generated_artifact_and_adopted_decision_are_not_the_same_object() -> None:
    artifact = GeneratedArtifact(uuid4(), uuid4(), "proposal", "ESCALATE", NOW)
    decision = DecisionRecord(uuid4(), "execution", "ESCALATE", NOW, (artifact.id,))
    assert decision.source_artifact_refs == (artifact.id,)
    assert decision.id != artifact.id
