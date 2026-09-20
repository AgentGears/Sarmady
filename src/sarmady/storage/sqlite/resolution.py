from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import UUID

from sarmady.epistemic import (
    Claim,
    ClaimRelation,
    ClaimRelationKind,
    ResolvedState,
    ResolutionStatus,
)

from ._codec import claim_from_row, relation_from_row
from .errors import CanonicalIntegrityError


HEAD_MOVING_RELATIONS = {
    ClaimRelationKind.CORRECTS,
    ClaimRelationKind.SUPERSEDES,
}


def normalized(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("temporal query values must be timezone-aware")
    return value.astimezone(UTC)


def load_claim(db: sqlite3.Connection, claim_id: UUID) -> Claim | None:
    row = db.execute(
        "SELECT * FROM claims WHERE id = ?", (str(claim_id),)
    ).fetchone()
    return claim_from_row(row) if row else None


def head_for_key(
    db: sqlite3.Connection,
    subject: str,
    predicate: str,
    *,
    known_at: datetime | None = None,
) -> tuple[UUID | None, dict[UUID, UUID]]:
    """Reconstruct the canonical head without consulting `claim_heads`."""

    known_norm = normalized(known_at) if known_at is not None else None

    claim_rows = db.execute(
        """
        SELECT c.*, l.seq AS semantic_seq
        FROM claims c
        JOIN semantic_log l ON l.kind = 'Claim' AND l.ref_id = c.id
        WHERE c.subject = ? AND c.predicate = ?
        ORDER BY l.seq
        """,
        (subject, predicate),
    ).fetchall()

    claims: dict[UUID, tuple[Claim, int]] = {}
    for row in claim_rows:
        claim = claim_from_row(row)
        if known_norm is not None and normalized(claim.recorded_at) > known_norm:
            continue
        claims[claim.id] = (claim, int(row["semantic_seq"]))

    relation_rows = db.execute(
        """
        SELECT r.*, l.seq AS semantic_seq
        FROM claim_relations r
        JOIN semantic_log l ON l.kind = 'ClaimRelation' AND l.ref_id = r.id
        ORDER BY l.seq
        """
    ).fetchall()

    relations: dict[UUID, tuple[ClaimRelation, int]] = {}
    for row in relation_rows:
        relation = relation_from_row(row)
        if (
            relation.source_claim_id not in claims
            or relation.target_claim_id not in claims
        ):
            continue
        if (
            known_norm is not None
            and normalized(relation.recorded_at) > known_norm
        ):
            continue
        relations[relation.id] = (relation, int(row["semantic_seq"]))

    timeline: list[tuple[int, str, UUID]] = []
    timeline.extend((seq, "Claim", cid) for cid, (_, seq) in claims.items())
    timeline.extend(
        (seq, "ClaimRelation", rid) for rid, (_, seq) in relations.items()
    )
    timeline.sort(key=lambda item: item[0])

    head: UUID | None = None
    revision_parent: dict[UUID, UUID] = {}
    for _, kind, ref_id in timeline:
        if kind == "Claim":
            if head is None:
                head = ref_id
            continue

        relation = relations[ref_id][0]
        if relation.kind not in HEAD_MOVING_RELATIONS:
            continue
        if head != relation.target_claim_id:
            raise CanonicalIntegrityError(
                "head-moving relation does not target the operative canonical head"
            )
        revision_parent[relation.source_claim_id] = relation.target_claim_id
        head = relation.source_claim_id

    return head, revision_parent


def claim_valid_at(claim: Claim, valid_at: datetime) -> bool:
    point = normalized(valid_at)
    if claim.valid_from is not None and point < normalized(claim.valid_from):
        return False
    if claim.valid_to is not None and point >= normalized(claim.valid_to):
        return False
    return True


def resolve_state(
    db: sqlite3.Connection,
    subject: str,
    predicate: str,
    *,
    frontier: int,
    known_at: datetime | None = None,
    valid_at: datetime | None = None,
) -> ResolvedState:
    if known_at is not None:
        normalized(known_at)
    if valid_at is not None:
        normalized(valid_at)

    head_id, revision_parent = head_for_key(
        db, subject, predicate, known_at=known_at
    )
    if head_id is None:
        return _missing(subject, predicate, frontier)

    operative_id = head_id
    if valid_at is not None:
        cursor: UUID | None = head_id
        operative_id = None
        seen: set[UUID] = set()
        while cursor is not None:
            if cursor in seen:
                raise CanonicalIntegrityError("revision lineage contains a cycle")
            seen.add(cursor)
            candidate = load_claim(db, cursor)
            if candidate is None:
                raise CanonicalIntegrityError(
                    f"revision lineage references missing claim {cursor}"
                )
            if claim_valid_at(candidate, valid_at):
                operative_id = cursor
                break
            cursor = revision_parent.get(cursor)

    if operative_id is None:
        return _missing(subject, predicate, frontier)

    operative = load_claim(db, operative_id)
    if operative is None:
        raise CanonicalIntegrityError(
            f"operative canonical claim {operative_id} is missing"
        )

    known_norm = normalized(known_at) if known_at is not None else None
    competing: list[UUID] = []
    conflicts: list[UUID] = []

    relation_rows = db.execute(
        """
        SELECT r.* FROM claim_relations r
        JOIN semantic_log l ON l.kind = 'ClaimRelation' AND l.ref_id = r.id
        WHERE r.kind = ?
          AND (r.source_claim_id = ? OR r.target_claim_id = ?)
        ORDER BY l.seq
        """,
        (
            ClaimRelationKind.CONTRADICTS.value,
            str(operative_id),
            str(operative_id),
        ),
    ).fetchall()

    for row in relation_rows:
        relation = relation_from_row(row)
        if (
            known_norm is not None
            and normalized(relation.recorded_at) > known_norm
        ):
            continue

        other_id = (
            relation.target_claim_id
            if relation.source_claim_id == operative_id
            else relation.source_claim_id
        )
        other = load_claim(db, other_id)
        if other is None:
            raise CanonicalIntegrityError(
                f"contradiction references missing claim {other_id}"
            )
        if known_norm is not None and normalized(other.recorded_at) > known_norm:
            continue
        if valid_at is not None and not claim_valid_at(other, valid_at):
            continue

        competing.append(other_id)
        conflicts.append(relation.id)

    status = (
        ResolutionStatus.CONTESTED if competing else ResolutionStatus.RESOLVED
    )
    return ResolvedState(
        subject=subject,
        predicate=predicate,
        status=status,
        operative_claim_id=operative.id,
        competing_claim_ids=tuple(competing),
        conflict_relation_ids=tuple(conflicts),
        value=operative.value,
        snapshot_id=f"sqlite:{frontier}",
        computed_at=datetime.now(UTC),
    )


def rebuild_claim_heads(db: sqlite3.Connection) -> int:
    keys = db.execute(
        "SELECT DISTINCT subject, predicate FROM claims ORDER BY subject, predicate"
    ).fetchall()
    desired: list[tuple[str, str, UUID]] = []

    for row in keys:
        head_id, _ = head_for_key(db, row["subject"], row["predicate"])
        if head_id is not None:
            desired.append((row["subject"], row["predicate"], head_id))

    db.execute("DELETE FROM claim_heads")
    db.executemany(
        "INSERT INTO claim_heads(subject, predicate, claim_id) VALUES (?, ?, ?)",
        [(subject, predicate, str(claim_id)) for subject, predicate, claim_id in desired],
    )
    return len(desired)


def _missing(subject: str, predicate: str, frontier: int) -> ResolvedState:
    return ResolvedState(
        subject=subject,
        predicate=predicate,
        status=ResolutionStatus.MISSING,
        operative_claim_id=None,
        competing_claim_ids=(),
        conflict_relation_ids=(),
        value=None,
        snapshot_id=f"sqlite:{frontier}",
        computed_at=datetime.now(UTC),
    )
