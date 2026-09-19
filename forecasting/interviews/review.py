"""Explain elicitation gaps without claiming to grade truth or forecast skill."""

from protocol.interviews import InterviewDraft


def review_findings(draft: InterviewDraft) -> list[dict[str, str]]:
    """Non-blocking next steps shared by people, follow-up generation and agents.

    Answer presence is not evidence quality. No NLP score or automatic prior is
    inferred from prose; ordinary settlement and promotion gates remain separate.
    """
    answered = {a.question_id: a for a in draft.answers if a.status == "answered"}
    questions = {q.id for q in draft.questions}
    findings = []
    prompts = (
        (
            "reference_class",
            "Define comparable cases and selection rules before relying on an inside-view story.",
        ),
        (
            "base_rate",
            "Record the observed rate or distribution, denominator, period and source; keep small-sample uncertainty explicit.",
        ),
        (
            "dependence",
            "Check shared causes before combining assumptions; marginal probabilities cannot generally be multiplied.",
        ),
        (
            "counterevidence",
            "Seek the strongest contrary evidence and an alternative explanation.",
        ),
        (
            "crux",
            "Identify the unknown whose plausible answers would most change the estimate.",
        ),
        (
            "triggers",
            "Name an observable review trigger and its source; a trigger does not authorize an automatic update.",
        ),
    )
    for key, message in prompts:
        if key in questions and key not in answered:
            findings.append({
                "field": key,
                "severity": "warning",
                "message": message,
                "fix": "Revisit this interview question; Unknown is valid when unsupported.",
            })
    if "base_rate" in answered:
        findings.append({
            "field": "base_rate",
            "severity": "info",
            "message": "A stated base rate is an elicited claim, not a verified ledger reference class.",
            "fix": "Attach the underlying cases and source through the reference-class workflow before relying on it for promotion.",
        })
    values = [answered.get(f"quantile_{q}") for q in (10, 50, 90)]
    if any(values) and not all(values):
        findings.append({
            "field": "beliefs",
            "severity": "warning",
            "message": "The numeric belief is partial; it does not yet specify the 10th, 50th and 90th percentiles.",
            "fix": "Complete the remaining quantiles or leave them explicitly Unknown; no distribution is inferred.",
        })
    if any(
        a.question_id == "belief" and a.value in (0.0, 1.0) for a in answered.values()
    ):
        findings.append({
            "field": "belief",
            "severity": "warning",
            "message": "This belief rules out one outcome entirely.",
            "fix": "Check for overlooked paths, reporting error and ambiguity before retaining absolute certainty.",
        })
    return findings


def belief_errors(draft: InterviewDraft) -> list[str]:
    """Allow partial drafts, but reject contradictory supplied distributions before analysis."""
    values = {a.question_id: a.value for a in draft.answers if a.status == "answered"}
    errors = []
    quantiles = [values.get(f"quantile_{q}") for q in (10, 50, 90)]
    present = [v for v in quantiles if isinstance(v, float)]
    if present != sorted(present):
        errors.append("Quantiles must increase from the 10th to the 90th percentile.")
    probabilities = [
        values.get(q.id) for q in draft.questions if q.id.startswith("category_prob_")
    ]
    if any(v is not None for v in probabilities):
        if not all(isinstance(v, float) for v in probabilities):
            errors.append("Complete every category probability, or leave all unknown.")
        elif abs(sum(v for v in probabilities if isinstance(v, float)) - 1.0) > 1e-9:
            errors.append("Category probabilities must sum to 1.")
    return errors


def contract_errors(draft: InterviewDraft, contract: dict) -> list[str]:
    """Use the frozen settlement meaning across preview, agents and comparisons."""
    expected = {
        "title": contract["title"],
        "criteria": contract["resolution_criteria"],
        "source": contract["resolution_source"],
        "deadline": contract["close_time"] or contract["resolution_time"],
        "outcome": contract["outcome_space"]["type"],
        "units": contract["outcome_space"]["units"],
    }
    errors = []
    for answer in draft.answers:
        if answer.status != "answered":
            continue
        if answer.question_id == "categories":
            labels = [v.strip() for v in str(answer.value).splitlines() if v.strip()]
            if labels != contract["outcome_space"]["choices"]:
                errors.append(
                    "changed category identities require a new question, not a probability update"
                )
        elif (
            answer.question_id in expected
            and answer.value != expected[answer.question_id]
        ):
            errors.append(
                f"changed resolution contract ({answer.question_id}) requires a new question, not a probability update"
            )
    return errors
