from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sarmady.context.models import (
    ContextItem,
    ContextProjection,
    ContextRequest,
    CoverageStatus,
    ExactCoverageRequirement,
)


class ProjectionStoreMixin:
    def register_context_projection(
        self,
        projection: ContextProjection,
        *,
        request: ContextRequest,
        dependency_keys: tuple[str, ...],
    ) -> bool:
        """Persist a complete immutable projection; return whether it is stale."""

        if projection.request_id != request.id:
            raise ValueError("projection must reference the persisted context request")

        canonical_frontier = int(projection.canonical_frontier)
        with self._write_transaction():
            current_frontier = self.frontier()
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
            stale = current_frontier != canonical_frontier
            persisted_request = self.context_request(request.id)
            if persisted_request != request:
                raise ValueError(
                    "context request id is already bound to different semantics"
                )

            self.db.execute(
                """
                INSERT INTO context_projections(
                    id, request_id, snapshot_id, canonical_frontier,
                    manifest_digest, compiler_version, coverage_status,
                    stale, stale_reason, stale_at_frontier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(projection.id),
                    str(projection.request_id),
                    projection.snapshot_id,
                    canonical_frontier,
                    projection.manifest_digest,
                    projection.compiler_version,
                    projection.coverage_status.value,
                    1 if stale else 0,
                    "frontier-advanced-before-registration" if stale else None,
                    current_frontier if stale else None,
                ),
            )
            self.db.execute(
                """
                INSERT INTO context_projection_details(
                    projection_id, conflict_refs_json,
                    unresolved_gaps_json, omitted_refs_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(projection.id),
                    json.dumps([str(ref) for ref in projection.conflict_refs]),
                    json.dumps(list(projection.unresolved_gaps)),
                    json.dumps([str(ref) for ref in projection.omitted_refs]),
                ),
            )
            self.db.executemany(
                """
                INSERT INTO context_projection_items(
                    projection_id, ordinal, ref_type, ref_id, role,
                    provenance_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(projection.id),
                        index,
                        item.ref_type,
                        str(item.ref_id),
                        item.role,
                        json.dumps([str(ref) for ref in item.provenance_refs]),
                    )
                    for index, item in enumerate(projection.items)
                ],
            )
            self.db.executemany(
                """
                INSERT INTO context_projection_dependencies
                (projection_id, dependency_key) VALUES (?, ?)
                """,
                [
                    (str(projection.id), dependency)
                    for dependency in sorted(set(dependency_keys))
                ],
            )
        return stale

    def context_request(self, request_id: UUID) -> ContextRequest | None:
        row = self.db.execute(
            "SELECT * FROM context_requests WHERE id = ?",
            (str(request_id),),
        ).fetchone()
        if row is None:
            return None
        raw_coverage = json.loads(row["coverage_requirements_json"])
        if isinstance(raw_coverage, list):
            labels = tuple(raw_coverage)
            exact = ()
        elif isinstance(raw_coverage, dict):
            labels = tuple(raw_coverage.get("labels", ()))
            exact = tuple(
                ExactCoverageRequirement(
                    key=item["key"],
                    subject=item["subject"],
                    predicate=item["predicate"],
                    role=item.get("role", "essential_now"),
                )
                for item in raw_coverage.get("exact", ())
            )
        else:
            raise RuntimeError("invalid persisted coverage_requirements_json")

        return ContextRequest(
            id=UUID(row["id"]),
            query=row["query"],
            token_budget=int(row["token_budget"]),
            latency_budget_ms=row["latency_budget_ms"],
            goal_ref=UUID(row["goal_ref"]) if row["goal_ref"] else None,
            task_ref=UUID(row["task_ref"]) if row["task_ref"] else None,
            coverage_requirements=labels,
            exact_requirements=exact,
            known_at=(
                datetime.fromisoformat(row["known_at"])
                if row["known_at"] else None
            ),
            valid_at=(
                datetime.fromisoformat(row["valid_at"])
                if row["valid_at"] else None
            ),
        )

    def context_projection(self, projection_id: UUID) -> ContextProjection | None:
        row = self.db.execute(
            "SELECT * FROM context_projections WHERE id = ?",
            (str(projection_id),),
        ).fetchone()
        if row is None:
            return None
        detail = self.db.execute(
            "SELECT * FROM context_projection_details WHERE projection_id = ?",
            (str(projection_id),),
        ).fetchone()
        if detail is None:
            return None
        item_rows = self.db.execute(
            """
            SELECT * FROM context_projection_items
            WHERE projection_id = ? ORDER BY ordinal
            """,
            (str(projection_id),),
        ).fetchall()
        items = tuple(
            ContextItem(
                ref_type=item["ref_type"],
                ref_id=UUID(item["ref_id"]),
                role=item["role"],
                provenance_refs=tuple(
                    UUID(value)
                    for value in json.loads(item["provenance_refs_json"])
                ),
            )
            for item in item_rows
        )
        return ContextProjection(
            id=UUID(row["id"]),
            request_id=UUID(row["request_id"]),
            snapshot_id=row["snapshot_id"],
            canonical_frontier=str(row["canonical_frontier"]),
            items=items,
            coverage_status=CoverageStatus(row["coverage_status"]),
            manifest_digest=row["manifest_digest"],
            compiler_version=row["compiler_version"],
            conflict_refs=tuple(
                UUID(value) for value in json.loads(detail["conflict_refs_json"])
            ),
            unresolved_gaps=tuple(json.loads(detail["unresolved_gaps_json"])),
            omitted_refs=tuple(
                UUID(value) for value in json.loads(detail["omitted_refs_json"])
            ),
        )

    def projection_is_stale(self, projection_id: UUID) -> bool:
        row = self.db.execute(
            "SELECT stale FROM context_projections WHERE id = ?",
            (str(projection_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown context projection {projection_id}")
        return bool(row["stale"])

    def projection_stale_reason(self, projection_id: UUID) -> str | None:
        row = self.db.execute(
            "SELECT stale_reason FROM context_projections WHERE id = ?",
            (str(projection_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown context projection {projection_id}")
        return row["stale_reason"]

    def _invalidate_projection_dependencies_in_tx(
        self, dependency_keys: tuple[str, ...], *, reason: str
    ) -> None:
        keys = tuple(sorted(set(dependency_keys)))
        if not keys:
            return

        frontier = self.frontier()
        placeholders = ",".join("?" for _ in keys)
        self.db.execute(
            f"""
            UPDATE context_projections
            SET stale = 1,
                stale_reason = ?,
                stale_at_frontier = ?
            WHERE stale = 0
              AND id IN (
                SELECT projection_id
                FROM context_projection_dependencies
                WHERE dependency_key IN ({placeholders})
              )
            """,
            (reason, frontier, *keys),
        )
