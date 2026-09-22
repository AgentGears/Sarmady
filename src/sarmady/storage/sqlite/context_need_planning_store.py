from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sarmady.cognition import ContextNeedDecisionKind
from sarmady.context.models import (
    ContextRequest,
    ExactCoverageRequirement,
    RequirementPlan,
    RequirementPlanStatus,
    context_request_fingerprint,
)
from sarmady.context.planning_receipt import ContextNeedPlanningReceipt

from ._codec import iso


_SUPPORTED_CANDIDATE_GENERATOR = "lexical-v0.2"
_SUPPORTED_PLANNER = "controlled-requirement-v0.1"
_ALLOWED_ABSTENTION_REASONS = frozenset(
    {
        "candidate-set-non-exhaustive",
        "no-candidates",
        "no-explicit-predicate-evidence",
        "predicate-ambiguous-or-multi-intent",
    }
)


class ContextNeedPlanningStoreMixin:
    """Durable receipts and freshness fences for accepted-need planning."""

    def register_context_need_planning_receipt(
        self,
        receipt: ContextNeedPlanningReceipt,
        *,
        derived_request: ContextRequest | None = None,
    ) -> None:
        receipt = self._reconstruct_context_need_planning_receipt(receipt)
        if derived_request is not None:
            derived_request = ContextRequest(
                id=derived_request.id,
                query=derived_request.query,
                token_budget=derived_request.token_budget,
                latency_budget_ms=derived_request.latency_budget_ms,
                goal_ref=derived_request.goal_ref,
                task_ref=derived_request.task_ref,
                coverage_requirements=tuple(derived_request.coverage_requirements),
                exact_requirements=tuple(derived_request.exact_requirements),
                known_at=derived_request.known_at,
                valid_at=derived_request.valid_at,
            )

        resolved = receipt.plan.status is RequirementPlanStatus.RESOLVED
        if resolved:
            if derived_request is None:
                raise ValueError("resolved planning receipt requires derived_request")
            if receipt.derived_context_request_id != derived_request.id:
                raise ValueError("derived request does not match planning receipt")
        elif derived_request is not None:
            raise ValueError("non-resolved planning receipt cannot persist derived_request")

        with self._write_transaction():
            if self.db.execute(
                "SELECT 1 FROM context_need_planning_receipts WHERE id = ?",
                (str(receipt.id),),
            ).fetchone() is not None:
                raise ValueError("context need planning receipt id already exists")

            decision = self.context_need_decision(receipt.context_need_decision_id)
            if decision is None:
                raise ValueError("unknown context need decision")
            if decision.decision is not ContextNeedDecisionKind.ACCEPTED:
                raise ValueError("only an accepted context need can be planned")
            if decision.child_context_request_id is None:
                raise RuntimeError("accepted context need is missing its child request")
            if receipt.plan.source_request_id != decision.child_context_request_id:
                raise ValueError("planning receipt source request is not the accepted child")
            if receipt.planned_at < decision.decided_at:
                raise ValueError("planning receipt cannot precede the acceptance decision")

            source_request = self.context_request(decision.child_context_request_id)
            if source_request is None:
                raise ValueError("accepted context need child request is missing")
            if receipt.plan.source_request_fingerprint != context_request_fingerprint(
                source_request
            ):
                raise ValueError("planning receipt source request fingerprint mismatch")
            if source_request.exact_requirements:
                raise ValueError("accepted context-need child must not already have exact requirements")

            self._validate_context_need_plan_in_tx(receipt.plan, source_request)
            frontier = int(receipt.plan.canonical_frontier)

            # A raw semantic frontier can advance for SEEN/USED memory telemetry,
            # even though that telemetry is intentionally excluded from planning
            # freshness because it cannot change candidate eligibility. Treat an
            # existing non-stale receipt with the same host planning configuration
            # as the retry owner across such frontier-only telemetry movement.
            # Replanning becomes eligible only after a relevant semantic/memory
            # change makes every prior same-configuration receipt stale.
            current_attempts = self.db.execute(
                """
                SELECT candidate_frontier
                FROM context_need_planning_receipts
                WHERE context_need_decision_id = ?
                  AND candidate_limit = ?
                  AND candidate_generator_version = ?
                  AND planner_version = ?
                """,
                (
                    str(receipt.context_need_decision_id),
                    receipt.candidate_limit,
                    receipt.plan.candidate_generator_version,
                    receipt.plan.planner_version,
                ),
            ).fetchall()
            if any(
                not self._dependency_keys_changed_since(int(row["candidate_frontier"]))
                for row in current_attempts
            ):
                raise ValueError(
                    "current context need planning attempt already recorded for this configuration"
                )

            if resolved:
                assert derived_request is not None
                self._validate_derived_context_request(
                    source_request,
                    receipt.plan,
                    derived_request,
                )
                self._insert_new_context_request_in_tx(derived_request)

            self.db.execute(
                """
                INSERT INTO context_need_planning_receipts(
                    id, context_need_decision_id, planned_at,
                    source_context_request_id, source_request_fingerprint,
                    candidate_snapshot_id, candidate_frontier, candidate_limit,
                    candidate_generator_version, planner_version, status,
                    exact_requirements_json, selected_candidate_claim_ids_json,
                    ambiguous_candidate_claim_ids_json, reasons_json,
                    derived_context_request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(receipt.id),
                    str(receipt.context_need_decision_id),
                    iso(receipt.planned_at),
                    str(receipt.plan.source_request_id),
                    receipt.plan.source_request_fingerprint,
                    receipt.plan.candidate_snapshot_id,
                    frontier,
                    receipt.candidate_limit,
                    receipt.plan.candidate_generator_version,
                    receipt.plan.planner_version,
                    receipt.plan.status.value,
                    self._requirements_json(receipt.plan.exact_requirements),
                    json.dumps(
                        [str(value) for value in receipt.plan.selected_candidate_claim_ids]
                    ),
                    json.dumps(
                        [str(value) for value in receipt.plan.ambiguous_candidate_claim_ids]
                    ),
                    json.dumps(list(receipt.plan.reasons)),
                    (
                        str(receipt.derived_context_request_id)
                        if receipt.derived_context_request_id is not None
                        else None
                    ),
                ),
            )

    def _validate_context_need_plan_in_tx(
        self,
        plan: RequirementPlan,
        source_request: ContextRequest,
    ) -> None:
        if plan.candidate_generator_version != _SUPPORTED_CANDIDATE_GENERATOR:
            raise ValueError("unsupported context-need candidate generator version")
        if plan.planner_version != _SUPPORTED_PLANNER:
            raise ValueError("unsupported context-need planner version")

        try:
            frontier = int(plan.canonical_frontier)
        except (TypeError, ValueError) as exc:
            raise ValueError("planning candidate frontier must be an integer") from exc
        if frontier < 0:
            raise ValueError("planning candidate frontier cannot be negative")
        if plan.canonical_frontier != str(frontier):
            raise ValueError("planning candidate frontier must use canonical integer spelling")
        if plan.candidate_snapshot_id != f"sqlite:{frontier}":
            raise ValueError("planning candidate snapshot must match candidate frontier")

        self._validate_controlled_planner_shape(plan)

        current_frontier = self.frontier()
        if frontier > current_frontier:
            raise ValueError("planning candidate frontier cannot exceed current frontier")

        # lexical-v0.2 enumerates the complete visible semantic-key space before
        # limiting results. Any later claim/relation or memory-state mutation can
        # therefore change membership, exhaustiveness, ambiguity, or uniqueness.
        # Fail closed instead of persisting a plan whose snapshot proof is stale.
        if self._dependency_keys_changed_since(frontier):
            raise ValueError("planning candidate snapshot is stale")

        claim_ids = (
            plan.selected_candidate_claim_ids + plan.ambiguous_candidate_claim_ids
        )
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("planning candidate claim ids must be unique")
        for claim_id in claim_ids:
            self._validate_candidate_claim_at_frontier(
                claim_id,
                source_request=source_request,
                frontier=frontier,
            )

        if plan.status is RequirementPlanStatus.RESOLVED:
            requirement = plan.exact_requirements[0]
            claim_id = plan.selected_candidate_claim_ids[0]
            row = self.db.execute(
                "SELECT subject, predicate FROM claims WHERE id = ?",
                (str(claim_id),),
            ).fetchone()
            if row is None:
                raise ValueError("planning selected candidate claim is missing")
            if (
                row["subject"] != requirement.subject
                or row["predicate"] != requirement.predicate
            ):
                raise ValueError(
                    "planning selected candidate does not match exact requirement"
                )

    @staticmethod
    def _validate_controlled_planner_shape(plan: RequirementPlan) -> None:
        """Fence the exact output grammar of controlled-requirement-v0.1.

        ``RequirementPlan`` is intentionally generic enough for future planners.
        A persisted receipt that names the v0.1 planner must, however, be an
        outcome that this concrete planner can actually emit.
        """

        if plan.status is RequirementPlanStatus.RESOLVED:
            if len(plan.exact_requirements) != 1 or len(
                plan.selected_candidate_claim_ids
            ) != 1:
                raise ValueError(
                    "controlled requirement v0.1 resolved plan must contain exactly one obligation"
                )
            if plan.reasons:
                raise ValueError(
                    "controlled requirement v0.1 resolved plan cannot carry reasons"
                )
            return

        if plan.status is RequirementPlanStatus.AMBIGUOUS:
            if plan.reasons != ("ambiguous-subject",):
                raise ValueError(
                    "controlled requirement v0.1 ambiguous plan has invalid reason"
                )
            if len(plan.ambiguous_candidate_claim_ids) < 2:
                raise ValueError(
                    "controlled requirement v0.1 ambiguity requires multiple candidates"
                )
            return

        if plan.ambiguous_candidate_claim_ids:
            raise ValueError(
                "controlled requirement v0.1 abstention cannot carry ambiguous candidates"
            )
        if len(plan.reasons) != 1 or plan.reasons[0] not in _ALLOWED_ABSTENTION_REASONS:
            raise ValueError(
                "controlled requirement v0.1 abstention has invalid reason"
            )

    def _validate_candidate_claim_at_frontier(
        self,
        claim_id: UUID,
        *,
        source_request: ContextRequest,
        frontier: int,
    ) -> None:
        logged = self.db.execute(
            """
            SELECT 1 FROM semantic_log
            WHERE kind = 'Claim' AND ref_id = ? AND seq <= ?
            """,
            (str(claim_id), frontier),
        ).fetchone()
        if logged is None:
            raise ValueError("planning candidate claim was not visible at candidate frontier")

        row = self.db.execute(
            "SELECT subject, predicate FROM claims WHERE id = ?",
            (str(claim_id),),
        ).fetchone()
        if row is None:
            raise ValueError("planning candidate claim is missing")
        state = self.resolved_state(
            row["subject"],
            row["predicate"],
            known_at=source_request.known_at,
            valid_at=source_request.valid_at,
            snapshot_frontier=frontier,
        )
        if state.operative_claim_id != claim_id:
            raise ValueError("planning candidate claim was not operative at candidate frontier")
        if not self.is_active_memory_target("Claim", claim_id):
            raise ValueError("planning candidate claim is not active memory")

    @staticmethod
    def _validate_derived_context_request(
        source: ContextRequest,
        plan: RequirementPlan,
        derived: ContextRequest,
    ) -> None:
        if derived.id == source.id:
            raise ValueError("planned exact request must use a new id")
        if derived.query != source.query:
            raise ValueError("planned exact request must preserve source query")
        if derived.token_budget != source.token_budget:
            raise ValueError("planned exact request must preserve source token budget")
        if derived.latency_budget_ms != source.latency_budget_ms:
            raise ValueError("planned exact request must preserve source latency budget")
        if derived.goal_ref != source.goal_ref or derived.task_ref != source.task_ref:
            raise ValueError("planned exact request must preserve goal/task lineage")
        if derived.coverage_requirements != source.coverage_requirements:
            raise ValueError("planned exact request must preserve coverage labels")
        if derived.exact_requirements != plan.exact_requirements:
            raise ValueError("planned exact request must carry the resolved exact requirements")
        if derived.known_at != source.known_at or derived.valid_at != source.valid_at:
            raise ValueError("planned exact request must preserve temporal selectors")

    def context_need_planning_receipt(
        self,
        receipt_id: UUID,
    ) -> ContextNeedPlanningReceipt | None:
        row = self.db.execute(
            "SELECT * FROM context_need_planning_receipts WHERE id = ?",
            (str(receipt_id),),
        ).fetchone()
        return self._context_need_planning_receipt_from_row(row)

    def context_need_planning_receipts_for_decision(
        self,
        decision_id: UUID,
    ) -> tuple[ContextNeedPlanningReceipt, ...]:
        rows = self.db.execute(
            """
            SELECT * FROM context_need_planning_receipts
            WHERE context_need_decision_id = ?
            ORDER BY planned_at, rowid
            """,
            (str(decision_id),),
        ).fetchall()
        return tuple(self._context_need_planning_receipt_from_row(row) for row in rows)

    def context_need_planning_receipt_is_stale(self, receipt_id: UUID) -> bool:
        row = self.db.execute(
            "SELECT candidate_frontier FROM context_need_planning_receipts WHERE id = ?",
            (str(receipt_id),),
        ).fetchone()
        if row is None:
            raise ValueError("unknown context need planning receipt")
        return bool(self._dependency_keys_changed_since(int(row["candidate_frontier"])))

    @staticmethod
    def _requirements_json(
        requirements: tuple[ExactCoverageRequirement, ...],
    ) -> str:
        return json.dumps(
            [
                {
                    "key": item.key,
                    "subject": item.subject,
                    "predicate": item.predicate,
                    "role": item.role,
                }
                for item in requirements
            ],
            sort_keys=True,
        )

    @classmethod
    def _context_need_planning_receipt_from_row(
        cls,
        row,
    ) -> ContextNeedPlanningReceipt | None:
        if row is None:
            return None
        exact = tuple(
            ExactCoverageRequirement(
                key=item["key"],
                subject=item["subject"],
                predicate=item["predicate"],
                role=item.get("role", "essential_now"),
            )
            for item in json.loads(row["exact_requirements_json"])
        )
        plan = RequirementPlan(
            source_request_id=UUID(row["source_context_request_id"]),
            source_request_fingerprint=row["source_request_fingerprint"],
            candidate_snapshot_id=row["candidate_snapshot_id"],
            canonical_frontier=str(row["candidate_frontier"]),
            candidate_generator_version=row["candidate_generator_version"],
            planner_version=row["planner_version"],
            status=RequirementPlanStatus(row["status"]),
            exact_requirements=exact,
            selected_candidate_claim_ids=tuple(
                UUID(value)
                for value in json.loads(row["selected_candidate_claim_ids_json"])
            ),
            ambiguous_candidate_claim_ids=tuple(
                UUID(value)
                for value in json.loads(row["ambiguous_candidate_claim_ids_json"])
            ),
            reasons=tuple(json.loads(row["reasons_json"])),
        )
        return ContextNeedPlanningReceipt(
            id=UUID(row["id"]),
            context_need_decision_id=UUID(row["context_need_decision_id"]),
            planned_at=datetime.fromisoformat(row["planned_at"]),
            plan=plan,
            candidate_limit=int(row["candidate_limit"]),
            derived_context_request_id=(
                UUID(row["derived_context_request_id"])
                if row["derived_context_request_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _reconstruct_context_need_planning_receipt(
        receipt: ContextNeedPlanningReceipt,
    ) -> ContextNeedPlanningReceipt:
        plan = RequirementPlan(
            source_request_id=receipt.plan.source_request_id,
            source_request_fingerprint=receipt.plan.source_request_fingerprint,
            candidate_snapshot_id=receipt.plan.candidate_snapshot_id,
            canonical_frontier=receipt.plan.canonical_frontier,
            candidate_generator_version=receipt.plan.candidate_generator_version,
            planner_version=receipt.plan.planner_version,
            status=receipt.plan.status,
            exact_requirements=tuple(receipt.plan.exact_requirements),
            selected_candidate_claim_ids=tuple(receipt.plan.selected_candidate_claim_ids),
            ambiguous_candidate_claim_ids=tuple(receipt.plan.ambiguous_candidate_claim_ids),
            reasons=tuple(receipt.plan.reasons),
        )
        return ContextNeedPlanningReceipt(
            id=receipt.id,
            context_need_decision_id=receipt.context_need_decision_id,
            planned_at=receipt.planned_at,
            plan=plan,
            candidate_limit=receipt.candidate_limit,
            derived_context_request_id=receipt.derived_context_request_id,
        )
