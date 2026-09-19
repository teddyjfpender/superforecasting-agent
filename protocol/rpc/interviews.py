"""Forecast questionnaire operations; nested contracts also generate the TUI types."""

from typing import Any, Literal

from pydantic import Field

from protocol.interviews import (
    ForecastArticleClaim,
    ForecastMarketSeed,
    InterviewAssumption,
    InterviewDraft,
    InterviewEditorBuffer,
    InterviewGenerationOptions,
    InterviewModel,
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


class InterviewLessonProvenance(WireModel):
    lesson_id: str
    revision: str
    content_digest: str
    included: bool
    reason: str
    guidance: str | None
    scope_type: str
    scope_ref: str | None
    applicability: dict[str, Any]
    support_score_count: int = Field(ge=0)
    distinct_outcome_count: int = Field(ge=0)
    independent_cluster_count: int | None = Field(default=None, ge=0)
    source_score_ids: list[str]
    source_postmortem_ids: list[str]


class InterviewLessonsResponse(WireModel):
    interview_id: str
    revision: int
    context_digest: str | None
    policy: str | None
    cutoff: str | None
    advisory_only: Literal[True] = True
    lessons: list[InterviewLessonProvenance]


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


class InterviewPromotionPreviewRequest(WireModel):
    job_id: str
    repetition: int = Field(default=0, ge=0, le=2)


class InterviewPromotionPreviewResponse(WireModel):
    job_id: str
    repetition: int
    question_id: str
    candidate: float | dict[str, float]
    would_commit: bool
    blockers: list[str]
    preview_digest: str
    promoted_forecast_id: str | None = None


class InterviewPromoteRequest(InterviewPromotionPreviewRequest):
    TS_NAME = "InterviewPromoteRequest"

    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class InterviewPromoteResponse(WireModel):
    question_id: str
    forecast_id: str


class InterviewAssumptionSaveRequest(WireModel):
    interview_id: str
    expected_revision: int
    request_id: str
    assumption: InterviewAssumption


class InterviewBufferSaveRequest(WireModel):
    model_config = InterviewModel.model_config

    interview_id: str = Field(min_length=1, max_length=200)
    question_id: str = Field(min_length=1, max_length=200)
    base_revision: int = Field(ge=1)
    expected_buffer_revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=200)
    # Null is an explicit discard, with its own revision and retry identity.
    buffer: InterviewEditorBuffer | None


class InterviewBufferReceipt(InterviewModel):
    interview_id: str
    question_id: str
    base_revision: int
    buffer_revision: int
    request_id: str
    saved_at: str
    discarded: bool


class InterviewBufferRecord(InterviewBufferReceipt):
    buffer: InterviewEditorBuffer | None
    stale: bool


class InterviewBuffersRequest(WireModel):
    model_config = InterviewModel.model_config

    interview_id: str = Field(min_length=1, max_length=200)


class InterviewBuffersResponse(InterviewModel):
    buffers: list[InterviewBufferRecord]
