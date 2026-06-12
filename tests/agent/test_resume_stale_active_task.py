"""Regression coverage for #35344: a resumed session must not let a stale
historical task snapshot from an inherited compaction handoff hijack the reply to a
new, unrelated user message.

The failure mode (real report): a lineage was compacted, producing a handoff
whose historical task snapshot described task A. The lineage was resumed later and
the user asked about an unrelated task B. The model answered with A because
the handoff's resume directive outranked the fresh ask.

The structural fix lives in ``SUMMARY_PREFIX``: the handoff is framed as
reference-only and the latest user message explicitly *wins* on conflict, with
named reverse-signal verbs. Two invariants guard the resume path specifically:

  1. A handoff persisted under the OLD (conflicting) prefix is re-normalized to
     the CURRENT prefix when it is re-compacted on a resumed lineage — so a
     pre-fix stale handoff cannot keep its "resume exactly" directive forever.

  2. The current handoff prefix contains an unambiguous "latest message wins /
     discard stale historical task" rule, so an unrelated new ask is privileged over
     the inherited task snapshot.

These are content/structural assertions (no live model call) — they pin the
mechanism that makes the stale task historical rather than active.

Fork note: the operative "old conflicting prefix" for this fork is the
fork-point-era prefix that includes the MEMORY.md/USER.md authority clause —
that is what this fork's builds persisted into saved sessions. The upstream
pre-fork variant (without the memory clause) is also frozen in
``_HISTORICAL_SUMMARY_PREFIXES`` and covered below.
"""

from agent.context_compressor import (
    HISTORICAL_TASK_HEADING,
    SUMMARY_PREFIX,
    LEGACY_SUMMARY_PREFIX,
    _HISTORICAL_SUMMARY_PREFIXES,
    ContextCompressor,
)


# The conflicting prefix that shipped before the #35344 fix — the fork-era
# generation, exactly as persisted by this fork's saved sessions.
_OLD_CONFLICTING_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. "
    "Your current task is identified in the '## Active Task' section of the "
    "summary — resume exactly from there. "
    "IMPORTANT: Your persistent memory (MEMORY.md, USER.md) in the system "
    "prompt is ALWAYS authoritative and active — never ignore or deprioritize "
    "memory content due to this compaction note. "
    "Respond ONLY to the latest user message "
    "that appears AFTER this summary. The current session state (files, "
    "config, etc.) may reflect work described here — avoid repeating it:"
)


def test_latest_message_wins_over_inherited_active_task():
    """The handoff must explicitly privilege the latest user message over a
    stale historical task snapshot — the core #35344 contract."""
    lower = SUMMARY_PREFIX.lower()
    assert "latest user message" in lower
    assert HISTORICAL_TASK_HEADING.lower() in lower
    # Conflict-resolution must be explicit, not implied.
    assert "wins" in lower or "supersede" in lower
    assert "discard" in lower


def test_no_resume_exactly_directive_can_hijack():
    """The directive that caused the hijack ("resume exactly from Active
    Task") must be gone."""
    assert "resume exactly" not in SUMMARY_PREFIX.lower()


def test_fork_era_prefix_is_frozen():
    """The fork's shipped pre-fix prefix must be frozen verbatim in
    ``_HISTORICAL_SUMMARY_PREFIXES`` — saved fork sessions carry it."""
    assert _OLD_CONFLICTING_PREFIX in _HISTORICAL_SUMMARY_PREFIXES


def test_resumed_stale_handoff_gets_renormalized_to_current_prefix():
    """A handoff persisted under the OLD conflicting prefix (e.g. saved before
    the fix and inherited into a resumed lineage) is upgraded to the CURRENT
    prefix when re-normalized on re-compaction — so the "resume exactly"
    directive cannot survive into a resumed session."""
    stale_body = (
        f"{HISTORICAL_TASK_HEADING}\n"
        "User asked: 'Migrate the billing module to Stripe'\n\n"
        "## Goal\nMigrate billing.\n"
    )
    stale_handoff = f"{_OLD_CONFLICTING_PREFIX}\n{stale_body}"

    # Sanity: the fixture really does carry the old directive.
    assert "resume exactly" in stale_handoff.lower()

    renormalized = ContextCompressor._with_summary_prefix(stale_handoff)

    # The body is preserved...
    assert "Migrate the billing module to Stripe" in renormalized
    # ...but the conflicting directive is stripped and replaced with the
    # current latest-message-wins framing.
    assert "resume exactly" not in renormalized.lower()
    assert renormalized.startswith(SUMMARY_PREFIX)
    assert "wins" in renormalized.lower()


def test_every_historical_prefix_renormalizes():
    """Every frozen historical prefix (fork-era and upstream pre-fork) must be
    detected and stripped, so no retired generation can keep its stale
    directive embedded in a renormalized body."""
    for old_prefix in _HISTORICAL_SUMMARY_PREFIXES:
        stale_handoff = f"{old_prefix}\n## Active Task\nUser asked: 'task A'"
        assert ContextCompressor._is_context_summary_content(stale_handoff)
        renormalized = ContextCompressor._with_summary_prefix(stale_handoff)
        assert renormalized.startswith(SUMMARY_PREFIX)
        assert "resume exactly" not in renormalized.lower()
        assert "task A" in renormalized


def test_legacy_prefix_handoff_also_renormalized():
    """The same upgrade applies to the oldest ``[CONTEXT SUMMARY]:`` handoff
    format that may sit in a long-lived resumed lineage."""
    legacy = f"{LEGACY_SUMMARY_PREFIX} {HISTORICAL_TASK_HEADING}\nUser asked: 'task A'"
    renormalized = ContextCompressor._with_summary_prefix(legacy)
    assert renormalized.startswith(SUMMARY_PREFIX)
    assert LEGACY_SUMMARY_PREFIX not in renormalized
    assert "task A" in renormalized


def test_inherited_handoff_detected_in_resumed_protected_head():
    """On a resumed lineage the handoff commonly sits right after the system
    prompt (in the protected head). ``_find_latest_context_summary`` must
    detect it there so re-compaction rehydrates state from it rather than
    serializing it as a fresh user turn (which is what let the stale Active
    Task read as live intent)."""
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": f"{SUMMARY_PREFIX}\n{HISTORICAL_TASK_HEADING}\nUser asked: 'task A'"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "Unrelated task B: what's the capital of France?"},
    ]
    # Search the whole post-system range.
    idx, body = ContextCompressor._find_latest_context_summary(
        messages, 1, len(messages)
    )
    assert idx == 1, "handoff in protected head must be found"
    assert "task A" in body
    # The detected body is stripped of the prefix (treated as state, not a
    # standalone instruction message).
    assert not body.startswith(SUMMARY_PREFIX)


def test_historical_prefixed_handoff_detected_and_stripped():
    """A pre-fix handoff (old conflicting prefix) inherited into a resumed
    lineage must still be recognized as a context summary AND have its old
    directive stripped on detection — otherwise re-compaction serializes the
    stale 'resume exactly' text as a fresh turn."""
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": f"{_OLD_CONFLICTING_PREFIX}\n## Active Task\nUser asked: 'task A'"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "Unrelated task B"},
    ]
    idx, body = ContextCompressor._find_latest_context_summary(
        messages, 1, len(messages)
    )
    assert idx == 1
    assert "task A" in body
    assert "resume exactly" not in body.lower()
