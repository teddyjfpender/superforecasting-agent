"""Validated interview revisions, independent of transports and model providers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InterviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def _source_url(value: str | None) -> None:
    if value is None:
        return
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("source URL must be an HTTP(S) URL without credentials")


def _source_time(value: str | None) -> None:
    if value is not None:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("source timestamps require a timezone")


class ForecastMarketSeed(InterviewModel):
    kind: Literal["prediction_market", "series"]
    provider: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=1000)
    event_id: str | None = Field(default=None, max_length=500)
    outcome_id: str | None = Field(default=None, max_length=500)
    outcome_label: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=4000)
    captured_at: str
    retrieved_at: str | None = None
    observed_at: str | None = None
    published_at: str | None = None
    close_time: str | None = None
    units: str | None = Field(default=None, max_length=200)
    revision_policy: str | None = Field(default=None, max_length=1000)
    period_start: str | None = None
    period_end: str | None = None
    market_price: float | None = Field(default=None, ge=0, le=1)
    observed_value: float | None = None

    @model_validator(mode="after")
    def source_identity(self) -> ForecastMarketSeed:
        _source_url(self.source_url)
        for value in (
            self.captured_at,
            self.retrieved_at,
            self.observed_at,
            self.published_at,
            self.close_time,
        ):
            _source_time(value)
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("observation periods require both start and end")
        if self.period_start is not None and self.period_end is not None:
            if date.fromisoformat(self.period_start) > date.fromisoformat(
                self.period_end
            ):
                raise ValueError("observation period end precedes its start")
        if self.kind == "prediction_market" and self.symbol != self.outcome_id:
            raise ValueError(
                "selected prediction-market symbol must identify its exact outcome"
            )
        if self.kind == "prediction_market" and not (self.event_id and self.outcome_id):
            raise ValueError(
                "prediction-market seeds require exact event and outcome identifiers"
            )
        if self.kind == "series" and (
            self.event_id or self.outcome_id or self.market_price is not None
        ):
            raise ValueError(
                "ordinary series cannot claim prediction-market identities or prices"
            )
        return self


class ForecastArticleClaim(InterviewModel):
    title: str = Field(min_length=1, max_length=2000)
    url: str = Field(min_length=1, max_length=4000)
    publisher: str = Field(default="", max_length=500)
    feed_url: str = Field(max_length=4000)
    published_at: str | None = None
    content: str = Field(default="", max_length=60000)
    extraction: Literal["article", "feed"]

    @model_validator(mode="after")
    def source_identity(self) -> ForecastArticleClaim:
        _source_url(self.url)
        _source_url(self.feed_url)
        _source_time(self.published_at)
        return self


class InterviewChoice(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=500)


InterviewSection = Literal[
    "define",
    "resolve",
    "outside_view",
    "drivers",
    "beliefs",
    "uncertainty",
    "challenge",
    "scenarios",
    "update_plan",
    "review",
]


class InterviewQuestion(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    section: InterviewSection
    prompt: str = Field(min_length=1, max_length=3000)
    rationale: str = Field(min_length=1, max_length=2000)
    kind: Literal["text", "single", "multiple", "probability", "number"] = "text"
    choices: list[InterviewChoice] = Field(default_factory=list, max_length=20)
    allow_custom: bool = True
    required: bool = False
    assumption_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def coherent_choices(self) -> InterviewQuestion:
        ids = [choice.id for choice in self.choices]
        if len(set(ids)) != len(ids):
            raise ValueError("choice identifiers must be unique")
        if self.kind in {"single", "multiple"} and not ids:
            raise ValueError("choice questions require choices")
        if self.kind not in {"single", "multiple"} and ids:
            raise ValueError("only choice questions may define choices")
        return self


class InterviewAnswer(InterviewModel):
    question_id: str
    status: Literal["answered", "unknown", "skipped"]
    value: str | float | list[str] | None = None
    note: str = Field(default="", max_length=10000)
    custom_text: str | None = Field(default=None, min_length=1, max_length=10000)
    actor: Literal["user", "agent"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class InterviewAssumption(InterviewModel):
    actor: Literal["user", "agent"] = "user"
    id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=3000)
    probability: float | None = Field(default=None, ge=0, le=1)
    uncertainty: Literal[
        "epistemic", "aleatoric", "measurement", "mixed", "unclassified"
    ] = "unclassified"
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=10000)


class InterviewScenario(InterviewModel):
    actor: Literal["user", "agent"] = "user"
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    kind: Literal["conditional", "ablation"]
    # False is an explicit condition, never an unchecked/omitted assumption.
    conditions: dict[str, bool] = Field(default_factory=dict, max_length=100)
    excluded_assumption_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def distinct_semantics(self) -> InterviewScenario:
        if self.kind == "conditional":
            if not self.conditions or self.excluded_assumption_ids:
                raise ValueError(
                    "conditional scenarios require conditions and cannot exclude factors"
                )
        elif self.conditions or not self.excluded_assumption_ids:
            raise ValueError(
                "ablations require exclusions and cannot assert conditions"
            )
        if len(set(self.excluded_assumption_ids)) != len(self.excluded_assumption_ids):
            raise ValueError("duplicate excluded assumptions")
        return self


class InterviewGenerationOptions(InterviewModel):
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    max_questions: int = Field(default=8, ge=1, le=16)
    max_tokens: int = Field(default=4000, ge=512, le=12000)
    timeout_seconds: float = Field(default=90.0, ge=5, le=180)


class InterviewFollowups(InterviewModel):
    questions: list[InterviewQuestion] = Field(max_length=16)
    assumptions: list[InterviewAssumption] = Field(default_factory=list, max_length=16)
    summary: str = Field(min_length=1, max_length=4000)


class InterviewGenerationRecord(InterviewModel):
    job_id: str
    input_revision: int
    input_digest: str
    prompt_digest: str
    response_model: str
    requested_provider: str | None
    max_tokens: int
    output_tokens: int | None
    created_at: str
    summary: str


class InterviewDraft(InterviewModel):
    schema_version: Literal[1] = 1
    seed: ForecastMarketSeed | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=200)
    generations: list[InterviewGenerationRecord] = Field(
        default_factory=list, max_length=100
    )
    mode: Literal["create", "update"]
    question_id: str | None = None
    baseline_forecast_id: str | None = None
    context_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=1000)
    questions: list[InterviewQuestion] = Field(default_factory=list, max_length=100)
    answers: list[InterviewAnswer] = Field(default_factory=list, max_length=100)
    assumptions: list[InterviewAssumption] = Field(default_factory=list, max_length=100)
    scenarios: list[InterviewScenario] = Field(default_factory=list, max_length=100)
    status: Literal["draft", "needs_user", "needs_research", "ready", "cancelled"] = (
        "draft"
    )

    @model_validator(mode="after")
    def coherent_revision(self) -> InterviewDraft:
        if (self.mode == "update") != bool(self.question_id):
            raise ValueError(
                "only update interviews must identify an existing question"
            )
        if self.mode == "create" and self.baseline_forecast_id:
            raise ValueError("new questions cannot have a baseline forecast")
        for values in (self.questions, self.assumptions, self.scenarios):
            ids = [value.id for value in values]
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate identifiers")
        questions = {question.id: question for question in self.questions}
        assumption_ids = {assumption.id for assumption in self.assumptions}
        answered = set()
        for answer in self.answers:
            if answer.question_id not in questions or answer.question_id in answered:
                raise ValueError(
                    "answers require unique, existing question identifiers"
                )
            answered.add(answer.question_id)
            question = questions[answer.question_id]
            value = answer.value
            if answer.status != "answered":
                if value is not None or answer.custom_text is not None:
                    raise ValueError("unknown/skipped answers cannot carry a value")
                continue
            if answer.custom_text is not None:
                if (
                    not answer.custom_text.strip()
                    or not question.allow_custom
                    or question.kind not in {"single", "multiple"}
                ):
                    raise ValueError("custom text requires an enabled choice question")
                if question.kind == "single":
                    if value is not None:
                        raise ValueError(
                            "single choice accepts a selection or custom text, not both"
                        )
                    continue
            if question.kind in {"probability", "number"}:
                if not isinstance(value, float):
                    raise ValueError("numeric answers require a number")
                if question.kind == "probability" and not 0 <= value <= 1:
                    raise ValueError("probabilities must be in [0, 1]")
            elif question.kind == "multiple":
                if (
                    not isinstance(value, list)
                    or (not value and answer.custom_text is None)
                    or len(set(value)) != len(value)
                ):
                    raise ValueError(
                        "multiple choice answers require unique selections"
                    )
                if not set(value) <= {choice.id for choice in question.choices}:
                    raise ValueError("unknown choice identifier")
            else:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("text/choice answers require nonempty text")
                if question.kind == "single" and not question.allow_custom:
                    if value not in {choice.id for choice in question.choices}:
                        raise ValueError("unknown choice identifier")
        for question in self.questions:
            if not set(question.assumption_ids) <= assumption_ids:
                raise ValueError("question references an unknown assumption")
        for scenario in self.scenarios:
            if (
                not (set(scenario.conditions) | set(scenario.excluded_assumption_ids))
                <= assumption_ids
            ):
                raise ValueError("scenario references an unknown assumption")
        if self.status == "ready":
            completed = {a.question_id for a in self.answers if a.status == "answered"}
            if any(q.required and q.id not in completed for q in self.questions):
                raise ValueError("required questions remain unanswered")
        return self
