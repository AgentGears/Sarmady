from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sarmady.cognition import CognitiveRequest, GeneratedArtifact, ModelInvocation

from ._codec import iso


class CognitiveStoreMixin:
    def create_cognitive_request(self, request: CognitiveRequest) -> None:
        if self.agent(request.agent_id) is None:
            raise ValueError(f"unknown agent {request.agent_id}")
        projection = self.context_projection(request.context_projection_id)
        if projection is None:
            raise ValueError(
                f"unknown context projection {request.context_projection_id}"
            )
        if self.projection_is_stale(request.context_projection_id):
            raise ValueError("cannot invoke cognition from a stale context projection")

        with self._write_transaction():
            # Revalidate after obtaining the write lock so a relevant state change
            # cannot race request admission.
            if self.projection_is_stale(request.context_projection_id):
                raise ValueError("cannot invoke cognition from a stale context projection")
            if (
                request.reasoning_policy_id is not None
                and self.reasoning_policy(request.reasoning_policy_id) is None
            ):
                raise ValueError(
                    f"unknown reasoning policy {request.reasoning_policy_id!r}"
                )
            self.db.execute(
                """
                INSERT INTO cognitive_requests(
                    id, agent_id, context_projection_id, operation, created_at, reasoning_policy_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request.id),
                    str(request.agent_id),
                    str(request.context_projection_id),
                    request.operation,
                    iso(request.created_at),
                    request.reasoning_policy_id,
                ),
            )

    def cognitive_request(self, request_id: UUID) -> CognitiveRequest | None:
        row = self.db.execute(
            "SELECT * FROM cognitive_requests WHERE id = ?", (str(request_id),)
        ).fetchone()
        if row is None:
            return None
        return CognitiveRequest(
            id=UUID(row["id"]),
            agent_id=UUID(row["agent_id"]),
            context_projection_id=UUID(row["context_projection_id"]),
            operation=row["operation"],
            created_at=datetime.fromisoformat(row["created_at"]),
            reasoning_policy_id=row["reasoning_policy_id"],
        )

    def start_model_invocation(self, invocation: ModelInvocation) -> None:
        if invocation.completed_at is not None or invocation.error_code is not None:
            raise ValueError("a new invocation must begin incomplete and error-free")

        with self._write_transaction():
            request_row = self.db.execute(
                "SELECT * FROM cognitive_requests WHERE id = ?",
                (str(invocation.cognitive_request_id),),
            ).fetchone()
            if request_row is None:
                raise ValueError(
                    f"unknown cognitive request {invocation.cognitive_request_id}"
                )

            projection_id = UUID(request_row["context_projection_id"])
            if self.projection_is_stale(projection_id):
                raise ValueError(
                    "cannot start model invocation from a stale context projection"
                )

            self.db.execute(
                """
                INSERT INTO model_invocations(
                    id, cognitive_request_id, model_binding,
                    started_at, completed_at, error_code
                ) VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (
                    str(invocation.id),
                    str(invocation.cognitive_request_id),
                    invocation.model_binding,
                    iso(invocation.started_at),
                ),
            )

    def complete_model_invocation(
        self,
        invocation_id: UUID,
        artifact: GeneratedArtifact,
        *,
        completed_at: datetime,
    ) -> ModelInvocation:
        if artifact.invocation_id != invocation_id:
            raise ValueError("artifact must reference the completed invocation")
        with self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM model_invocations WHERE id = ?",
                (str(invocation_id),),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown invocation {invocation_id}")
            if row["completed_at"] is not None:
                raise ValueError("model invocation is already terminal")
            started_at = datetime.fromisoformat(row["started_at"])
            if completed_at < started_at:
                raise ValueError("completed_at cannot precede started_at")
            if artifact.created_at < started_at or artifact.created_at > completed_at:
                raise ValueError(
                    "artifact creation time must fall within the invocation interval"
                )

            self.db.execute(
                """
                UPDATE model_invocations
                SET completed_at = ?, error_code = NULL
                WHERE id = ?
                """,
                (iso(completed_at), str(invocation_id)),
            )
            self.db.execute(
                """
                INSERT INTO generated_artifacts(
                    id, invocation_id, artifact_kind, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(artifact.id),
                    str(artifact.invocation_id),
                    artifact.artifact_kind,
                    artifact.content,
                    iso(artifact.created_at),
                ),
            )

        return ModelInvocation(
            id=UUID(row["id"]),
            cognitive_request_id=UUID(row["cognitive_request_id"]),
            model_binding=row["model_binding"],
            started_at=started_at,
            completed_at=completed_at,
            error_code=None,
        )

    def fail_model_invocation(
        self,
        invocation_id: UUID,
        *,
        completed_at: datetime,
        error_code: str,
    ) -> ModelInvocation:
        if not error_code.strip():
            raise ValueError("error_code is required")
        with self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM model_invocations WHERE id = ?",
                (str(invocation_id),),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown invocation {invocation_id}")
            if row["completed_at"] is not None:
                raise ValueError("model invocation is already terminal")
            started_at = datetime.fromisoformat(row["started_at"])
            if completed_at < started_at:
                raise ValueError("completed_at cannot precede started_at")
            self.db.execute(
                """
                UPDATE model_invocations
                SET completed_at = ?, error_code = ?
                WHERE id = ?
                """,
                (iso(completed_at), error_code, str(invocation_id)),
            )

        return ModelInvocation(
            id=UUID(row["id"]),
            cognitive_request_id=UUID(row["cognitive_request_id"]),
            model_binding=row["model_binding"],
            started_at=started_at,
            completed_at=completed_at,
            error_code=error_code,
        )

    def invocation(self, invocation_id: UUID) -> ModelInvocation | None:
        row = self.db.execute(
            "SELECT * FROM model_invocations WHERE id = ?",
            (str(invocation_id),),
        ).fetchone()
        if row is None:
            return None
        return ModelInvocation(
            id=UUID(row["id"]),
            cognitive_request_id=UUID(row["cognitive_request_id"]),
            model_binding=row["model_binding"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
            error_code=row["error_code"],
        )

    def artifact(self, artifact_id: UUID) -> GeneratedArtifact | None:
        row = self.db.execute(
            "SELECT * FROM generated_artifacts WHERE id = ?",
            (str(artifact_id),),
        ).fetchone()
        if row is None:
            return None
        return GeneratedArtifact(
            id=UUID(row["id"]),
            invocation_id=UUID(row["invocation_id"]),
            artifact_kind=row["artifact_kind"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def invocations_for_agent(self, agent_id: UUID) -> tuple[ModelInvocation, ...]:
        rows = self.db.execute(
            """
            SELECT i.*
            FROM model_invocations i
            JOIN cognitive_requests r ON r.id = i.cognitive_request_id
            WHERE r.agent_id = ?
            ORDER BY i.rowid
            """,
            (str(agent_id),),
        ).fetchall()
        return tuple(
            ModelInvocation(
                id=UUID(row["id"]),
                cognitive_request_id=UUID(row["cognitive_request_id"]),
                model_binding=row["model_binding"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=(
                    datetime.fromisoformat(row["completed_at"])
                    if row["completed_at"] is not None
                    else None
                ),
                error_code=row["error_code"],
            )
            for row in rows
        )
