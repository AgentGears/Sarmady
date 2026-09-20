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


_UNPROVEN_CONTEXT_DEPENDENCY = "semantic:*"


class ProjectionStoreMixin:
    def register_context_projection(
        self,
        projection: ContextProjection,
        *,
        request: ContextRequest,
        dependency_keys: tuple[str, ...] = (),
        dependency_capture: object | None = None,
    ) -> bool:
        """Persist a complete immutable projection; return whether it is stale.

        Dependency-aware race handling is enabled only when registration carries
        a one-shot capture produced by ``context_read_snapshot``. A raw caller
        declaration is not treated as proof of completeness. Proven lineage is
        bound to both the captured semantic dependencies and the projection
        items successfully read inside that pinned snapshot. Unproven
        projections may register only at the current frontier and receive a
        wildcard dependency so any later semantic mutation stales them.
        """

        if projection.request_id != request.id:
            raise ValueError("projection must reference the persisted context request")

        # Reconstruct through the current public invariant before consuming a
        # one-shot lineage capture or writing anything. Historical rows may be
        # rehydrated with legacy values (for example nonpositive latency), but
        # those compatibility objects are read-only representations and cannot
        # propagate invalid state into a fresh store.
        request = ContextRequest(
            id=request.id,
            query=request.query,
            token_budget=request.token_budget,
            latency_budget_ms=request.latency_budget_ms,
            goal_ref=request.goal_ref,
            task_ref=request.task_ref,
            coverage_requirements=tuple(request.coverage_requirements),
            exact_requirements=tuple(request.exact_requirements),
            known_at=request.known_at,
            valid_at=request.valid_at,
        )

        canonical_frontier = int(projection.canonical_frontier)
        required_refs = frozenset(
            (item.ref_type, item.ref_id) for item in projection.items
        )
        captured_lineage = self._consume_context_dependency_capture(
            dependency_capture,
            frontier=canonical_frontier,
            required_refs=required_refs,
        )
        declared_dependencies = set(dependency_keys)
        if captured_lineage is not None:
            captured_dependencies, captured_refs = captured_lineage
            if declared_dependencies and declared_dependencies != set(
                captured_dependencies
            ):
                raise ValueError(
                    "declared dependency_keys do not match captured context dependencies"
                )
            # A closed but untouched capture proves no semantic lineage. Treat
            # it as unproven so an old frontier cannot be blessed simply by
            # opening and closing a snapshot without consulting canonical state.
            lineage_proven = bool(captured_dependencies or captured_refs)
            effective_dependencies = set(captured_dependencies)
            if not lineage_proven:
                effective_dependencies.add(_UNPROVEN_CONTEXT_DEPENDENCY)
        else:
            lineage_proven = False
            effective_dependencies = declared_dependencies
            effective_dependencies.add(_UNPROVEN_CONTEXT_DEPENDENCY)

        with self._write_transaction():
            current_frontier = self.frontier()
            if canonical_frontier < 0:
                raise ValueError(
                    "projection canonical_frontier cannot be negative"
                )
            if canonical_frontier > current_frontier:
                raise ValueError(
                    "projection canonical_frontier cannot exceed current frontier"
                )
            if not lineage_proven and canonical_frontier < current_frontier:
                raise ValueError(
                    "projection compiled before current frontier requires captured dependency lineage"
                )
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
            changed_dependencies = self._dependency_keys_changed_since(canonical_frontier)
            wildcard_changed = (
                _UNPROVEN_CONTEXT_DEPENDENCY in effective_dependencies
                and canonical_frontier < current_frontier
            )
            stale = wildcard_changed or bool(
                effective_dependencies & changed_dependencies
            )
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
                    "dependency-changed-before-registration" if stale else None,
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
                    for dependency in sorted(effective_dependencies)
                ],
            )
        return stale

    def _dependency_keys_changed_since(self, frontier: int) -> set[str]:
        """Return context dependency keys changed after a semantic frontier.

        Registration uses this under the write lock so unrelated semantic-log
        activity cannot stale a freshly compiled projection with proven
        lineage. SEEN/USED memory telemetry is intentionally excluded because
        it does not change memory admission/lifecycle state.
        """

        rows = self.db.execute(
            """
            SELECT DISTINCT 'epistemic-key:' || c.subject || ':' || c.predicate AS dependency_key
            FROM semantic_log l
            JOIN claims c ON l.kind = 'Claim' AND l.ref_id = c.id
            WHERE l.seq > ?

            UNION

            SELECT DISTINCT 'epistemic-key:' || c.subject || ':' || c.predicate AS dependency_key
            FROM semantic_log l
            JOIN claim_relations r ON l.kind = 'ClaimRelation' AND l.ref_id = r.id
            JOIN claims c ON c.id = r.source_claim_id
            WHERE l.seq > ?

            UNION

            SELECT DISTINCT 'memory-entry:' || m.id AS dependency_key
            FROM semantic_log l
            JOIN memory_entries m ON l.kind = 'MemoryEntry' AND l.ref_id = m.id
            WHERE l.seq > ?

            UNION

            SELECT DISTINCT 'memory-entry:' || e.memory_entry_id AS dependency_key
            FROM semantic_log l
            JOIN memory_lifecycle_events e
              ON l.kind = 'MemoryLifecycleEvent' AND l.ref_id = e.id
            WHERE l.seq > ?
              AND e.event_kind NOT IN ('SEEN', 'USED')
            """,
            (frontier, frontier, frontier, frontier),
        ).fetchall()
        return {row["dependency_key"] for row in rows}

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

        persisted_latency = row["latency_budget_ms"]
        request = ContextRequest(
            id=UUID(row["id"]),
            query=row["query"],
            token_budget=int(row["token_budget"]),
            latency_budget_ms=(
                persisted_latency
                if persisted_latency is None or persisted_latency > 0
                else None
            ),
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
        if persisted_latency is not None and persisted_latency <= 0:
            object.__setattr__(request, "latency_budget_ms", persisted_latency)
        return request

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
                   OR dependency_key = ?
              )
            """,
            (reason, frontier, *keys, _UNPROVEN_CONTEXT_DEPENDENCY),
        )
