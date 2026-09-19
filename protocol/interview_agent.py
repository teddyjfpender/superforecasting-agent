"""Agent-owned interview operations; no user impersonation or promotion action."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from protocol.interviews import InterviewFollowups, InterviewModel, InterviewScenario


class InterviewAgentAnswer(InterviewModel):
    question_id: str
    status: Literal["answered", "unknown", "skipped"]
    value: str | float | list[str] | None = None
    custom_text: str | None = None
    note: str = ""
    evidence_refs: list[str] = Field(default_factory=list, max_length=200)


class InterviewAgentRequest(InterviewModel):
    operation: Literal["begin", "read", "answer", "propose", "scenario"]
    interview_id: str = Field(min_length=1, max_length=200)
    question_id: str | None = None
    revision: int | None = Field(default=None, ge=1)
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    answer: InterviewAgentAnswer | None = None
    followups: InterviewFollowups | None = None
    scenario: InterviewScenario | None = None
