from __future__ import annotations

from uuid import uuid4

import pytest

from sarmady.context import ContextProjection, ContextRequest, CoverageStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore


def test_legacy_nonpositive_latency_cannot_propagate_to_fresh_store(tmp_path) -> None:
    source_path = tmp_path / "legacy-latency-source.db"
    destination_path = tmp_path / "fresh-latency-destination.db"
    request_id = uuid4()

    with SQLiteCanonicalStore(source_path) as source:
        request = ContextRequest(
            request_id,
            "legacy latency",
            512,
            latency_budget_ms=1,
        )
        projection = ContextProjection(
            id=uuid4(),
            request_id=request_id,
            snapshot_id="sqlite:0",
            canonical_frontier="0",
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:legacy-latency-source",
            compiler_version="test",
        )
        source.register_context_projection(projection, request=request)
        source.db.execute(
            "UPDATE context_requests SET latency_budget_ms = -5 WHERE id = ?",
            (str(request_id),),
        )
        legacy_request = source.context_request(request_id)
        assert legacy_request is not None
        assert legacy_request.latency_budget_ms == -5

    with SQLiteCanonicalStore(destination_path) as destination:
        copied_projection = ContextProjection(
            id=uuid4(),
            request_id=request_id,
            snapshot_id="sqlite:0",
            canonical_frontier="0",
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:legacy-latency-copy",
            compiler_version="test",
        )

        with pytest.raises(ValueError, match="latency_budget_ms must be positive"):
            destination.register_context_projection(
                copied_projection,
                request=legacy_request,
            )

        assert destination.context_request(request_id) is None
        assert destination.context_projection(copied_projection.id) is None
