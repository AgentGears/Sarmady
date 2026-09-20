from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import ReasoningMode, ReasoningPolicy
from sarmady.context import ContextProjection, ContextRequest, CoverageStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.storage.sqlite import schema as schema_module


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _shape_projection_as_legacy_v5(path, projection_id) -> None:
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


def _seed_projection(path):
    request_id = uuid4()
    projection_id = uuid4()
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
    _shape_projection_as_legacy_v5(path, projection_id)
    return projection_id


def test_v5_projection_is_migrated_to_unproven_and_stale(tmp_path) -> None:
    path = tmp_path / "legacy-v5-projection.db"
    projection_id = _seed_projection(path)

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


def test_v6_version_bump_waits_for_successful_lineage_migration(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "interrupted-v6-migration.db"
    projection_id = _seed_projection(path)
    original_migration = schema_module._backfill_legacy_projection_lineage

    def fail_lineage_migration(db) -> None:
        raise RuntimeError("simulated lineage migration failure")

    monkeypatch.setattr(
        schema_module,
        "_backfill_legacy_projection_lineage",
        fail_lineage_migration,
    )

    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        with pytest.raises(RuntimeError, match="simulated lineage migration failure"):
            schema_module.initialize_schema(db)
        assert int(db.execute("PRAGMA user_version").fetchone()[0]) == 5
    finally:
        db.close()

    monkeypatch.setattr(
        schema_module,
        "_backfill_legacy_projection_lineage",
        original_migration,
    )
    with SQLiteCanonicalStore(path) as upgraded:
        assert int(upgraded.db.execute("PRAGMA user_version").fetchone()[0]) == 6
        assert upgraded.projection_is_stale(projection_id)
        assert (
            upgraded.projection_stale_reason(projection_id)
            == "schema-v6-unproven-lineage-migration"
        )


def _insert_legacy_uppercase_policy(store, policy_id: str, uppercase_digest: str) -> str:
    legacy = ReasoningPolicy(
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
    object.__setattr__(legacy, "source_sha256", uppercase_digest)
    legacy_fingerprint = legacy.fingerprint
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
    return legacy_fingerprint


def test_legacy_uppercase_reasoning_policy_remains_readable(tmp_path) -> None:
    path = tmp_path / "legacy-uppercase-policy.db"
    policy_id = "legacy:uppercase:v1"
    uppercase_digest = "A" * 64

    with SQLiteCanonicalStore(path) as store:
        legacy_fingerprint = _insert_legacy_uppercase_policy(
            store,
            policy_id,
            uppercase_digest,
        )

        restored = store.reasoning_policy(policy_id)
        assert restored is not None
        assert restored.source_sha256 == uppercase_digest
        assert restored.fingerprint == legacy_fingerprint
        assert store.reasoning_policy_fingerprint(policy_id) == legacy_fingerprint


def test_lowercase_policy_registration_is_idempotent_against_legacy_uppercase_row(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-uppercase-idempotency.db"
    policy_id = "legacy:uppercase:idempotent:v1"
    uppercase_digest = "B" * 64

    with SQLiteCanonicalStore(path) as store:
        legacy_fingerprint = _insert_legacy_uppercase_policy(
            store,
            policy_id,
            uppercase_digest,
        )
        canonical = ReasoningPolicy(
            id=policy_id,
            version="1",
            mode=ReasoningMode.DIRECT,
            stages=(),
            requirements=(),
            source_ref="legacy-source",
            source_sha256=uppercase_digest.lower(),
        )

        registered = store.register_reasoning_policy(
            canonical,
            registered_at=T0 + timedelta(minutes=1),
        )

        assert registered.source_sha256 == uppercase_digest
        assert registered.fingerprint == legacy_fingerprint
        row = store.db.execute(
            "SELECT source_sha256, fingerprint FROM reasoning_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
        assert row["source_sha256"] == uppercase_digest
        assert row["fingerprint"] == legacy_fingerprint


def test_legacy_policy_object_is_canonicalized_before_write_to_fresh_store(
    tmp_path,
) -> None:
    source_path = tmp_path / "legacy-policy-source.db"
    destination_path = tmp_path / "fresh-policy-destination.db"
    policy_id = "legacy:uppercase:copy:v1"
    uppercase_digest = "C" * 64

    with SQLiteCanonicalStore(source_path) as source:
        legacy_fingerprint = _insert_legacy_uppercase_policy(
            source,
            policy_id,
            uppercase_digest,
        )
        legacy_object = source.reasoning_policy(policy_id)
        assert legacy_object is not None
        assert legacy_object.source_sha256 == uppercase_digest
        assert legacy_object.fingerprint == legacy_fingerprint

    with SQLiteCanonicalStore(destination_path) as destination:
        registered = destination.register_reasoning_policy(
            legacy_object,
            registered_at=T0 + timedelta(minutes=2),
        )
        assert registered.source_sha256 == uppercase_digest.lower()
        assert registered.fingerprint != legacy_fingerprint
        row = destination.db.execute(
            "SELECT source_sha256, fingerprint FROM reasoning_policies WHERE id = ?",
            (policy_id,),
        ).fetchone()
        assert row["source_sha256"] == uppercase_digest.lower()
        assert row["fingerprint"] == registered.fingerprint
