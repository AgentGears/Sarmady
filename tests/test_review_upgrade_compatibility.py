from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from sarmady.cognition import ReasoningMode, ReasoningPolicy
from sarmady.context import ContextProjection, ContextRequest, CoverageStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_v5_projection_is_migrated_to_unproven_and_stale(tmp_path) -> None:
    path = tmp_path / "legacy-v5-projection.db"
    request_id = uuid4()
    projection_id = uuid4()

    # Build a physically current database, then shape its durable projection
    # state exactly as a pre-v6 database could contain it: fresh and without a
    # wildcard proof marker.
    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(request_id, "legacy context", 512)
        projection = ContextProjection(
            id=projection_id,
            request_id=request_id,
            snapshot_id="sqlite:0",
            canonical_frontier="0",
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:legacy-v5",
            compiler_version="legacy-v5",
        )
        store.register_context_projection(projection, request=request)

    legacy = sqlite3.connect(path)
    try:
        legacy.execute(
            "DELETE FROM context_projection_dependencies WHERE projection_id = ?",
            (str(projection_id),),
        )
        legacy.execute(
            """
            UPDATE context_projections
            SET stale = 0, stale_reason = NULL, stale_at_frontier = NULL
            WHERE id = ?
            """,
            (str(projection_id),),
        )
        legacy.execute("PRAGMA user_version = 5")
        legacy.commit()
    finally:
        legacy.close()

    with SQLiteCanonicalStore(path) as upgraded:
        assert upgraded.projection_is_stale(projection_id)
        assert (
            upgraded.projection_stale_reason(projection_id)
            == "schema-v6-unproven-lineage-migration"
        )
        dependency = upgraded.db.execute(
            """
            SELECT 1
            FROM context_projection_dependencies
            WHERE projection_id = ? AND dependency_key = 'semantic:*'
            """,
            (str(projection_id),),
        ).fetchone()
        assert dependency is not None
        assert int(upgraded.db.execute("PRAGMA user_version").fetchone()[0]) == 6


def test_legacy_uppercase_reasoning_policy_remains_readable(tmp_path) -> None:
    path = tmp_path / "legacy-uppercase-policy.db"
    policy_id = "legacy:uppercase:v1"
    uppercase_digest = "A" * 64

    canonical = ReasoningPolicy(
        id=policy_id,
        version="1",
        mode=ReasoningMode.DIRECT,
        stages=(),
        requirements=(),
        source_ref="legacy-source",
        source_sha256=uppercase_digest.lower(),
    )
    # Reproduce the exact object semantics used by the previous release, which
    # accepted uppercase and therefore fingerprinted the uppercase spelling.
    object.__setattr__(canonical, "source_sha256", uppercase_digest)
    legacy_fingerprint = canonical.fingerprint

    with SQLiteCanonicalStore(path) as store:
        store.db.execute(
            """
            INSERT INTO reasoning_policies(
                id, version, mode, stages_json, requirements_json,
                source_ref, source_sha256, fingerprint, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id,
                "1",
                ReasoningMode.DIRECT.value,
                json.dumps([]),
                json.dumps([]),
                "legacy-source",
                uppercase_digest,
                legacy_fingerprint,
                T0.isoformat(),
            ),
        )
        store.db.commit()

        restored = store.reasoning_policy(policy_id)
        assert restored is not None
        assert restored.source_sha256 == uppercase_digest
        assert restored.fingerprint == legacy_fingerprint
        assert store.reasoning_policy_fingerprint(policy_id) == legacy_fingerprint
