"""Validated interview revisions, independent of transports and model providers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InterviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Choice(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=500)


class InterviewQuestion(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    section: Literal[
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
    prompt: str = Field(min_length=1, max_length=3000)
    rationale: str = Field(min_length=1, max_length=2000)
    kind: Literal["text", "single", "multiple", "probability", "number"] = "text"
    choices: list[Choice] = Field(default_factory=list, max_length=20)
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
    actor: Literal["user", "agent"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class Assumption(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=3000)
    probability: float | None = Field(default=None, ge=0, le=1)
    uncertainty: Literal[
        "epistemic", "aleatoric", "measurement", "mixed", "unclassified"
    ] = "unclassified"
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=10000)


class Scenario(InterviewModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    kind: Literal["conditional", "ablation"]
    # False is an explicit condition, never an unchecked/omitted assumption.
    conditions: dict[str, bool] = Field(default_factory=dict, max_length=100)
    excluded_assumption_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def distinct_semantics(self) -> Scenario:
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


class InterviewDraft(InterviewModel):
    schema_version: Literal[1] = 1
    mode: Literal["create", "update"]
    question_id: str | None = None
    baseline_forecast_id: str | None = None
    title: str = Field(min_length=1, max_length=1000)
    questions: list[InterviewQuestion] = Field(default_factory=list, max_length=100)
    answers: list[InterviewAnswer] = Field(default_factory=list, max_length=100)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=100)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=100)
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
                if value is not None:
                    raise ValueError("unknown/skipped answers cannot carry a value")
                continue
            if question.kind in {"probability", "number"}:
                if not isinstance(value, float):
                    raise ValueError("numeric answers require a number")
                if question.kind == "probability" and not 0 <= value <= 1:
                    raise ValueError("probabilities must be in [0, 1]")
            elif question.kind == "multiple":
                if (
                    not isinstance(value, list)
                    or not value
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
