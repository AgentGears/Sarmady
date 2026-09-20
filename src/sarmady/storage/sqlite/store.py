from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sarmady.epistemic.models import Claim, ClaimRelation, ClaimRelationKind, Evidence, Event
from sarmady.memory.models import MemoryEntry, MemoryKind, MemoryLifecycle


class SQLiteCanonicalStore:
    """Minimal durable store for the first persistent epistemic vertical slice.

    Canonical history and materialized current heads are stored separately.
    `claim_heads` is rebuildable; claims, relations, evidence, events and memory
    admissions are the durable semantic record.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self._init_schema()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SQLiteCanonicalStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                ref_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );

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
                ON claims(subject, predicate, recorded_at);

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
            """
        )
        self.db.commit()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value is not None else None

    def _log(self, kind: str, ref_id: UUID, recorded_at: datetime) -> None:
        self.db.execute(
            "INSERT INTO semantic_log(kind, ref_id, recorded_at) VALUES (?, ?, ?)",
            (kind, str(ref_id), self._iso(recorded_at)),
        )

    def frontier(self) -> int:
        row = self.db.execute("SELECT COALESCE(MAX(seq), 0) AS frontier FROM semantic_log").fetchone()
        return int(row["frontier"])

    def commit_claim_bundle(
        self,
        *,
        event: Event,
        evidence: Evidence,
        claim: Claim,
        memory: MemoryEntry,
        relation: ClaimRelation | None = None,
    ) -> None:
        """Atomically admit one observed claim and optional revision relation."""

        if evidence.event_id != event.id:
            raise ValueError("evidence must reference the bundled event")
        if evidence.id not in claim.evidence_refs:
            raise ValueError("claim must reference the bundled evidence")
        if memory.target_type != "Claim" or memory.target_id != claim.id:
            raise ValueError("memory entry must target the bundled claim")

        current = self.current_claim(claim.subject, claim.predicate)
        if current is None and relation is not None:
            raise ValueError("initial claim cannot revise a missing current claim")
        if current is not None:
            if relation is None:
                raise ValueError("a claim over existing current state requires an explicit relation")
            if relation.source_claim_id != claim.id or relation.target_claim_id != current.id:
                raise ValueError("revision relation must point from new claim to current claim")

        with self.db:
            self.db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                (
                    str(event.id),
                    event.kind,
                    self._iso(event.occurred_at),
                    self._iso(event.recorded_at),
                    json.dumps(dict(event.payload), sort_keys=True),
                ),
            )
            self._log("Event", event.id, event.recorded_at)

            self.db.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?)",
                (str(evidence.id), str(evidence.event_id), evidence.source_ref, self._iso(evidence.captured_at), evidence.digest),
            )
            self._log("Evidence", evidence.id, evidence.captured_at)

            self.db.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(claim.id),
                    claim.subject,
                    claim.predicate,
                    json.dumps(claim.value, sort_keys=True),
                    self._iso(claim.recorded_at),
                    json.dumps([str(ref) for ref in claim.evidence_refs]),
                    self._iso(claim.valid_from),
                    self._iso(claim.valid_to),
                    str(claim.derivation_ref) if claim.derivation_ref else None,
                ),
            )
            self._log("Claim", claim.id, claim.recorded_at)

            move_head = current is None
            if relation is not None:
                self.db.execute(
                    "INSERT INTO claim_relations VALUES (?, ?, ?, ?, ?)",
                    (
                        str(relation.id),
                        str(relation.source_claim_id),
                        str(relation.target_claim_id),
                        relation.kind.value,
                        self._iso(relation.recorded_at),
                    ),
                )
                self._log("ClaimRelation", relation.id, relation.recorded_at)
                move_head = relation.kind in {ClaimRelationKind.CORRECTS, ClaimRelationKind.SUPERSEDES}

            if move_head:
                self.db.execute(
                    """
                    INSERT INTO claim_heads(subject, predicate, claim_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(subject, predicate) DO UPDATE SET claim_id = excluded.claim_id
                    """,
                    (claim.subject, claim.predicate, str(claim.id)),
                )

            self.db.execute(
                "INSERT INTO memory_entries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(memory.id),
                    memory.target_type,
                    str(memory.target_id),
                    memory.kind.value,
                    self._iso(memory.created_at),
                    memory.lifecycle.value,
                ),
            )
            self._log("MemoryEntry", memory.id, memory.created_at)

    def current_claim(self, subject: str, predicate: str) -> Claim | None:
        row = self.db.execute(
            """
            SELECT c.* FROM claim_heads h
            JOIN claims c ON c.id = h.claim_id
            WHERE h.subject = ? AND h.predicate = ?
            """,
            (subject, predicate),
        ).fetchone()
        return self._claim_from_row(row) if row else None

    def claim_history(self, subject: str, predicate: str) -> tuple[Claim, ...]:
        rows = self.db.execute(
            "SELECT * FROM claims WHERE subject = ? AND predicate = ? ORDER BY recorded_at, rowid",
            (subject, predicate),
        ).fetchall()
        return tuple(self._claim_from_row(row) for row in rows)

    def relations_for(self, claim_id: UUID) -> tuple[ClaimRelation, ...]:
        rows = self.db.execute(
            "SELECT * FROM claim_relations WHERE source_claim_id = ? OR target_claim_id = ? ORDER BY recorded_at, rowid",
            (str(claim_id), str(claim_id)),
        ).fetchall()
        return tuple(
            ClaimRelation(
                id=UUID(row["id"]),
                source_claim_id=UUID(row["source_claim_id"]),
                target_claim_id=UUID(row["target_claim_id"]),
                kind=ClaimRelationKind(row["kind"]),
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
            )
            for row in rows
        )

    def evidence(self, evidence_id: UUID) -> Evidence | None:
        row = self.db.execute("SELECT * FROM evidence WHERE id = ?", (str(evidence_id),)).fetchone()
        if not row:
            return None
        return Evidence(
            id=UUID(row["id"]),
            event_id=UUID(row["event_id"]),
            source_ref=row["source_ref"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            digest=row["digest"],
        )

    def is_active_memory_target(self, target_type: str, target_id: UUID) -> bool:
        row = self.db.execute(
            """
            SELECT 1 FROM memory_entries
            WHERE target_type = ? AND target_id = ? AND lifecycle = ?
            LIMIT 1
            """,
            (target_type, str(target_id), MemoryLifecycle.ACTIVE.value),
        ).fetchone()
        return row is not None

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> Claim:
        return Claim(
            id=UUID(row["id"]),
            subject=row["subject"],
            predicate=row["predicate"],
            value=json.loads(row["value_json"]),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            evidence_refs=tuple(UUID(value) for value in json.loads(row["evidence_refs_json"])),
            valid_from=SQLiteCanonicalStore._dt(row["valid_from"]),
            valid_to=SQLiteCanonicalStore._dt(row["valid_to"]),
            derivation_ref=UUID(row["derivation_ref"]) if row["derivation_ref"] else None,
        )
