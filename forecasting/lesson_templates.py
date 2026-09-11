"""Lesson -> hook-rule patterns.

Turn a calibration lesson's INTENT into an enforceable hook RuleSpec, so a learning
becomes strict, formal enforcement WITHOUT anyone hand-authoring a rule (the
lazy-operator pattern: the system applies the lesson, the operator does not). A
lesson either declares an ``enforcement_pattern`` in its ``recommended_adjustment``,
or the system infers one from the lesson's ``process_rule`` / text. Every pattern
references signals that ALREADY exist in the hooks DSL; the rule's ``applies_to`` is
force-stamped from the lesson's own scope at compile time (``compile_lesson_rules``),
so a pattern can never widen scope.

The patterns are GENERIC (a small, auditable library) — not bound to any specific
forecast. New patterns are added here once and become available to every lesson.
"""

from __future__ import annotations

from typing import Any, Callable


def _tail_cap(lesson: dict[str, Any], severity: str, *, threshold: float = 0.15) -> dict[str, Any]:
    return {
        "category": "confidence",
        "severity": severity,
        "message": (
            f"Lesson {lesson.get('id', '?')}: compress unearned lower-tier / tail mass into the "
            "viable field — no-path candidates must not hold fat share (raise viability, haircut, "
            "or justify the tail)."
        ),
        "check": {"signal": "tails.null_excess", "op": "<=", "value": threshold},
        "remediation_hint": "compress_tails",
    }


def _born_scoreable(lesson: dict[str, Any], severity: str) -> dict[str, Any]:
    return {
        "category": "output",
        "severity": severity,
        "message": (
            f"Lesson {lesson.get('id', '?')}: a vote-share forecast must be born MACHINE-SCOREABLE — "
            "numeric candidate shares keyed to the question's choices (so it is graded automatically, "
            "not by hand)."
        ),
        "check": {"signal": "outcome.machine_scoreable", "op": "is_true"},
        "remediation_hint": "fix_distribution",
    }


def _require_reference_class(lesson: dict[str, Any], severity: str) -> dict[str, Any]:
    return {
        "category": "reasoning",
        "severity": severity,
        "message": f"Lesson {lesson.get('id', '?')}: attach an outside-view reference class before committing.",
        "check": {"signal": "reference_classes.count", "op": ">=", "value": 1},
        "remediation_hint": "add_reference_class",
    }


def _require_winner_backing(lesson: dict[str, Any], severity: str, *, cap: float = 0.65) -> dict[str, Any]:
    return {
        "category": "calibration",
        "severity": severity,
        "message": (
            f"Lesson {lesson.get('id', '?')}: a >{int(cap * 100)}% winner call needs a linked "
            f"vote-share / derived model — cap below {cap}, link one, or mark exploratory."
        ),
        "check": {
            "any": [
                {"signal": "confidence.winner_prob", "op": "<=", "value": cap},
                {"signal": "links.derived_child_present", "op": "is_true"},
            ]
        },
        "remediation_hint": "decompose",
    }


# The auditable pattern library. Add a pattern here once; it is then available to
# every lesson (declared or inferred).
LESSON_ENFORCEMENT_PATTERNS: dict[str, Callable[..., dict[str, Any]]] = {
    "tail_cap": _tail_cap,
    "born_scoreable": _born_scoreable,
    "require_reference_class": _require_reference_class,
    "require_winner_backing": _require_winner_backing,
}

# Keyword inference (checked in order) for a lesson that does NOT declare an explicit
# enforcement_pattern. Conservative: born_scoreable before tail_cap before winner
# before reference-class, so the most specific intent wins.
_PATTERN_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("born_scoreable", ("scoreab", "machine-scoreable", "machine_scoreable")),
    ("tail_cap", ("tail", "compress", "consolidat", "top_two", "top-two", "lower-tier", "lower_tier", "haircut", "candidate_tail_cap")),
    ("require_winner_backing", ("winner_prob", "winner backing", "winner-backing", "winner odds", "vote_share_first", "vote-share first")),
    ("require_reference_class", ("reference_class", "reference class", "base_rate", "base rate", "outside_view", "outside view")),
]


def resolve_enforcement_pattern(recommended_adjustment: Any) -> str | None:
    """The pattern a lesson maps to: its explicit ``enforcement_pattern`` if valid,
    else inferred from its process_rule / text keywords. None -> advisory."""
    adjustment = recommended_adjustment if isinstance(recommended_adjustment, dict) else {}
    explicit = adjustment.get("enforcement_pattern")
    if isinstance(explicit, str) and explicit in LESSON_ENFORCEMENT_PATTERNS:
        return explicit
    haystack = " ".join(
        str(adjustment.get(key, ""))
        for key in ("process_rule", "candidate_tail_cap", "tooling_fix", "adjustment", "share_adjustment", "trigger")
    ).lower()
    for pattern, keywords in _PATTERN_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return pattern
    return None


def build_lesson_rule(lesson: dict[str, Any], *, severity: str = "warn") -> dict[str, Any] | None:
    """Build a hook RuleSpec dict from a lesson's enforcement pattern (WARN by
    default — observe-then-flip). None when no pattern applies (the lesson stays
    advisory). The returned rule's applies_to is intentionally absent — it is
    force-stamped from the lesson's scope by compile_lesson_rules."""
    pattern = resolve_enforcement_pattern(lesson.get("recommended_adjustment"))
    if pattern is None:
        return None
    if pattern == "tail_cap" and (lesson.get("scope_ref") or "").split(":")[0] == "weather":
        return None  # Candidate viability is not a temperature-tail measurement.
    return LESSON_ENFORCEMENT_PATTERNS[pattern](lesson, severity)
