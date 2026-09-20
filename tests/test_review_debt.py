from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import ReasoningMode, ReasoningPolicy
from sarmady.context import ContextProjection, ContextRequest, CoverageStatus, ExactContextCompiler
from sarmady.epistemic import Claim, ClaimRelationKind, Evidence, Event
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import ActionIntent, Agent
from sarmady.memory import MemoryEntry, MemoryHealthSnapshot, MemoryKind
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_canonical_claim_and_event_values_are_deeply_detached_and_immutable() -> None:
    original_value = {"parts": [1, {"nested": "before"}]}
    original_payload = {"utterances": ["before"]}
    event = Event(uuid4(), "OBSERVATION", T0, T0, original_payload)
    evidence = Evidence(uuid4(), event.id, "user:statement", T0)
    claim = Claim(
        uuid4(),
        "machine:primary",
        "profile",
        original_value,
        T0,
        (evidence.id,),
    )

    original_value["parts"][1]["nested"] = "after"
    original_payload["utterances"].append("after")

    assert claim.value["parts"][1]["nested"] == "before"
    assert event.payload["utterances"] == ("before",)
    with pytest.raises(TypeError, match="immutable"):
        claim.value["new"] = "mutation"
    with pytest.raises(TypeError, match="immutable"):
        claim.value["parts"][1]["nested"] = "mutation"


def test_action_parameters_are_deeply_frozen_after_fingerprint_binding() -> None:
    parameters = {"event": {"title": "original"}, "attendees": ["a@example.com"]}
    action = ActionIntent(
        uuid4(),
        uuid4(),
        "calendar.create",
        "sha256:bound-action",
        parameters,
        T0,
    )

    parameters["event"]["title"] = "mutated"
    parameters["attendees"].append("b@example.com")

    assert action.parameters["event"]["title"] == "original"
    assert action.parameters["attendees"] == ("a@example.com",)
    with pytest.raises(TypeError, match="immutable"):
        action.parameters["event"]["title"] = "mutated again"


def test_memory_health_snapshot_remains_publicly_exported() -> None:
    assert MemoryHealthSnapshot.__name__ == "MemoryHealthSnapshot"


def test_projection_registration_ignores_unrelated_frontier_advances(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="seed:a",
            observed_at=T0,
        )
        request = ContextRequest(uuid4(), "current RAM", 512)
        with store.context_read_snapshot() as snapshot:
            frontier = snapshot.frontier
            snapshot.resolved_state("machine:primary", "memory_gb")
            projection = ContextProjection(
                id=uuid4(),
                request_id=request.id,
                snapshot_id=f"sqlite:{frontier}",
                canonical_frontier=str(frontier),
                items=(),
                coverage_status=CoverageStatus.INSUFFICIENT,
                manifest_digest="sha256:test-unrelated",
                compiler_version="test",
            )

        service.observe_claim(
            subject="user:primary",
            predicate="timezone",
            value="Asia/Riyadh",
            source_ref="seed:b",
            observed_at=T0 + timedelta(minutes=1),
        )

        stale = store.register_context_projection(
            projection,
            request=request,
            dependency_capture=snapshot,
        )
        assert not stale
        assert not store.projection_is_stale(projection.id)


def test_projection_registration_detects_related_dependency_change(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="seed:a",
            observed_at=T0,
        )
        request = ContextRequest(uuid4(), "current RAM", 512)
        with store.context_read_snapshot() as snapshot:
            frontier = snapshot.frontier
            snapshot.resolved_state("machine:primary", "memory_gb")
            projection = ContextProjection(
                id=uuid4(),
                request_id=request.id,
                snapshot_id=f"sqlite:{frontier}",
                canonical_frontier=str(frontier),
                items=(),
                coverage_status=CoverageStatus.INSUFFICIENT,
                manifest_digest="sha256:test-related",
                compiler_version="test",
            )

        service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="upgrade",
            observed_at=T0 + timedelta(minutes=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        stale = store.register_context_projection(
            projection,
            request=request,
            dependency_capture=snapshot,
        )
        assert stale
        assert store.projection_stale_reason(projection.id) == "dependency-changed-before-registration"


def test_projection_registration_rejects_unproven_advanced_lineage(tmp_path) -> None:
    path = tmp_path / "unproven-lineage.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="seed:a",
            observed_at=T0,
        )
        frontier = store.frontier()
        request = ContextRequest(uuid4(), "current RAM", 512)
        projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:test-unproven",
            compiler_version="external-test",
        )

        service.observe_claim(
            subject="user:primary",
            predicate="timezone",
            value="Asia/Riyadh",
            source_ref="seed:b",
            observed_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(ValueError, match="requires captured dependency lineage"):
            store.register_context_projection(
                projection,
                request=request,
                dependency_keys=(
                    store.epistemic_dependency_key("machine:primary", "memory_gb"),
                ),
            )

        assert store.context_request(request.id) is None
        assert store.context_projection(projection.id) is None


def test_unproven_current_projection_is_conservatively_invalidated(tmp_path) -> None:
    path = tmp_path / "unproven-wildcard.db"
    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), "manual context", 512)
        frontier = store.frontier()
        projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:test-wildcard",
            compiler_version="external-test",
        )
        stale = store.register_context_projection(
            projection,
            request=request,
            dependency_keys=(),
        )
        assert not stale

        EpistemicMemoryService(store).observe_claim(
            subject="unrelated:subject",
            predicate="value",
            value=1,
            source_ref="seed:unrelated",
            observed_at=T0,
        )

        assert store.projection_is_stale(projection.id)


def test_claim_cannot_reference_preexisting_future_evidence(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        future_claim = EpistemicMemoryService(store).observe_claim(
            subject="sensor:future",
            predicate="reading",
            value=1,
            source_ref="future-source",
            observed_at=T0 + timedelta(hours=2),
        )
        future_evidence_id = future_claim.evidence_refs[0]

        event = Event(uuid4(), "OBSERVATION", T0, T0, {})
        evidence = Evidence(uuid4(), event.id, "present-source", T0)
        claim = Claim(
            uuid4(),
            "machine:primary",
            "memory_gb",
            64,
            T0,
            (evidence.id, future_evidence_id),
        )
        memory = MemoryEntry(uuid4(), "Claim", claim.id, MemoryKind.SEMANTIC, T0)

        with pytest.raises(ValueError, match="captured after claim admission"):
            store.commit_claim_bundle(event=event, evidence=evidence, claim=claim, memory=memory)
        assert store.claim(claim.id) is None


class _RecordingAdapter:
    binding_id = "fake:coverage"

    def __init__(self) -> None:
        self.input: ModelInput | None = None

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        self.input = model_input
        return ModelResponse("answer", "insufficient acknowledged")


class _NonStringAdapter:
    binding_id = "fake:non-string"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        return ModelResponse("answer", 123)  # type: ignore[arg-type]


def test_model_input_preserves_projection_coverage_metadata(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent = Agent(uuid4(), "Sarmady", T0)
        store.register_agent(agent)
        request = ContextRequest(uuid4(), "unknown fact", 512)
        projection = ExactContextCompiler(store).compile(
            request,
            subject="missing:subject",
            predicate="missing_predicate",
        )
        assert projection.coverage_status is CoverageStatus.INSUFFICIENT
        adapter = _RecordingAdapter()

        CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1)).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-unknown-fact",
            adapter=adapter,
        )

        assert adapter.input is not None
        assert adapter.input.coverage_status is CoverageStatus.INSUFFICIENT
        assert adapter.input.unresolved_gaps == projection.unresolved_gaps
        assert adapter.input.omitted_refs == projection.omitted_refs


def test_non_string_model_response_is_rejected_and_durably_failed(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent = Agent(uuid4(), "Sarmady", T0)
        store.register_agent(agent)
        projection = ExactContextCompiler(store).compile(
            ContextRequest(uuid4(), "unknown fact", 512),
            subject="missing:subject",
            predicate="missing_predicate",
        )
        runtime = CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1))

        with pytest.raises(TypeError, match="content must be a string"):
            runtime.invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-unknown-fact",
                adapter=_NonStringAdapter(),
            )

        invocation = store.invocations_for_agent(agent.id)[0]
        assert invocation.completed_at is not None
        assert invocation.error_code == "adapter-error:TypeError"


def test_reasoning_policy_rejects_uppercase_source_digest() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        ReasoningPolicy(
            id="test:policy:v1",
            version="1",
            mode=ReasoningMode.DIRECT,
            stages=(),
            requirements=(),
            source_ref="test-source",
            source_sha256="A" * 64,
        )


def test_context_request_preserves_pre_v5_positional_temporal_arguments() -> None:
    request = ContextRequest(
        uuid4(),
        "historical question",
        512,
        None,
        None,
        None,
        ("legacy-label",),
        T0,
        T0 + timedelta(hours=1),
    )
    assert request.coverage_requirements == ("legacy-label",)
    assert request.known_at == T0
    assert request.valid_at == T0 + timedelta(hours=1)
    assert request.exact_requirements == ()


def test_legacy_nonpositive_latency_request_remains_rehydratable(tmp_path) -> None:
    path = tmp_path / "legacy-latency.db"
    request_id = uuid4()
    with SQLiteCanonicalStore(path) as store:
        store.db.execute(
            """
            INSERT INTO context_requests(
                id, query, token_budget, latency_budget_ms, goal_ref, task_ref,
                coverage_requirements_json, known_at, valid_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, '[]', NULL, NULL)
            """,
            (str(request_id), "legacy", 512, -1),
        )
        store.db.commit()

        restored = store.context_request(request_id)
        assert restored is not None
        assert restored.latency_budget_ms == -1


def test_frozen_claim_value_round_trips_through_sqlite(tmp_path) -> None:
    path = tmp_path / "frozen-value.db"
    original = {"hardware": {"ram": [64, 96]}, "labels": ["primary"]}
    with SQLiteCanonicalStore(path) as store:
        claim = EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="profile",
            value=original,
            source_ref="user:statement",
            observed_at=T0,
        )
        claim_id = claim.id
        assert claim.value["hardware"]["ram"] == (64, 96)

    with SQLiteCanonicalStore(path) as reopened:
        restored = reopened.claim(claim_id)
        assert restored is not None
        assert restored.value["hardware"]["ram"] == (64, 96)
        with pytest.raises(TypeError, match="immutable"):
            restored.value["hardware"]["ram"] = (128,)
