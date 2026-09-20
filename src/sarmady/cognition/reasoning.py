from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


class ReasoningMode(str, Enum):
    DIRECT = "DIRECT"
    COMPACT = "COMPACT"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class ReasoningRequirement:
    key: str
    description: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("reasoning requirement key is required")
        if not self.description.strip():
            raise ValueError("reasoning requirement description is required")


@dataclass(frozen=True, slots=True)
class ReasoningPolicy:
    """Versioned semantic control contract for a cognitive invocation.

    A policy describes reasoning obligations and stages. It is not a provider
    prompt and carries no provider/model configuration.
    """

    id: str
    version: str
    mode: ReasoningMode
    stages: tuple[str, ...]
    requirements: tuple[ReasoningRequirement, ...]
    source_ref: str
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("reasoning policy id is required")
        if not self.version.strip():
            raise ValueError("reasoning policy version is required")
        if not self.source_ref.strip():
            raise ValueError("reasoning policy source_ref is required")
        if any(not stage.strip() for stage in self.stages):
            raise ValueError("reasoning policy stages cannot be empty")
        stage_keys = [stage.strip().upper() for stage in self.stages]
        if len(stage_keys) != len(set(stage_keys)):
            raise ValueError("reasoning policy stages must be unique")
        requirement_keys = [item.key for item in self.requirements]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("reasoning requirement keys must be unique")
        if self.source_sha256 is not None:
            if self.source_sha256 != self.source_sha256.lower():
                raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
            digest = self.source_sha256
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")

    @property
    def fingerprint(self) -> str:
        payload = {
            "id": self.id,
            "version": self.version,
            "mode": self.mode.value,
            "stages": list(self.stages),
            "requirements": [
                {"key": item.key, "description": item.description}
                for item in self.requirements
            ],
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


_REASONING_ENGINE_COMMIT = "71c69fcf0b5fc3d7b89497f98ddc1755ead5f6c2"
_REASONING_ENGINE_PATH = "benchmark/pilot.py"
_SOURCE_PREFIX = (
    f"ElephantRock/Reasoning-Engine@{_REASONING_ENGINE_COMMIT}:{_REASONING_ENGINE_PATH}"
)


DIRECT_V1 = ReasoningPolicy(
    id="sarmady:reasoning:direct:v1",
    version="1",
    mode=ReasoningMode.DIRECT,
    stages=(),
    requirements=(
        ReasoningRequirement(
            "direct_when_established",
            "Answer directly when the task is trivial, deterministic, or established and deeper causal investigation adds no decision value.",
        ),
    ),
    source_ref=f"{_SOURCE_PREFIX}#ROUTER",
    source_sha256="66aaf0b5825eef6df78f9ab6d0d3d59ba0ee32f91b71a11503d6cc1c6542cfdc",
)


_COMMON_REQUIREMENTS = (
    ReasoningRequirement(
        "define_problem",
        "Define the actual problem before proposing a solution.",
    ),
    ReasoningRequirement(
        "separate_epistemic_roles",
        "Keep observations, interpretations, assumptions, hypotheses, predictions, evidence, conclusions, and recommendations distinct where material.",
    ),
    ReasoningRequirement(
        "first_principles_as_invariants",
        "Treat first principles as necessities or invariants rather than conventions, precedents, analogies, or current implementations.",
    ),
    ReasoningRequirement(
        "mechanism_not_correlation",
        "Do not treat correlation or plausibility as an established causal mechanism.",
    ),
    ReasoningRequirement(
        "expose_critical_assumptions",
        "Surface assumptions whose failure could change the decision.",
    ),
    ReasoningRequirement(
        "preserve_uncertainty",
        "Preserve material uncertainty and calibrate confidence to available evidence.",
    ),
    ReasoningRequirement(
        "seek_disconfirming_evidence",
        "Prefer evidence and tests capable of weakening or falsifying the favored mechanism.",
    ),
    ReasoningRequirement(
        "revise_on_contradiction",
        "Revise the working model when evidence contradicts it rather than preserving the prior explanation by default.",
    ),
    ReasoningRequirement(
        "engineer_under_constraints",
        "Choose interventions from the best-supported mechanism while accounting for constraints, risk, reversibility, side effects, and second-order effects.",
    ),
    ReasoningRequirement(
        "stop_on_low_information_value",
        "Stop further investigation when additional information is unlikely to change the justified action.",
    ),
)


COMPACT_V1 = ReasoningPolicy(
    id="sarmady:reasoning:compact:v1",
    version="1",
    mode=ReasoningMode.COMPACT,
    stages=("PROBLEM", "FIRST_PRINCIPLE", "MECHANISM", "EVIDENCE", "SOLUTION"),
    requirements=_COMMON_REQUIREMENTS,
    source_ref=f"{_SOURCE_PREFIX}#COMPACT",
    source_sha256="8e9d66f50c4afaa10f0df58c5c2b11fd6c30d8600d7246c2a0aea63c71a83bd4",
)


FULL_V1 = ReasoningPolicy(
    id="sarmady:reasoning:full:v1",
    version="1",
    mode=ReasoningMode.FULL,
    stages=(
        "OBSERVE",
        "DIAGNOSE",
        "DERIVE",
        "HYPOTHESIZE",
        "PREDICT",
        "TEST",
        "REVISE",
        "ENGINEER",
    ),
    requirements=_COMMON_REQUIREMENTS
    + (
        ReasoningRequirement(
            "generate_competing_hypotheses",
            "Generate multiple plausible explanations when ambiguity is material.",
        ),
        ReasoningRequirement(
            "distinguish_causal_depth",
            "Distinguish symptoms, proximate causes, and root causes when causal diagnosis matters.",
        ),
        ReasoningRequirement(
            "derive_predictions",
            "Express important mechanisms in falsifiable form and derive observable predictions.",
        ),
        ReasoningRequirement(
            "prefer_discriminating_tests",
            "Prefer tests that discriminate among competing explanations rather than merely confirm one narrative.",
        ),
        ReasoningRequirement(
            "compare_interventions",
            "Compare candidate interventions on effectiveness, robustness, cost, risk, reversibility, feasibility, constraints, feedback loops, and second-order effects when material.",
        ),
        ReasoningRequirement(
            "close_feedback_loop",
            "After intervention, predict expected outcomes and use observed outcomes to update the model.",
        ),
    ),
    source_ref=f"{_SOURCE_PREFIX}#FULL",
    source_sha256="e5e5556dc09ae25b7b84aae05a3a4c921c24751645bd9e965cc506fc9e42df2d",
)


BUILTIN_REASONING_POLICIES = (DIRECT_V1, COMPACT_V1, FULL_V1)
BUILTIN_REASONING_POLICY_BY_ID = {policy.id: policy for policy in BUILTIN_REASONING_POLICIES}
