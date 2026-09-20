from __future__ import annotations

from uuid import UUID


class ProjectionStoreMixin:
    def register_context_projection(
        self,
        *,
        projection_id: UUID,
        request_id: UUID,
        snapshot_id: str,
        canonical_frontier: int,
        manifest_digest: str,
        compiler_version: str,
        coverage_status: str,
        dependency_keys: tuple[str, ...],
    ) -> bool:
        """Persist projection lineage; return whether registration is stale."""

        with self._write_transaction():
            current_frontier = self.frontier()
            stale = current_frontier != canonical_frontier
            self.db.execute(
                """
                INSERT INTO context_projections(
                    id, request_id, snapshot_id, canonical_frontier,
                    manifest_digest, compiler_version, coverage_status,
                    stale, stale_reason, stale_at_frontier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(projection_id),
                    str(request_id),
                    snapshot_id,
                    canonical_frontier,
                    manifest_digest,
                    compiler_version,
                    coverage_status,
                    1 if stale else 0,
                    "frontier-advanced-before-registration" if stale else None,
                    current_frontier if stale else None,
                ),
            )
            self.db.executemany(
                """
                INSERT INTO context_projection_dependencies
                (projection_id, dependency_key) VALUES (?, ?)
                """,
                [
                    (str(projection_id), dependency)
                    for dependency in sorted(set(dependency_keys))
                ],
            )
        return stale

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
