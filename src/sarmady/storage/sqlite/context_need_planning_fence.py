from __future__ import annotations

from uuid import UUID

from sarmady.context.models import ContextProjection


class ContextNeedPlanningProjectionFenceMixin:
    """Fail closed when a derived exact request outlives its planning proof.

    ``ProjectionStoreMixin.register_context_projection`` calls
    ``_validate_context_projection_refs_in_tx`` while holding its write lock.
    Placing this cooperative mixin before ``ProjectionStoreMixin`` therefore
    makes planning freshness part of the durable projection-registration fence,
    regardless of which compiler produced the projection.

    The same provenance remains relevant after a projection has been persisted:
    a later semantic change may invalidate the lexical uniqueness/ambiguity
    judgment even when the projection's exact semantic key itself did not
    change. Dynamic projection freshness therefore includes the owning planning
    receipt so cognition cannot bypass replanning through an older projection.
    """

    def _planning_receipt_frontier_for_request(self, request_id: UUID) -> int | None:
        row = self.db.execute(
            """
            SELECT candidate_frontier
            FROM context_need_planning_receipts
            WHERE derived_context_request_id = ?
            """,
            (str(request_id),),
        ).fetchone()
        return int(row["candidate_frontier"]) if row is not None else None

    def _planning_receipt_frontier_for_projection(
        self,
        projection_id: UUID,
    ) -> int | None:
        row = self.db.execute(
            """
            SELECT r.candidate_frontier
            FROM context_projections p
            JOIN context_need_planning_receipts r
              ON r.derived_context_request_id = p.request_id
            WHERE p.id = ?
            """,
            (str(projection_id),),
        ).fetchone()
        return int(row["candidate_frontier"]) if row is not None else None

    def _validate_context_projection_refs_in_tx(
        self,
        projection: ContextProjection,
    ) -> None:
        planning_frontier = self._planning_receipt_frontier_for_request(
            projection.request_id
        )
        if planning_frontier is not None and self._dependency_keys_changed_since(
            planning_frontier
        ):
            raise ValueError(
                "cannot register projection from a stale context-need planning receipt"
            )
        super()._validate_context_projection_refs_in_tx(projection)

    def projection_is_stale(self, projection_id: UUID) -> bool:
        if super().projection_is_stale(projection_id):
            return True
        planning_frontier = self._planning_receipt_frontier_for_projection(projection_id)
        return bool(
            planning_frontier is not None
            and self._dependency_keys_changed_since(planning_frontier)
        )

    def projection_stale_reason(self, projection_id: UUID) -> str | None:
        stored_reason = super().projection_stale_reason(projection_id)
        if stored_reason is not None:
            return stored_reason
        planning_frontier = self._planning_receipt_frontier_for_projection(projection_id)
        if planning_frontier is not None and self._dependency_keys_changed_since(
            planning_frontier
        ):
            return "context-need-planning-receipt-stale"
        return None
