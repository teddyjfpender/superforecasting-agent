"""Forecast questionnaire operations; nested contracts also generate the TUI types."""

from typing import Any, Literal

from pydantic import Field

from protocol.interviews import (
    ForecastArticleClaim,
    ForecastMarketSeed,
    InterviewDraft,
    InterviewGenerationOptions,
    InterviewScenario,
)
from protocol.rpc.jobs import JobsStatusResponse
from protocol.scenarios import ScenarioEvaluationOptions, ScenarioReport
from protocol.types import WireModel


class InterviewBeginRequest(WireModel):
    interview_id: str
    title: str = "New forecast"
    seed: ForecastMarketSeed | None = None
    question_id: str | None = None


class InterviewReadRequest(WireModel):
    interview_id: str
    revision: int | None = None


class InterviewListRequest(WireModel):
    question_id: str | None = None


class InterviewRecord(WireModel):
    interview_id: str
    revision: int
    request_id: str
    actor: Literal["user", "agent"]
    document: InterviewDraft
    digest: str
    created_at: str


class InterviewListResponse(WireModel):
    interviews: list[InterviewRecord]


class InterviewAnswerRequest(WireModel):
    interview_id: str
    expected_revision: int
    request_id: str
    question_id: str
    status: Literal["answered", "unknown", "skipped"]
    value: str | float | list[str] | None = None
    note: str = ""
    custom_text: str | None = None


class InterviewPreviewRequest(WireModel):
    interview_id: str
    revision: int


class InterviewPreviewResponse(WireModel):
    spec: dict[str, Any]
    issues: list[dict[str, Any]]
    unanswered: list[str]
    committable: bool


class InterviewCommitResponse(WireModel):
    question_id: str
    revision: int


class ForecastArticleAttachRequest(WireModel):
    question_id: str
    article: ForecastArticleClaim
    prepare_update: bool = False


class ForecastArticleAttachResponse(WireModel):
    question_id: str
    evidence_id: str
    interview_id: str | None
    already_attached: bool


class ForecastQuestionChoice(WireModel):
    id: str
    title: str
    domain: str | None


class ForecastQuestionChoicesResponse(WireModel):
    questions: list[ForecastQuestionChoice]


class InterviewGenerateRequest(WireModel):
    request_id: str = Field(min_length=1, max_length=200)
    interview_id: str
    revision: int
    options: InterviewGenerationOptions = Field(
        default_factory=InterviewGenerationOptions
    )


class InterviewGenerateResponse(WireModel):
    job_id: str


class InterviewTargetRequest(WireModel):
    interview_id: str


class InterviewScenarioSaveRequest(WireModel):
    interview_id: str
    expected_revision: int
    request_id: str
    scenario: InterviewScenario


class InterviewScenarioDeleteRequest(WireModel):
    interview_id: str
    expected_revision: int
    request_id: str
    scenario_id: str


class InterviewGenerationStatusResponse(JobsStatusResponse):
    TS_NAME = "InterviewGenerationStatusResponse"

    request_id: str | None = None


class InterviewEvaluateRequest(WireModel):
    request_id: str = Field(min_length=1, max_length=200)
    interview_id: str
    revision: int
    options: ScenarioEvaluationOptions


class InterviewEvaluationStatusResponse(InterviewGenerationStatusResponse):
    TS_NAME = "InterviewEvaluationStatusResponse"

    report: ScenarioReport | None = None
    stale: bool = False
