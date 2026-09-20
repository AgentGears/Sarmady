from __future__ import annotations

import json
from copy import copy, deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.context import (
    ContextProjection,
    ContextRequest,
    CoverageStatus,
    ExactContextCompiler,
)
from sarmady.epistemic import Claim, Evidence, Event
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.memory import MemoryEntry, MemoryKind
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.values import FrozenMapping


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _MutableValue:
    pass


class _JsonSerializingAdapter:
    binding_id = "fake:json-serializing"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        json.dumps([item.payload for item in model_input.items])
        return ModelResponse("answer", "ok")


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


def test_frozen_mapping_reinitialization_cannot_replace_admitted_state() -> None:
    claim = Claim(
        uuid4(),
        "subject",
        "predicate",
        {"value": 1, "nested": {"state": "original"}},
        T0,
    )
    admitted = claim.value
    assert isinstance(admitted, FrozenMapping)

    FrozenMapping.__init__(
        admitted,
        {"value": 2, "nested": {"state": "replacement"}},
    )

    assert admitted["value"] == 1
    assert admitted["nested"]["state"] == "original"


def test_frozen_mapping_exposes_no_mutable_backing_attributes() -> None:
    claim = Claim(uuid4(), "subject", "predicate", {"value": 1}, T0)
    admitted = claim.value
    assert isinstance(admitted, FrozenMapping)

    with pytest.raises(AttributeError):
        object.__setattr__(admitted, "_items", (("value", 2),))
    with pytest.raises(AttributeError):
        object.__setattr__(admitted, "_index", {"value": 2})

    assert admitted["value"] == 1


def test_frozen_mapping_supports_standard_copy_and_asdict_protocols() -> None:
    claim = Claim(
        uuid4(),
        "subject",
        "predicate",
        {"value": 1, "nested": {"labels": ["a", "b"]}},
        T0,
    )

    shallow = copy(claim)
    deep = deepcopy(claim)
    serialized = asdict(claim)

    assert shallow == claim
    assert deep == claim
    assert isinstance(deep.value, FrozenMapping)
    assert deep.value["nested"]["labels"] == ("a", "b")
    assert serialized["value"]["value"] == 1
    assert serialized["value"]["nested"]["labels"] == ("a", "b")


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


def test_mapping_claim_is_json_serializable_at_model_adapter_boundary(tmp_path) -> None:
    path = tmp_path / "adapter-json.db"
    with SQLiteCanonicalStore(path) as store:
        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="profile",
            value={"hardware": {"ram_gb": 64}, "labels": ["primary"]},
            source_ref="seed:profile",
            observed_at=T0,
        )
        agent = Agent(uuid4(), "Sarmady", T0)
        store.register_agent(agent)
        projection = ExactContextCompiler(store).compile(
            ContextRequest(uuid4(), "machine profile", 1024),
            subject="machine:primary",
            predicate="profile",
        )

        artifact = CognitiveRuntime(
            store, clock=lambda: T0 + timedelta(minutes=1)
        ).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="summarize-profile",
            adapter=_JsonSerializingAdapter(),
        )

        assert artifact.content == "ok"


def test_projection_registration_rejects_future_frontier(tmp_path) -> None:
    path = tmp_path / "future-frontier.db"
    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), "future snapshot", 512)
        future_frontier = store.frontier() + 1
        projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{future_frontier}",
            canonical_frontier=str(future_frontier),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:future-frontier",
            compiler_version="test",
        )

        with pytest.raises(ValueError, match="cannot exceed current frontier"):
            store.register_context_projection(
                projection,
                request=request,
                dependency_keys=(),
            )

        assert store.context_request(request.id) is None
        assert store.context_projection(projection.id) is None


def test_projection_registration_rejects_negative_frontier(tmp_path) -> None:
    path = tmp_path / "negative-frontier.db"
    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), "impossible snapshot", 512)
        projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id="sqlite:-1",
            canonical_frontier="-1",
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:negative-frontier",
            compiler_version="test",
        )

        with pytest.raises(ValueError, match="cannot be negative"):
            store.register_context_projection(
                projection,
                request=request,
                dependency_keys=(),
            )

        assert store.context_request(request.id) is None
        assert store.context_projection(projection.id) is None
