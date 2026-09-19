"""Shared questionnaire operations for interactive clients and scheduled agents."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger

from forecasting.interviews.context import capture_context, read_context
from forecasting.interviews.questions import category_questions, core_questions
from forecasting.interviews.review import (
    belief_errors,
    contract_errors,
    review_findings,
)
from forecasting.interviews.store import InterviewStore
from forecasting.models import ValidationError, parse_timestamp
from forecasting.question_spec import spec_from_dict
from protocol.interviews import (
    ForecastMarketSeed,
    InterviewAnswer,
    InterviewAssumption,
    InterviewDraft,
    InterviewParent,
    InterviewScenario,
)


class InterviewService:
    def __init__(self, ledger: ForecastLedger):
        self.ledger = ledger
        self.store = InterviewStore(ledger)

    def begin(
        self,
        interview_id: str,
        *,
        title: str = "New forecast",
        question_id: str | None = None,
        seed: ForecastMarketSeed | dict | None = None,
    ) -> dict:
        seed = ForecastMarketSeed.model_validate(seed) if seed is not None else None
        if question_id and seed:
            raise ValidationError(
                "market seeds create new questions; they do not replace existing contracts"
            )
        # Client-generated IDs survive request retries. Never replace an existing draft.
        with self.ledger.transaction(immediate=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM forecast_interview_revisions WHERE interview_id = ?",
                (interview_id,),
            ).fetchone()
            if exists:
                existing = self.store.read(interview_id)
                if existing["document"]["question_id"] != question_id or existing[
                    "document"
                ].get("seed") != (seed.model_dump() if seed else None):
                    raise ValidationError(
                        "interview identifier belongs to another target"
                    )
                return existing
            question = self.ledger.get_question(question_id) if question_id else None
            outcome = (
                question.outcome_space.type
                if question
                else "numeric"
                if seed and seed.kind == "series"
                else "binary"
            )
            context, context_digest = (
                capture_context(self.ledger, interview_id, question)
                if question
                else (None, None)
            )
            document = InterviewDraft(
                mode="update" if question else "create",
                question_id=question_id,
                baseline_forecast_id=question.current_forecast_id if question else None,
                title=question.title if question else seed.title if seed else title,
                seed=seed,
                context_digest=context_digest,
                evidence_refs=[item["id"] for item in context["evidence"]]
                if context
                else [],
                questions=core_questions(outcome, update=bool(question)),
            )
            if context and context.get("prior_interview"):
                prior = context["prior_interview"]
                document.parent_interview = InterviewParent.model_validate({
                    key: prior[key] for key in ("interview_id", "revision", "digest")
                })
                historical = InterviewDraft.model_validate(prior["document"])
                document.assumptions = historical.assumptions
                document.scenarios = historical.scenarios
            if question:
                values = {
                    "title": question.title,
                    "criteria": question.resolution_criteria,
                    "source": question.resolution_source,
                    "deadline": question.close_time or question.resolution_time,
                    "outcome": outcome,
                    "units": question.outcome_space.units,
                    "categories": "\n".join(question.outcome_space.choices)
                    if outcome == "categorical"
                    else None,
                }
                if outcome == "categorical":
                    document.questions = [
                        q for q in document.questions if q.id != "category_beliefs"
                    ]
                    at = (
                        next(
                            i
                            for i, q in enumerate(document.questions)
                            if q.id == "categories"
                        )
                        + 1
                    )
                    document.questions[at:at] = category_questions(
                        question.outcome_space.choices
                    )
                ids = {q.id for q in document.questions}
                document.answers = [
                    InterviewAnswer(
                        question_id=key,
                        status="answered",
                        value=value,
                        actor="agent",
                        note=f"Existing question contract: {question.id}. Confirm before changing.",
                    )
                    for key, value in values.items()
                    if value and key in ids
                ]
            return self.store.save(
                interview_id,
                document,
                expected_revision=0,
                request_id="begin",
                actor="agent",
            )

    def answer(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        request_id: str,
        question_id: str,
        status: Literal["answered", "unknown", "skipped"],
        value: str | float | list[str] | None = None,
        note: str = "",
        custom_text: str | None = None,
        actor: Literal["user", "agent"] = "user",
        evidence_refs: list[str] | None = None,
    ) -> dict:
        # Read the stated base, not latest: a retry must reproduce the exact same revision.
        record = self.store.read(interview_id, expected_revision)
        draft = InterviewDraft.model_validate(record["document"])
        prior_answer = next(
            (a for a in draft.answers if a.question_id == question_id), None
        )
        answer = InterviewAnswer(
            question_id=question_id,
            status=status,
            value=value,
            note=note,
            custom_text=custom_text,
            actor=actor,
            evidence_refs=evidence_refs
            if evidence_refs is not None
            else list(prior_answer.evidence_refs)
            if prior_answer
            else [],
        )
        if question_id not in {question.id for question in draft.questions}:
            raise ValidationError("unknown interview question")
        draft.answers = [a for a in draft.answers if a.question_id != question_id] + [
            answer
        ]
        if status == "answered" and question_id == "outcome":
            questions = core_questions(str(value), update=draft.mode == "update")
            core_ids = {
                q.id
                for kind in ("binary", "numeric", "distribution", "categorical")
                for q in core_questions(kind, update=draft.mode == "update")
            }
            questions += [
                q
                for q in draft.questions
                if q.id not in core_ids and not q.id.startswith("category_prob_")
            ]
            # Reconfirming the same outcome must preserve category elicitation.
            if value == "categorical":
                questions += [
                    q for q in draft.questions if q.id.startswith("category_prob_")
                ]
                if any(q.id.startswith("category_prob_") for q in questions):
                    questions = [q for q in questions if q.id != "category_beliefs"]
            ids = {q.id for q in questions}
            if any(a.question_id not in ids for a in draft.answers):
                raise ValidationError(
                    "outcome change would discard prior answers; start a new interview"
                )
            if (
                prior_answer
                and prior_answer.status == "answered"
                and prior_answer.value == value
            ):
                # Reconfirmation must not rewrite questions from a frozen older version.
                existing_questions = {q.id: q for q in draft.questions}
                questions = [existing_questions.get(q.id, q) for q in questions]
            draft.questions = questions
        if status == "answered" and question_id == "categories":
            labels = [
                label.strip() for label in str(value).splitlines() if label.strip()
            ]
            if len(labels) < 2 or len(set(label.casefold() for label in labels)) != len(
                labels
            ):
                raise ValidationError("provide at least two distinct categories")
            if len(labels) > 20:
                raise ValidationError("use at most 20 categories")
            draft.questions = [
                q
                for q in draft.questions
                if q.id != "category_beliefs" and not q.id.startswith("category_prob_")
            ]
            at = (
                next(i for i, q in enumerate(draft.questions) if q.id == "categories")
                + 1
            )
            draft.questions[at:at] = category_questions(labels)
        if status == "answered" and question_id == "title":
            draft.title = str(value)
        if status == "answered" and question_id == "drivers":
            known = {a.id: a for a in draft.assumptions}
            for statement in str(value).splitlines():
                statement = statement.strip()
                if statement:
                    id = (
                        "assumption_"
                        + hashlib.sha256(statement.encode()).hexdigest()[:16]
                    )
                    known.setdefault(
                        id, InterviewAssumption(id=id, statement=statement, actor=actor)
                    )
            draft.assumptions = list(known.values())
        draft.status = (
            "needs_user"
            if any(a.status == "unknown" and a.actor == "user" for a in draft.answers)
            else "needs_research"
            if any(a.status == "unknown" for a in draft.answers)
            else "draft"
        )
        return self.store.save(
            interview_id,
            draft,
            expected_revision=expected_revision,
            request_id=request_id,
            actor=actor,
        )

    def save_assumption(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        request_id: str,
        assumption: InterviewAssumption | dict,
        actor: Literal["user", "agent"] = "user",
    ) -> dict:
        draft = InterviewDraft.model_validate(
            self.store.read(interview_id, expected_revision)["document"]
        )
        assumption = InterviewAssumption.model_validate(assumption).model_copy(
            update={"actor": actor}
        )
        if not set(assumption.evidence_refs) <= set(draft.evidence_refs):
            raise ValidationError(
                "assumption cites evidence outside the frozen interview"
            )
        existing = {item.id: item for item in draft.assumptions}
        existing[assumption.id] = assumption
        draft.assumptions = list(existing.values())
        if draft.status == "ready":
            draft.status = "draft"
        return self.store.save(
            interview_id,
            draft,
            expected_revision=expected_revision,
            request_id=request_id,
            actor=actor,
        )

    def save_scenario(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        request_id: str,
        scenario: InterviewScenario | dict,
        actor: Literal["user", "agent"] = "user",
    ) -> dict:
        draft = InterviewDraft.model_validate(
            self.store.read(interview_id, expected_revision)["document"]
        )
        scenario = InterviewScenario.model_validate(scenario).model_copy(
            update={"actor": actor}
        )
        draft.scenarios = [
            item for item in draft.scenarios if item.id != scenario.id
        ] + [scenario]
        return self.store.save(
            interview_id,
            draft,
            expected_revision=expected_revision,
            request_id=request_id,
            actor=actor,
        )

    def delete_scenario(
        self,
        interview_id: str,
        *,
        expected_revision: int,
        request_id: str,
        scenario_id: str,
        actor: Literal["user", "agent"] = "user",
    ) -> dict:
        draft = InterviewDraft.model_validate(
            self.store.read(interview_id, expected_revision)["document"]
        )
        if scenario_id not in {item.id for item in draft.scenarios}:
            raise ValidationError("scenario not found")
        draft.scenarios = [item for item in draft.scenarios if item.id != scenario_id]
        return self.store.save(
            interview_id,
            draft,
            expected_revision=expected_revision,
            request_id=request_id,
            actor=actor,
        )

    def preview(self, interview_id: str, revision: int) -> dict:
        if type(revision) is not int or revision < 1:
            raise ValidationError("revision must be a positive integer")
        draft = InterviewDraft.model_validate(
            self.store.read(interview_id, revision)["document"]
        )
        values = {
            a.question_id: a.value for a in draft.answers if a.status == "answered"
        }
        missing = [
            q.prompt for q in draft.questions if q.required and q.id not in values
        ]
        outcome = values.get("outcome", "binary")
        raw = {
            "title": values.get("title", draft.title),
            "resolution_criteria": values.get("criteria", ""),
            "resolution_source": values.get("source"),
            "outcome_type": outcome,
            "close_time": values.get("deadline"),
            "autonomy": "ask",
            "clarifications": [answer.model_dump() for answer in draft.answers],
        }
        raw["clarifications"].append({
            "kind": "interview_provenance",
            "interview_id": interview_id,
            "revision": revision,
            "source_seed": draft.seed.model_dump() if draft.seed else None,
            "evidence_refs": list(draft.evidence_refs),
            "verification_status": "interview_context_not_settlement_verification",
        })
        if outcome in {"numeric", "distribution"}:
            raw["units"] = values.get("units")
        elif outcome == "categorical":
            raw["choices"] = [
                v.strip()
                for v in str(values.get("categories", "")).splitlines()
                if v.strip()
            ]
        missing.extend(belief_errors(draft))
        if draft.mode == "update" and draft.context_digest:
            context = read_context(self.ledger, interview_id, draft.context_digest)
            missing.extend(contract_errors(draft, context["question"]))
        try:
            deadline = raw["close_time"]
            if deadline is not None and not isinstance(deadline, str):
                raise ValidationError("deadline must be a timestamp string")
            raw["close_time"] = parse_timestamp(deadline, field_name="deadline")
            spec = spec_from_dict(raw)
            issues = [issue.to_dict() for issue in spec.validate()]
            normalized = spec.to_dict()
        except (ValidationError, ValueError, TypeError) as exc:
            issues = [
                {
                    "field": "spec",
                    "severity": "error",
                    "message": str(exc),
                    "fix": "Review the answers",
                }
            ]
            normalized = raw
        return {
            "spec": normalized,
            "issues": issues + review_findings(draft),
            "unanswered": missing,
            "committable": not missing
            and not any(i["severity"] == "error" for i in issues),
        }

    def commit(self, interview_id: str, revision: int) -> dict:
        from forecasting.models import utc_now_iso

        if type(revision) is not int or revision < 1:
            raise ValidationError("revision must be a positive integer")
        with self.ledger.transaction(immediate=True) as conn:
            receipt = conn.execute(
                "SELECT revision, question_id FROM forecast_interview_commits WHERE interview_id = ?",
                (interview_id,),
            ).fetchone()
            if receipt:
                if receipt["revision"] != revision:
                    raise ValidationError(
                        "a different interview revision was already committed"
                    )
                return {"question_id": receipt["question_id"], "revision": revision}
            record = self.store.read(interview_id)
            if record["revision"] != revision:
                raise ValidationError("interview changed; reload before committing")
            draft = InterviewDraft.model_validate(record["document"])
            if draft.mode != "create" or draft.status == "cancelled":
                raise ValidationError(
                    "only active new-question interviews can create a question"
                )
            preview = self.preview(interview_id, revision)
            if not preview["committable"]:
                raise ValidationError(
                    "required answers or resolution criteria need review"
                )
            result = spec_from_dict(preview["spec"]).commit(self.ledger)
            conn.execute(
                "INSERT INTO forecast_interview_commits (interview_id, revision, question_id, committed_at) "
                "VALUES (?, ?, ?, ?)",
                (interview_id, revision, result["question_id"], utc_now_iso()),
            )
            conn.execute(
                "UPDATE forecast_interview_buffers SET document=NULL WHERE interview_id=?",
                (interview_id,),
            )
            return {"question_id": result["question_id"], "revision": revision}
