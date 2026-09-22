from __future__ import annotations

import sqlite3
from uuid import NAMESPACE_URL, uuid5

from sarmady.memory import MemoryLifecycleEventKind


SCHEMA_VERSION = 7


def initialize_schema(db: sqlite3.Connection) -> None:
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if version not in {0, 1, 2, 3, 4, 5, 6, SCHEMA_VERSION}:
        raise RuntimeError(
            f"unsupported Sarmady SQLite schema version {version}; "
            f"expected <= {SCHEMA_VERSION}"
        )

    # v0-v5 databases can be upgraded in place. v5 changed only the
    # backwards-compatible JSON encoding inside coverage_requirements_json.
    # v6 adds no columns; it establishes conservative lineage semantics for
    # projections created before dependency capture could prove completeness.
    # v7 adds durable context-need decisions and parent/child request lineage.
    # The schema version is deliberately advanced only after every migration
    # succeeds. If migration is interrupted, the prior version remains durable
    # and the idempotent migration is retried on the next open.
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS semantic_log (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_log_object
            ON semantic_log(kind, ref_id);

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id),
            source_ref TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            digest TEXT
        );

        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            value_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            derivation_ref TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_claims_subject_predicate
            ON claims(subject, predicate);

        CREATE TABLE IF NOT EXISTS claim_relations (
            id TEXT PRIMARY KEY,
            source_claim_id TEXT NOT NULL REFERENCES claims(id),
            target_claim_id TEXT NOT NULL REFERENCES claims(id),
            kind TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS claim_heads (
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            claim_id TEXT NOT NULL REFERENCES claims(id),
            PRIMARY KEY(subject, predicate)
        );

        CREATE TABLE IF NOT EXISTS memory_entries (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            lifecycle TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_target
            ON memory_entries(target_type, target_id, lifecycle);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_unique_target
            ON memory_entries(target_type, target_id);

        CREATE TABLE IF NOT EXISTS memory_lifecycle_events (
            id TEXT PRIMARY KEY,
            memory_entry_id TEXT NOT NULL REFERENCES memory_entries(id),
            event_kind TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            source TEXT NOT NULL,
            reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_memory_lifecycle_entry
            ON memory_lifecycle_events(memory_entry_id, occurred_at);

        CREATE TABLE IF NOT EXISTS context_requests (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            token_budget INTEGER NOT NULL CHECK(token_budget > 0),
            latency_budget_ms INTEGER,
            goal_ref TEXT,
            task_ref TEXT,
            coverage_requirements_json TEXT NOT NULL,
            known_at TEXT,
            valid_at TEXT
        );

        CREATE TABLE IF NOT EXISTS context_projections (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            canonical_frontier INTEGER NOT NULL,
            manifest_digest TEXT NOT NULL,
            compiler_version TEXT NOT NULL,
            coverage_status TEXT NOT NULL,
            stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0, 1)),
            stale_reason TEXT,
            stale_at_frontier INTEGER
        );

        CREATE TABLE IF NOT EXISTS context_projection_dependencies (
            projection_id TEXT NOT NULL
                REFERENCES context_projections(id) ON DELETE CASCADE,
            dependency_key TEXT NOT NULL,
            PRIMARY KEY(projection_id, dependency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_projection_dependency_key
            ON context_projection_dependencies(dependency_key);

        CREATE TABLE IF NOT EXISTS context_projection_details (
            projection_id TEXT PRIMARY KEY
                REFERENCES context_projections(id) ON DELETE CASCADE,
            conflict_refs_json TEXT NOT NULL,
            unresolved_gaps_json TEXT NOT NULL,
            omitted_refs_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS context_projection_items (
            projection_id TEXT NOT NULL
                REFERENCES context_projections(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            ref_type TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            role TEXT NOT NULL,
            provenance_refs_json TEXT NOT NULL,
            PRIMARY KEY(projection_id, ordinal)
        );

        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reasoning_policies (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            mode TEXT NOT NULL,
            stages_json TEXT NOT NULL,
            requirements_json TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_sha256 TEXT,
            fingerprint TEXT NOT NULL UNIQUE,
            registered_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cognitive_requests (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES agents(id),
            context_projection_id TEXT NOT NULL REFERENCES context_projections(id),
            operation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reasoning_policy_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cognitive_requests_agent
            ON cognitive_requests(agent_id);

        CREATE TABLE IF NOT EXISTS model_invocations (
            id TEXT PRIMARY KEY,
            cognitive_request_id TEXT NOT NULL REFERENCES cognitive_requests(id),
            model_binding TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_code TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_model_invocations_request
            ON model_invocations(cognitive_request_id);

        CREATE TABLE IF NOT EXISTS generated_artifacts (
            id TEXT PRIMARY KEY,
            invocation_id TEXT NOT NULL REFERENCES model_invocations(id),
            artifact_kind TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_generated_artifacts_invocation
            ON generated_artifacts(invocation_id);

        CREATE TABLE IF NOT EXISTS context_need_decisions (
            id TEXT PRIMARY KEY,
            context_need_artifact_id TEXT NOT NULL UNIQUE
                REFERENCES generated_artifacts(id),
            decision TEXT NOT NULL CHECK(decision IN ('ACCEPTED', 'REJECTED')),
            decided_at TEXT NOT NULL,
            reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
            decision_source TEXT NOT NULL CHECK(length(trim(decision_source)) > 0),
            parent_invocation_id TEXT NOT NULL REFERENCES model_invocations(id),
            parent_cognitive_request_id TEXT NOT NULL REFERENCES cognitive_requests(id),
            parent_context_projection_id TEXT NOT NULL REFERENCES context_projections(id),
            parent_context_request_id TEXT NOT NULL REFERENCES context_requests(id),
            child_context_request_id TEXT REFERENCES context_requests(id),
            CHECK(
                (decision = 'ACCEPTED' AND child_context_request_id IS NOT NULL)
                OR (decision = 'REJECTED' AND child_context_request_id IS NULL)
            ),
            CHECK(
                child_context_request_id IS NULL
                OR child_context_request_id <> parent_context_request_id
            )
        );
        CREATE INDEX IF NOT EXISTS idx_context_need_decisions_parent_request
            ON context_need_decisions(parent_context_request_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_context_need_decisions_child_request
            ON context_need_decisions(child_context_request_id)
            WHERE child_context_request_id IS NOT NULL;
        """
    )
    _backfill_legacy_memory_created_events(db)
    if version < 6:
        _backfill_legacy_projection_lineage(db)

    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()


def _backfill_legacy_memory_created_events(db: sqlite3.Connection) -> None:
    """Give pre-v2 memory admissions an explicit canonical CREATED event."""

    rows = db.execute(
        """
        SELECT m.id, m.created_at
        FROM memory_entries m
        LEFT JOIN memory_lifecycle_events e
          ON e.memory_entry_id = m.id
        WHERE e.id IS NULL
        ORDER BY m.rowid
        """
    ).fetchall()
    if not rows:
        return

    db.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            event_id = uuid5(
                NAMESPACE_URL,
                f"sarmady:memory-created:{row['id']}",
            )
            db.execute(
                """
                INSERT OR IGNORE INTO memory_lifecycle_events
                (id, memory_entry_id, event_kind, occurred_at, source, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event_id),
                    row["id"],
                    MemoryLifecycleEventKind.CREATED.value,
                    row["created_at"],
                    "schema-migration-v2",
                    "backfill legacy memory admission",
                ),
            )
            exists = db.execute(
                """
                SELECT 1 FROM semantic_log
                WHERE kind = 'MemoryLifecycleEvent' AND ref_id = ?
                """,
                (str(event_id),),
            ).fetchone()
            if exists is None:
                db.execute(
                    """
                    INSERT INTO semantic_log(kind, ref_id, recorded_at)
                    VALUES ('MemoryLifecycleEvent', ?, ?)
                    """,
                    (str(event_id), row["created_at"]),
                )
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


def _backfill_legacy_projection_lineage(db: sqlite3.Connection) -> None:
    """Conservatively invalidate projections created before lineage proofs.

    Pre-v6 dependency rows were caller-declared and therefore cannot prove that
    every semantic dependency was captured. Preserve those rows for audit, add
    the unproven-lineage wildcard, and force any previously fresh projection to
    be recompiled before cognition can use it under v6 semantics.
    """

    rows = db.execute("SELECT id FROM context_projections").fetchall()
    if not rows:
        return

    frontier = int(
        db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS frontier FROM semantic_log"
        ).fetchone()["frontier"]
    )
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            """
            INSERT OR IGNORE INTO context_projection_dependencies(
                projection_id, dependency_key
            ) VALUES (?, 'semantic:*')
            """,
            [(row["id"],) for row in rows],
        )
        db.execute(
            """
            UPDATE context_projections
            SET stale = 1,
                stale_reason = 'schema-v6-unproven-lineage-migration',
                stale_at_frontier = ?
            WHERE stale = 0
            """,
            (frontier,),
        )
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()
