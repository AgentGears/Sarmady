from __future__ import annotations

from sarmady.context.models import ContextProjection


class ContextNeedPlanningProjectionFenceMixin:
    """Fail closed when a derived exact request outlives its planning proof.

    ``ProjectionStoreMixin.register_context_projection`` calls
    ``_validate_context_projection_refs_in_tx`` while holding its write lock.
    Placing this cooperative mixin before ``ProjectionStoreMixin`` therefore
    makes planning freshness part of the durable projection-registration fence,
    regardless of which compiler produced the projection.
    """

    def _validate_context_projection_refs_in_tx(
        self,
        projection: ContextProjection,
    ) -> None:
        receipt_row = self.db.execute(
            """
            SELECT candidate_frontier
            FROM context_need_planning_receipts
            WHERE derived_context_request_id = ?
            """,
            (str(projection.request_id),),
        ).fetchone()
        if receipt_row is not None and self._dependency_keys_changed_since(
            int(receipt_row["candidate_frontier"])
        ):
            raise ValueError(
                "cannot register projection from a stale context-need planning receipt"
            )
        super()._validate_context_projection_refs_in_tx(projection)
