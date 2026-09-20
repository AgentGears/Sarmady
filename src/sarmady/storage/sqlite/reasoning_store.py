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
                exact_match = (
                    existing == policy
                    and row["fingerprint"] == policy.fingerprint
                )
                legacy_case_only_match = self._equivalent_modulo_digest_case(
                    existing,
                    policy,
                )
                if not exact_match and not legacy_case_only_match:
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
    def _equivalent_modulo_digest_case(
        existing: ReasoningPolicy,
        candidate: ReasoningPolicy,
    ) -> bool:
        """Treat pre-hardening SHA-256 case as representation, not semantics.

        Legacy releases accepted uppercase or mixed-case hex and fingerprinted
        that exact spelling. A current canonical lowercase object with otherwise
        identical fields must remain an idempotent registration, while any
        substantive policy or provenance difference still fails closed.
        """

        existing_digest = existing.source_sha256
        candidate_digest = candidate.source_sha256
        normalized_existing = (
            existing_digest.lower() if existing_digest is not None else None
        )
        normalized_candidate = (
            candidate_digest.lower() if candidate_digest is not None else None
        )
        return (
            existing.id == candidate.id
            and existing.version == candidate.version
            and existing.mode == candidate.mode
            and existing.stages == candidate.stages
            and existing.requirements == candidate.requirements
            and existing.source_ref == candidate.source_ref
            and normalized_existing == normalized_candidate
        )

    @staticmethod
    def _reasoning_policy_from_row(row) -> ReasoningPolicy:
        requirements = tuple(
            ReasoningRequirement(item["key"], item["description"])
            for item in json.loads(row["requirements_json"])
        )
        persisted_digest = row["source_sha256"]
        construction_digest = persisted_digest
        legacy_noncanonical_digest = (
            persisted_digest is not None
            and persisted_digest != persisted_digest.lower()
        )
        if legacy_noncanonical_digest:
            # Pre-hardening releases accepted uppercase/mixed-case SHA-256
            # provenance. Validate the digest through the current constructor
            # using its canonical lowercase form, then restore the exact legacy
            # spelling solely for fingerprint verification and durable reads.
            construction_digest = persisted_digest.lower()

        policy = ReasoningPolicy(
            id=row["id"],
            version=row["version"],
            mode=ReasoningMode(row["mode"]),
            stages=tuple(json.loads(row["stages_json"])),
            requirements=requirements,
            source_ref=row["source_ref"],
            source_sha256=construction_digest,
        )
        if legacy_noncanonical_digest:
            object.__setattr__(policy, "source_sha256", persisted_digest)
        if policy.fingerprint != row["fingerprint"]:
            raise RuntimeError(
                f"persisted reasoning policy {policy.id!r} failed fingerprint verification"
            )
        return policy
