"""Deterministic interview spine; model follow-ups supplement these safeguards."""

from protocol.interviews import InterviewChoice, InterviewQuestion, InterviewSection


def core_questions(
    outcome: str = "binary", *, update: bool = False
) -> list[InterviewQuestion]:
    questions: list[tuple[str, InterviewSection, str, str, bool]] = [
        (
            "title",
            "define",
            "What exactly are you forecasting? Name the entity and event.",
            "Distinguish an announcement, attempt, success and realized outcome.",
            True,
        ),
        (
            "criteria",
            "resolve",
            "What observable result counts, and what explicitly does not?",
            "Make settlement possible without interpreting your original intent.",
            True,
        ),
        (
            "source",
            "resolve",
            "Which canonical source will settle this question?",
            "Prefer the original authority over repeated secondary reports.",
            True,
        ),
        (
            "deadline",
            "define",
            "What is the outcome deadline? Enter an ISO timestamp with timezone.",
            "Separate the observation period from when the result becomes known.",
            True,
        ),
        (
            "period",
            "resolve",
            "Which observation period and publication/revision policy apply?",
            "First release and revised values can resolve the same wording differently.",
            False,
        ),
        (
            "censoring",
            "resolve",
            "What happens if the event is cancelled, delayed, or only a bound is reported?",
            "An unavailable or censored observation is not automatically a negative outcome.",
            False,
        ),
        (
            "reference_class",
            "outside_view",
            "What comparable cases form your reference class? State inclusion and exclusion rules.",
            "Use an outside view before constructing a persuasive story about this case.",
            False,
        ),
        (
            "base_rate",
            "outside_view",
            "How many comparable cases succeeded, out of how many, over what period?",
            "A rate without a denominator hides small-sample uncertainty and selection bias.",
            False,
        ),
        (
            "drivers",
            "drivers",
            "List the assumptions that matter, one per line.",
            "Include enabling conditions, obstacles and dependencies; an assumption is not an established fact.",
            False,
        ),
        (
            "dependence",
            "drivers",
            "Which drivers share causes or depend on each other?",
            "Do not multiply correlated marginal probabilities as if they were independent.",
            False,
        ),
        (
            "epistemic",
            "uncertainty",
            "Which facts could you learn that would materially change your estimate?",
            "Identify missing knowledge and the source or observation that could resolve it.",
            False,
        ),
        (
            "aleatoric",
            "uncertainty",
            "Which future variability would remain even with better information?",
            "Specify useful conditioning variables without pretending that all randomness can be removed.",
            False,
        ),
        (
            "measurement",
            "uncertainty",
            "Where could measurement, reporting delay or model disagreement mislead you?",
            "Separate uncertainty in the phenomenon from uncertainty in its measurement.",
            False,
        ),
        (
            "counterevidence",
            "challenge",
            "What is the strongest case for a different outcome?",
            "Seek disconfirming evidence, not just additional support for your first estimate.",
            False,
        ),
        (
            "crux",
            "challenge",
            "Which assumption would most change your estimate if it failed?",
            "Describe estimates if it holds and if it fails; research matters when plausible answers would change your judgment or decision.",
            False,
        ),
        (
            "triggers",
            "update_plan",
            "What new observation should trigger a review, and how much change would matter?",
            "A review trigger proposes reconsideration; it does not authorize an automatic probability change.",
            False,
        ),
        (
            "decision",
            "update_plan",
            "What decision does this forecast inform, and when must it be made?",
            "Record the action threshold separately from the event probability.",
            False,
        ),
    ]
    result = [
        InterviewQuestion(
            id=id, section=section, prompt=prompt, rationale=why, required=required
        )
        for id, section, prompt, why, required in questions
    ]
    result.insert(
        1,
        InterviewQuestion(
            id="outcome",
            section="define",
            prompt="What kind of outcome will be scored?",
            rationale="The outcome type determines valid beliefs, resolution and scoring.",
            kind="single",
            allow_custom=False,
            required=True,
            choices=[
                InterviewChoice(id="binary", label="Yes / no"),
                InterviewChoice(id="numeric", label="Numeric measurement"),
                InterviewChoice(
                    id="categorical", label="Mutually exclusive categories"
                ),
            ],
        ),
    )
    if outcome == "binary":
        belief = [
            InterviewQuestion(
                id="belief",
                section="beliefs",
                kind="probability",
                prompt="Before seeing a model suggestion, what is your probability (0 to 1)?",
                rationale="If you say 0.7, about 7 of 10 comparable forecasts should occur.",
            )
        ]
    elif outcome == "numeric":
        belief = [
            InterviewQuestion(
                id="units",
                section="resolve",
                required=True,
                prompt="What exact units and measurement definition apply?",
                rationale="Percent, percentage points, index levels and annualized rates differ.",
            )
        ]
        belief.extend(
            InterviewQuestion(
                id=f"quantile_{q}",
                section="beliefs",
                kind="number",
                prompt=f"What value do you expect the outcome to fall at or below with {q}% probability?",
                rationale="Use quantiles to represent a distribution, not a false-precision point estimate.",
            )
            for q in (10, 50, 90)
        )
    else:
        belief = [
            InterviewQuestion(
                id="categories",
                section="resolve",
                required=True,
                prompt="List mutually exclusive outcomes, one per line, including any residual category.",
                rationale="The categories must cover every possible settlement outcome.",
            ),
            InterviewQuestion(
                id="category_beliefs",
                section="beliefs",
                prompt="Give a probability for each category; the probabilities must sum to 1.",
                rationale="Record a complete distribution, including low-probability alternatives.",
            ),
        ]
    if outcome != "binary":
        base_rate = next(q for q in result if q.id == "base_rate")
        base_rate.prompt = (
            "Across comparable cases, what is the distribution (median, spread and tails), in these units? State the sample size and period."
            if outcome == "numeric"
            else "Across comparable cases, how many fell in each category? State the total sample size and period."
        )
        base_rate.rationale = "Use comparable measurements and a defined sample; do not substitute a binary success rate or treat a small sample as precise."
    # An initial independent judgment precedes model advice or outside-view anchoring.
    result[6:6] = belief
    if update:
        result.insert(
            0,
            InterviewQuestion(
                id="new_evidence",
                section="beliefs",
                prompt="What has changed since the previous forecast? Cite new evidence and its date.",
                rationale="Explain an update relative to its frozen baseline; do not rewrite the old reasoning.",
            ),
        )
    return result
