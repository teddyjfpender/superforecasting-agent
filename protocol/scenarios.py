"""Bounded scenario evaluation contracts; results are not active forecasts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from protocol.interviews import (
    InterviewAssumption,
    InterviewGenerationOptions,
    InterviewModel,
    InterviewScenario,
)


class ScenarioEvaluationOptions(InterviewModel):
    model: InterviewGenerationOptions = Field(
        default_factory=InterviewGenerationOptions
    )
    scenario_ids: list[str] = Field(min_length=1, max_length=8)
    repetitions: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def unique_scenarios(self) -> ScenarioEvaluationOptions:
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario IDs must be unique")
        return self


class ScenarioEstimate(InterviewModel):
    outcome_type: Literal["binary", "categorical", "numeric", "distribution"]
    probability: float | None = Field(default=None, ge=0, le=1)
    categories: dict[str, float] = Field(default_factory=dict, max_length=100)
    # Quantiles are elicited directly; never infer a Gaussian or tail probability.
    q10: float | None = None
    q50: float | None = None
    q90: float | None = None
    units: str | None = None
    rationale: str = Field(min_length=1, max_length=10000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=200)
    reference_class_refs: list[str] = Field(default_factory=list, max_length=100)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def coherent_estimate(self) -> ScenarioEstimate:
        quantiles = (self.q10, self.q50, self.q90)
        if self.outcome_type == "binary":
            if (
                self.probability is None
                or self.categories
                or any(q is not None for q in quantiles)
                or self.units
            ):
                raise ValueError("binary estimates require only a probability")
        elif self.outcome_type == "categorical":
            if (
                self.probability is not None
                or any(q is not None for q in quantiles)
                or self.units
            ):
                raise ValueError(
                    "categorical estimates require only category probabilities"
                )
            if (
                not self.categories
                or any(not 0 <= p <= 1 for p in self.categories.values())
                or abs(sum(self.categories.values()) - 1) > 1e-9
            ):
                raise ValueError("category probabilities must sum to one")
        elif (
            self.probability is not None
            or self.categories
            or not self.units
            or self.q10 is None
            or self.q50 is None
            or self.q90 is None
        ):
            raise ValueError("continuous estimates require units and three quantiles")
        elif not self.q10 <= self.q50 <= self.q90:
            raise ValueError("quantiles must be ordered")
        return self


class ScenarioRouteReceipt(InterviewModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str


class ScenarioCallResult(InterviewModel):
    variant_id: str
    kind: Literal["baseline", "conditional", "ablation"]
    repetition: int
    prompt_digest: str
    estimate: ScenarioEstimate
    request_receipt: ScenarioRouteReceipt
    response_model: str
    output_tokens: int | None
    created_at: str


class ScenarioDimension(InterviewModel):
    mean: float
    paired_delta: float
    model_dispersion: float | None


class ScenarioComparison(InterviewModel):
    variant_id: str
    kind: Literal["baseline", "conditional", "ablation"]
    repetitions: int
    dimensions: dict[str, ScenarioDimension]


class ScenarioReport(InterviewModel):
    interview_id: str
    revision: int
    input_digest: str
    matched: Literal[True]
    scenarios: list[InterviewScenario]
    assumptions: list[InterviewAssumption]
    comparisons: list[ScenarioComparison]
    results: list[ScenarioCallResult]
    limitation: str
