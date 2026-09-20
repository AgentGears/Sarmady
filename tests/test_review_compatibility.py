from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sarmady.context import (
    ContextRequest,
    CoverageStatus,
    ExactCoverageRequirement,
)
from sarmady.runtime import ModelInput


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_context_request_accepts_current_v5_positional_exact_requirements() -> None:
    requirement = ExactCoverageRequirement(
        "machine-profile",
        "machine:primary",
        "profile",
    )

    request = ContextRequest(
        uuid4(),
        "profile",
        512,
        None,
        None,
        None,
        (),
        (requirement,),
    )

    assert request.exact_requirements == (requirement,)
    assert request.known_at is None
    assert request.valid_at is None


def test_context_request_accepts_pre_v5_positional_temporal_layout() -> None:
    valid_at = T0 + timedelta(hours=1)

    request = ContextRequest(
        uuid4(),
        "historical",
        512,
        None,
        None,
        None,
        ("legacy-label",),
        T0,
        valid_at,
    )

    assert request.coverage_requirements == ("legacy-label",)
    assert request.exact_requirements == ()
    assert request.known_at == T0
    assert request.valid_at == valid_at


def test_context_request_accepts_mixed_pre_v5_temporal_arguments() -> None:
    valid_at = T0 + timedelta(hours=2)

    request = ContextRequest(
        uuid4(),
        "mixed historical",
        512,
        None,
        None,
        None,
        ("legacy-label",),
        T0,
        valid_at=valid_at,
    )

    assert request.exact_requirements == ()
    assert request.known_at == T0
    assert request.valid_at == valid_at


def test_model_input_legacy_constructor_gets_conservative_coverage_default() -> None:
    model_input = ModelInput(
        uuid4(),
        uuid4(),
        uuid4(),
        "sqlite:0",
        "answer",
        None,
        None,
        None,
        (),
    )

    assert model_input.coverage_status is CoverageStatus.INSUFFICIENT
    assert model_input.unresolved_gaps == ()
    assert model_input.omitted_refs == ()
