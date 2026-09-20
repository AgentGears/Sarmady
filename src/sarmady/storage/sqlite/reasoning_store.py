from __future__ import annotations

import json
from datetime import datetime

from sarmady.cognition import ReasoningMode, ReasoningPolicy, ReasoningRequirement

from ._codec import iso


class ReasoningStoreMixin:
    def register_reasoning_policy(
        self,
        policy: ReasoningPolicy,
        *,
        registered_at: datetime,
    ) -> ReasoningPolicy:
        """Persist an immutable reasoning-policy definition idempotently.

        A policy id may never be rebound to different semantics or provenance.
        Policy registration is operational configuration and does not advance
        the epistemic semantic frontier.
        """

        if registered_at.tzinfo is None or registered_at.utcoffset() is None:
            raise ValueError("registered_at must be timezone-aware")

        stages_json = json.dumps(list(policy.stages), ensure_ascii=False)
        requirements_json = json.dumps(
            [
                {"key": item.key, "description": item.description}
                for item in policy.requirements
            ],
            ensure_ascii=False,
            sort_keys=True,
        )

        with self._write_transaction():
            row = self.db.execute(
                "SELECT * FROM reasoning_policies WHERE id = ?",
                (policy.id,),
            ).fetchone()
            if row is not None:
                existing = self._reasoning_policy_from_row(row)
                if existing != policy or row["fingerprint"] != policy.fingerprint:
                    raise ValueError(
                        f"reasoning policy id {policy.id!r} is already bound to different semantics"
                    )
                return existing

            fingerprint_owner = self.db.execute(
                "SELECT id FROM reasoning_policies WHERE fingerprint = ?",
                (policy.fingerprint,),
            ).fetchone()
            if fingerprint_owner is not None:
                raise ValueError(
                    "reasoning policy fingerprint is already registered under "
                    f"{fingerprint_owner['id']!r}"
                )

            self.db.execute(
                """
                INSERT INTO reasoning_policies(
                    id, version, mode, stages_json, requirements_json,
                    source_ref, source_sha256, fingerprint, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.id,
                    policy.version,
                    policy.mode.value,
                    stages_json,
                    requirements_json,
                    policy.source_ref,
                    policy.source_sha256,
                    policy.fingerprint,
                    iso(registered_at),
                ),
            )
        return policy

    def reasoning_policy(self, policy_id: str) -> ReasoningPolicy | None:
        row = self.db.execute(
            "SELECT * FROM reasoning_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
        return self._reasoning_policy_from_row(row) if row is not None else None

    def reasoning_policy_fingerprint(self, policy_id: str) -> str | None:
        row = self.db.execute(
            "SELECT fingerprint FROM reasoning_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
        return row["fingerprint"] if row is not None else None

    @staticmethod
    def _reasoning_policy_from_row(row) -> ReasoningPolicy:
        requirements = tuple(
            ReasoningRequirement(item["key"], item["description"])
            for item in json.loads(row["requirements_json"])
        )
        policy = ReasoningPolicy(
            id=row["id"],
            version=row["version"],
            mode=ReasoningMode(row["mode"]),
            stages=tuple(json.loads(row["stages_json"])),
            requirements=requirements,
            source_ref=row["source_ref"],
            source_sha256=row["source_sha256"],
        )
        if policy.fingerprint != row["fingerprint"]:
            raise RuntimeError(
                f"persisted reasoning policy {policy.id!r} failed fingerprint verification"
            )
        return policy
