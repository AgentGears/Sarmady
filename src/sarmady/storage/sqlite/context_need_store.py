from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sarmady.cognition import (
    CONTEXT_NEED_ARTIFACT_KIND,
    ContextNeedDecision,
    ContextNeedDecisionKind,
    deserialize_context_need_proposal,
)
from sarmady.context.models import ContextRequest

from ._codec import iso


class ContextNeedStoreMixin:
    """Persistence and lineage fences for governed context-need decisions."""

    def register_context_need_decision(
        self,
        decision: ContextNeedDecision,
        *,
        child_request: ContextRequest | None = None,
    ) -> None:
        # Reconstruct both values through public invariants at the durable write
        # boundary so post-construction mutation of frozen dataclasses cannot
        # forge lineage, decision kind, or request semantics.
        decision = ContextNeedDecision(
            id=decision.id,
            context_need_artifact_id=decision.context_need_artifact_id,
            decision=decision.decision,
            decided_at=decision.decided_at,
            reason=decision.reason,
            decision_source=decision.decision_source,
            parent_invocation_id=decision.parent_invocation_id,
            parent_cognitive_request_id=decision.parent_cognitive_request_id,
            parent_context_projection_id=decision.parent_context_projection_id,
            parent_context_request_id=decision.parent_context_request_id,
            child_context_request_id=decision.child_context_request_id,
        )
        if child_request is not None:
            child_request = ContextRequest(
                id=child_request.id,
                query=child_request.query,
                token_budget=child_request.token_budget,
                latency_budget_ms=child_request.latency_budget_ms,
                goal_ref=child_request.goal_ref,
                task_ref=child_request.task_ref,
                coverage_requirements=tuple(child_request.coverage_requirements),
                exact_requirements=tuple(child_request.exact_requirements),
                known_at=child_request.known_at,
                valid_at=child_request.valid_at,
            )

        if decision.decision is ContextNeedDecisionKind.ACCEPTED:
            if child_request is None:
                raise ValueError("accepted context need requires child_request")
            if decision.child_context_request_id != child_request.id:
                raise ValueError("child request does not match accepted decision")
        elif child_request is not None:
            raise ValueError("rejected context need cannot persist a child request")

        with self._write_transaction():
            existing = self.db.execute(
                "SELECT id FROM context_need_decisions WHERE context_need_artifact_id = ?",
                (str(decision.context_need_artifact_id),),
            ).fetchone()
            if existing is not None:
                raise ValueError("context need artifact already has a decision")

            proposal, parent_request = self._validate_context_need_lineage_in_tx(decision)
            if decision.decision is ContextNeedDecisionKind.ACCEPTED:
                assert child_request is not None
                projection_row = self.db.execute(
                    "SELECT stale FROM context_projections WHERE id = ?",
                    (str(decision.parent_context_projection_id),),
                ).fetchone()
                if projection_row is None:
                    raise ValueError("unknown parent context projection")
                if bool(projection_row["stale"]):
                    raise ValueError("cannot accept context need from a stale context projection")
                self._validate_child_context_request(
                    parent_request,
                    child_request,
                    proposal_query=proposal.query,
                    proposal_coverage=proposal.coverage_requirements,
                )
                self._insert_context_request_in_tx(child_request)

            self.db.execute(
                """
                INSERT INTO context_need_decisions(
                    id, context_need_artifact_id, decision, decided_at,
                    reason, decision_source, parent_invocation_id,
                    parent_cognitive_request_id, parent_context_projection_id,
                    parent_context_request_id, child_context_request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(decision.id),
                    str(decision.context_need_artifact_id),
                    decision.decision.value,
                    iso(decision.decided_at),
                    decision.reason,
                    decision.decision_source,
                    str(decision.parent_invocation_id),
                    str(decision.parent_cognitive_request_id),
                    str(decision.parent_context_projection_id),
                    str(decision.parent_context_request_id),
                    (
                        str(decision.child_context_request_id)
                        if decision.child_context_request_id is not None
                        else None
                    ),
                ),
            )

    def _validate_context_need_lineage_in_tx(
        self,
        decision: ContextNeedDecision,
    ):
        artifact_row = self.db.execute(
            "SELECT * FROM generated_artifacts WHERE id = ?",
            (str(decision.context_need_artifact_id),),
        ).fetchone()
        if artifact_row is None:
            raise ValueError("unknown context need artifact")
        if artifact_row["artifact_kind"] != CONTEXT_NEED_ARTIFACT_KIND:
            raise ValueError("artifact is not a context-need proposal")
        proposal = deserialize_context_need_proposal(artifact_row["content"])
        if artifact_row["invocation_id"] != str(decision.parent_invocation_id):
            raise ValueError("context need decision invocation lineage mismatch")

        invocation_row = self.db.execute(
            "SELECT * FROM model_invocations WHERE id = ?",
            (str(decision.parent_invocation_id),),
        ).fetchone()
        if invocation_row is None:
            raise ValueError("unknown parent model invocation")
        if invocation_row["completed_at"] is None or invocation_row["error_code"] is not None:
            raise ValueError("context need must come from a successful model invocation")
        if invocation_row["cognitive_request_id"] != str(decision.parent_cognitive_request_id):
            raise ValueError("context need decision cognitive lineage mismatch")

        cognitive_row = self.db.execute(
            "SELECT * FROM cognitive_requests WHERE id = ?",
            (str(decision.parent_cognitive_request_id),),
        ).fetchone()
        if cognitive_row is None:
            raise ValueError("unknown parent cognitive request")
        if cognitive_row["context_projection_id"] != str(decision.parent_context_projection_id):
            raise ValueError("context need decision projection lineage mismatch")

        projection_row = self.db.execute(
            "SELECT * FROM context_projections WHERE id = ?",
            (str(decision.parent_context_projection_id),),
        ).fetchone()
        if projection_row is None:
            raise ValueError("unknown parent context projection")
        if projection_row["request_id"] != str(decision.parent_context_request_id):
            raise ValueError("context need decision request lineage mismatch")

        parent_request = self.context_request(decision.parent_context_request_id)
        if parent_request is None:
            raise ValueError("unknown parent context request")
        return proposal, parent_request

    @staticmethod
    def _validate_child_context_request(
        parent: ContextRequest,
        child: ContextRequest,
        *,
        proposal_query: str,
        proposal_coverage: tuple[str, ...],
    ) -> None:
        if child.id == parent.id:
            raise ValueError("child context request must use a new id")
        if child.query != proposal_query:
            raise ValueError("child context request query must match the accepted proposal")
        if tuple(child.coverage_requirements) != tuple(proposal_coverage):
            raise ValueError(
                "child context request coverage labels must match the accepted proposal"
            )
        if child.exact_requirements:
            raise ValueError(
                "context-need acceptance cannot directly create exact semantic requirements"
            )
        if child.goal_ref != parent.goal_ref or child.task_ref != parent.task_ref:
            raise ValueError("child context request must inherit parent goal/task lineage")
        if child.known_at != parent.known_at or child.valid_at != parent.valid_at:
            raise ValueError("child context request must inherit parent temporal selectors")
        if child.token_budget > parent.token_budget:
            raise ValueError("child token budget cannot exceed parent token budget")

        parent_latency = (
            parent.latency_budget_ms
            if parent.latency_budget_ms is not None and parent.latency_budget_ms > 0
            else None
        )
        if parent_latency is not None:
            if child.latency_budget_ms is None:
                raise ValueError("bounded parent latency cannot be removed from child request")
            if child.latency_budget_ms > parent_latency:
                raise ValueError("child latency budget cannot exceed parent latency budget")

    def _insert_context_request_in_tx(self, request: ContextRequest) -> None:
        self.db.execute(
            """
            INSERT OR IGNORE INTO context_requests(
                id, query, token_budget, latency_budget_ms, goal_ref, task_ref,
                coverage_requirements_json, known_at, valid_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(request.id),
                request.query,
                request.token_budget,
                request.latency_budget_ms,
                str(request.goal_ref) if request.goal_ref else None,
                str(request.task_ref) if request.task_ref else None,
                json.dumps(
                    {
                        "labels": list(request.coverage_requirements),
                        "exact": [
                            {
                                "key": item.key,
                                "subject": item.subject,
                                "predicate": item.predicate,
                                "role": item.role,
                            }
                            for item in request.exact_requirements
                        ],
                    },
                    sort_keys=True,
                ),
                request.known_at.isoformat() if request.known_at else None,
                request.valid_at.isoformat() if request.valid_at else None,
            ),
        )
        persisted = self.context_request(request.id)
        if persisted != request:
            raise ValueError("context request id is already bound to different semantics")

    def context_need_decision(self, decision_id: UUID) -> ContextNeedDecision | None:
        row = self.db.execute(
            "SELECT * FROM context_need_decisions WHERE id = ?",
            (str(decision_id),),
        ).fetchone()
        return self._context_need_decision_from_row(row)

    def context_need_decision_for_artifact(
        self,
        artifact_id: UUID,
    ) -> ContextNeedDecision | None:
        row = self.db.execute(
            "SELECT * FROM context_need_decisions WHERE context_need_artifact_id = ?",
            (str(artifact_id),),
        ).fetchone()
        return self._context_need_decision_from_row(row)

    @staticmethod
    def _context_need_decision_from_row(row) -> ContextNeedDecision | None:
        if row is None:
            return None
        return ContextNeedDecision(
            id=UUID(row["id"]),
            context_need_artifact_id=UUID(row["context_need_artifact_id"]),
            decision=ContextNeedDecisionKind(row["decision"]),
            decided_at=datetime.fromisoformat(row["decided_at"]),
            reason=row["reason"],
            decision_source=row["decision_source"],
            parent_invocation_id=UUID(row["parent_invocation_id"]),
            parent_cognitive_request_id=UUID(row["parent_cognitive_request_id"]),
            parent_context_projection_id=UUID(row["parent_context_projection_id"]),
            parent_context_request_id=UUID(row["parent_context_request_id"]),
            child_context_request_id=(
                UUID(row["child_context_request_id"])
                if row["child_context_request_id"] is not None
                else None
            ),
        )
