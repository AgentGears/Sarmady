from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sarmady.kernel.identity import Agent

from ._codec import iso


class IdentityStoreMixin:
    def register_agent(self, agent: Agent) -> None:
        with self._write_transaction():
            self.db.execute(
                "INSERT INTO agents(id, name, created_at) VALUES (?, ?, ?)",
                (str(agent.id), agent.name, iso(agent.created_at)),
            )
            self._log("Agent", agent.id, agent.created_at)

    def agent(self, agent_id: UUID) -> Agent | None:
        row = self.db.execute(
            "SELECT * FROM agents WHERE id = ?", (str(agent_id),)
        ).fetchone()
        if row is None:
            return None
        return Agent(
            id=UUID(row["id"]),
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
