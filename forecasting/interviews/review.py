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
