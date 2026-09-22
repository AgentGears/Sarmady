from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

from sarmady.cognition import (
    CONTEXT_NEED_ARTIFACT_KIND,
    CognitiveRequest,
    ContextNeedProposal,
    GeneratedArtifact,
    ModelInvocation,
    ReasoningPolicy,
    deserialize_context_need_proposal,
    serialize_context_need_proposal,
)
from sarmady.context import ContextProjection, CoverageStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.values import thaw_value


@dataclass(frozen=True, slots=True)
class ModelContextItem:
    ref_type: str
    ref_id: UUID
    role: str
    payload: Mapping[str, Any]
    provenance_refs: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelInput:
    agent_id: UUID
    cognitive_request_id: UUID
    context_projection_id: UUID
    snapshot_id: str
    operation: str
    reasoning_policy_id: str | None
    reasoning_policy_fingerprint: str | None
    reasoning_policy: ReasoningPolicy | None
    items: tuple[ModelContextItem, ...]
    conflict_refs: tuple[UUID, ...] = ()
    coverage_status: CoverageStatus = field(
        default=CoverageStatus.INSUFFICIENT,
        kw_only=True,
    )
    unresolved_gaps: tuple[str, ...] = field(default=(), kw_only=True)
    omitted_refs: tuple[UUID, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        if self.reasoning_policy is None:
            if self.reasoning_policy_id is not None or self.reasoning_policy_fingerprint is not None:
                raise ValueError(
                    "reasoning policy metadata requires a structured reasoning policy"
                )
            return
        if self.reasoning_policy_id != self.reasoning_policy.id:
            raise ValueError("reasoning_policy_id must match the structured policy")
        if self.reasoning_policy_fingerprint != self.reasoning_policy.fingerprint:
            raise ValueError(
                "reasoning_policy_fingerprint must match the structured policy"
            )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    artifact_kind: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_kind, str) or not self.artifact_kind.strip():
            raise ValueError("artifact_kind is required")
        if self.artifact_kind == CONTEXT_NEED_ARTIFACT_KIND:
            raise ValueError(
                "context-need:v1 is reserved for typed ContextNeedProposal outcomes"
            )
        if not isinstance(self.content, str):
            raise TypeError("model response content must be a string")


class ModelAdapter(Protocol):
    @property
    def binding_id(self) -> str: ...

    def invoke(self, model_input: ModelInput) -> ModelResponse: ...


class StepModelAdapter(Protocol):
    """Adapter that may either complete or propose an additional context need."""

    @property
    def binding_id(self) -> str: ...

    def invoke(
        self,
        model_input: ModelInput,
    ) -> ModelResponse | ContextNeedProposal: ...


class CognitiveStepStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NEEDS_CONTEXT = "NEEDS_CONTEXT"


@dataclass(frozen=True, slots=True)
class CognitiveStepResult:
    status: CognitiveStepStatus
    artifact: GeneratedArtifact
    context_need: ContextNeedProposal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CognitiveStepStatus):
            raise TypeError("cognitive step status must be CognitiveStepStatus")
        if not isinstance(self.artifact, GeneratedArtifact):
            raise TypeError("cognitive step artifact must be GeneratedArtifact")
        if self.status is CognitiveStepStatus.COMPLETED:
            if self.context_need is not None:
                raise ValueError("completed cognitive step cannot carry a context need")
            if self.artifact.artifact_kind == CONTEXT_NEED_ARTIFACT_KIND:
                raise ValueError(
                    "completed cognitive step cannot carry a context-need artifact"
                )
            return
        if not isinstance(self.context_need, ContextNeedProposal):
            raise TypeError(
                "context-needing cognitive step requires a ContextNeedProposal"
            )
        if self.artifact.artifact_kind != CONTEXT_NEED_ARTIFACT_KIND:
            raise ValueError(
                "context-needing cognitive step requires a context-need artifact"
            )
        if deserialize_context_need_proposal(self.artifact.content) != self.context_need:
            raise ValueError(
                "context-needing cognitive step artifact does not match its proposal"
            )


def context_need_from_artifact(artifact: GeneratedArtifact) -> ContextNeedProposal:
    """Rehydrate a typed context need from a versioned generated artifact.

    This validates kind and payload shape; it does not authenticate that the
    artifact came from a trusted store/runtime path.
    """

    if not isinstance(artifact, GeneratedArtifact):
        raise TypeError("artifact must be GeneratedArtifact")
    if artifact.artifact_kind != CONTEXT_NEED_ARTIFACT_KIND:
        raise ValueError("generated artifact is not a context-need artifact")
    return deserialize_context_need_proposal(artifact.content)


class CognitiveRuntime:
    """Provider-neutral cognitive execution over persisted semantic context."""

    def __init__(
        self,
        store: SQLiteCanonicalStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def invoke(
        self,
        *,
        agent_id: UUID,
        context_projection_id: UUID,
        operation: str,
        adapter: ModelAdapter,
        reasoning_policy: ReasoningPolicy | None = None,
        reasoning_policy_id: str | None = None,
    ) -> GeneratedArtifact:
        """Run one terminal model invocation.

        This preserves the original M1 contract: adapters used through
        ``invoke`` must return a terminal ``ModelResponse``.
        """

        invocation, model_input = self._begin_invocation(
            agent_id=agent_id,
            context_projection_id=context_projection_id,
            operation=operation,
            binding_id=adapter.binding_id,
            reasoning_policy=reasoning_policy,
            reasoning_policy_id=reasoning_policy_id,
        )

        try:
            response = self._validated_model_response(adapter.invoke(model_input))
            return self._complete_artifact(
                invocation,
                artifact_kind=response.artifact_kind,
                content=response.content,
            )
        except Exception as exc:
            self._fail_open_invocation(invocation, exc)
            raise

    def invoke_step(
        self,
        *,
        agent_id: UUID,
        context_projection_id: UUID,
        operation: str,
        adapter: StepModelAdapter,
        reasoning_policy: ReasoningPolicy | None = None,
        reasoning_policy_id: str | None = None,
    ) -> CognitiveStepResult:
        """Run one cognitive step without granting the model context authority.

        A step may complete normally or emit a typed ``ContextNeedProposal``.
        The proposal is durably recorded as a non-authoritative
        ``GeneratedArtifact``. This method does not create a ``ContextRequest``,
        retrieve additional state, allocate a new budget, or continue a loop.
        """

        invocation, model_input = self._begin_invocation(
            agent_id=agent_id,
            context_projection_id=context_projection_id,
            operation=operation,
            binding_id=adapter.binding_id,
            reasoning_policy=reasoning_policy,
            reasoning_policy_id=reasoning_policy_id,
        )

        try:
            response = adapter.invoke(model_input)
            if isinstance(response, ModelResponse):
                terminal = self._validated_model_response(response)
                artifact = self._complete_artifact(
                    invocation,
                    artifact_kind=terminal.artifact_kind,
                    content=terminal.content,
                )
                return CognitiveStepResult(
                    status=CognitiveStepStatus.COMPLETED,
                    artifact=artifact,
                )
            if isinstance(response, ContextNeedProposal):
                content = serialize_context_need_proposal(response)
                normalized = deserialize_context_need_proposal(content)
                artifact = self._complete_artifact(
                    invocation,
                    artifact_kind=CONTEXT_NEED_ARTIFACT_KIND,
                    content=content,
                    allow_context_need=True,
                )
                return CognitiveStepResult(
                    status=CognitiveStepStatus.NEEDS_CONTEXT,
                    artifact=artifact,
                    context_need=normalized,
                )
            raise TypeError(
                "step model adapter must return ModelResponse or ContextNeedProposal"
            )
        except Exception as exc:
            self._fail_open_invocation(invocation, exc)
            raise

    @staticmethod
    def _validated_model_response(response: object) -> ModelResponse:
        """Revalidate adapter output at the runtime/durable boundary."""

        if not isinstance(response, ModelResponse):
            raise TypeError("model adapter must return ModelResponse")
        return ModelResponse(
            artifact_kind=response.artifact_kind,
            content=response.content,
        )

    def _begin_invocation(
        self,
        *,
        agent_id: UUID,
        context_projection_id: UUID,
        operation: str,
        binding_id: str,
        reasoning_policy: ReasoningPolicy | None,
        reasoning_policy_id: str | None,
    ) -> tuple[ModelInvocation, ModelInput]:
        if not binding_id.strip():
            raise ValueError("adapter binding_id is required")
        if (
            reasoning_policy is not None
            and reasoning_policy_id is not None
            and reasoning_policy.id != reasoning_policy_id
        ):
            raise ValueError(
                "reasoning_policy and reasoning_policy_id refer to different policies"
            )

        policy = reasoning_policy
        if policy is not None:
            self.store.register_reasoning_policy(
                policy,
                registered_at=self.clock(),
            )
        elif reasoning_policy_id is not None:
            policy = self.store.reasoning_policy(reasoning_policy_id)
            if policy is None:
                raise ValueError(f"unknown reasoning policy {reasoning_policy_id!r}")

        request = CognitiveRequest(
            id=uuid4(),
            agent_id=agent_id,
            context_projection_id=context_projection_id,
            operation=operation,
            created_at=self.clock(),
            reasoning_policy_id=policy.id if policy is not None else None,
        )
        self.store.create_cognitive_request(request)
        projection = self.store.context_projection(context_projection_id)
        if projection is None:
            raise RuntimeError("persisted context projection disappeared")
        model_input = self._materialize_input(request, projection)

        invocation = ModelInvocation(
            id=uuid4(),
            cognitive_request_id=request.id,
            model_binding=binding_id,
            started_at=self.clock(),
        )
        self.store.start_model_invocation(invocation)
        return invocation, model_input

    def _complete_artifact(
        self,
        invocation: ModelInvocation,
        *,
        artifact_kind: str,
        content: str,
        allow_context_need: bool = False,
    ) -> GeneratedArtifact:
        if artifact_kind == CONTEXT_NEED_ARTIFACT_KIND and not allow_context_need:
            raise ValueError(
                "context-need:v1 artifact is reserved for typed ContextNeedProposal outcomes"
            )
        artifact = GeneratedArtifact(
            id=uuid4(),
            invocation_id=invocation.id,
            artifact_kind=artifact_kind,
            content=content,
            created_at=self.clock(),
        )
        self.store.complete_model_invocation(
            invocation.id,
            artifact,
            completed_at=self.clock(),
        )
        return artifact

    def _fail_open_invocation(self, invocation: ModelInvocation, exc: Exception) -> None:
        current = self.store.invocation(invocation.id)
        if current is not None and current.completed_at is None:
            self.store.fail_model_invocation(
                invocation.id,
                completed_at=self.clock(),
                error_code=f"adapter-error:{type(exc).__name__}",
            )

    def _materialize_input(
        self,
        request: CognitiveRequest,
        projection: ContextProjection,
    ) -> ModelInput:
        policy = None
        if request.reasoning_policy_id is not None:
            policy = self.store.reasoning_policy(request.reasoning_policy_id)
            if policy is None:
                raise RuntimeError(
                    f"cognitive request references missing reasoning policy {request.reasoning_policy_id!r}"
                )

        items: list[ModelContextItem] = []
        for item in projection.items:
            if item.ref_type == "Claim":
                claim = self.store.claim(item.ref_id)
                if claim is None:
                    raise RuntimeError(f"projection references missing claim {item.ref_id}")
                payload = {
                    "subject": claim.subject,
                    "predicate": claim.predicate,
                    "value": thaw_value(claim.value),
                    "recorded_at": claim.recorded_at.isoformat(),
                    "valid_from": claim.valid_from.isoformat() if claim.valid_from else None,
                    "valid_to": claim.valid_to.isoformat() if claim.valid_to else None,
                }
            elif item.ref_type == "Evidence":
                evidence = self.store.evidence(item.ref_id)
                if evidence is None:
                    raise RuntimeError(
                        f"projection references missing evidence {item.ref_id}"
                    )
                payload = {
                    "source_ref": evidence.source_ref,
                    "captured_at": evidence.captured_at.isoformat(),
                    "digest": evidence.digest,
                }
            else:
                raise RuntimeError(
                    f"unsupported context item type for model input: {item.ref_type}"
                )

            items.append(
                ModelContextItem(
                    ref_type=item.ref_type,
                    ref_id=item.ref_id,
                    role=item.role,
                    payload=payload,
                    provenance_refs=item.provenance_refs,
                )
            )

        return ModelInput(
            agent_id=request.agent_id,
            cognitive_request_id=request.id,
            context_projection_id=projection.id,
            snapshot_id=projection.snapshot_id,
            operation=request.operation,
            reasoning_policy_id=policy.id if policy is not None else None,
            reasoning_policy_fingerprint=(policy.fingerprint if policy is not None else None),
            reasoning_policy=policy,
            items=tuple(items),
            conflict_refs=projection.conflict_refs,
            coverage_status=projection.coverage_status,
            unresolved_gaps=projection.unresolved_gaps,
            omitted_refs=projection.omitted_refs,
        )
