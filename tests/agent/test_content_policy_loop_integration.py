"""Fork-native guards for the content-policy wiring in the conversation loop.

The upstream integration test (tests/run_agent/test_18028_content_policy_blocked.py)
mirrors the ``is_client_error`` predicate but does not exercise our actual
loop source. These cheap checks pin the two things most likely to silently
regress when ``agent/conversation_loop.py`` is refactored (e.g. by the
#33816 status-buffer port that touches the same is_client_error block):

  1. The classification → is_client_error routing stays correct, i.e.
     content_policy_blocked is NOT in the exclusion set and a
     (retryable=False, should_compress=False) content-policy error resolves
     to is_client_error = True (so fallback fires immediately).
  2. The rebranded guidance / final_response strings the loop emits for a
     content-policy block survive (no accidental "hermes" leak, and the
     provider-safety wording stays present).

See PR #33883 / issue #18028.
"""

import inspect

from agent.error_classifier import FailoverReason


def _is_client_error(reason, *, retryable, should_compress=False) -> bool:
    """Re-declaration of conversation_loop.py's is_client_error predicate.

    Kept in lock-step with the source — our local exclusion set INCLUDES
    FailoverReason.billing (unlike upstream's mirror). If you change the
    source set, change this too.
    """
    return (
        not retryable
        and not should_compress
        and reason not in {
            FailoverReason.rate_limit,
            FailoverReason.billing,
            FailoverReason.overloaded,
            FailoverReason.context_overflow,
            FailoverReason.payload_too_large,
            FailoverReason.long_context_tier,
            FailoverReason.thinking_signature,
        }
    )


class TestContentPolicyRouting:
    def test_content_policy_blocked_resolves_to_client_error(self):
        assert _is_client_error(
            FailoverReason.content_policy_blocked,
            retryable=False,
            should_compress=False,
        ), (
            "content_policy_blocked must route through is_client_error so the "
            "loop attempts fallback then aborts instead of burning retries."
        )

    def test_content_policy_blocked_not_in_exclusion_set(self):
        # If someone adds content_policy_blocked to the exclusion set it would
        # silently fall through to the retry-backoff path — the exact bug
        # #33883 fixes. Guard against it.
        assert not _is_client_error(
            FailoverReason.content_policy_blocked,
            retryable=True,   # retryable errors are never client errors
        )


class TestContentPolicyLoopStrings:
    """Grep the live conversation_loop source for the rebranded wiring so an
    accidental ``hermes`` leak or a deleted guidance branch fails CI."""

    def _loop_source(self) -> str:
        import agent.conversation_loop as cl
        return inspect.getsource(cl)

    def test_provider_safety_status_present(self):
        src = self._loop_source()
        assert "Provider safety filter blocked this request" in src

    def test_final_response_mentions_provider_block(self):
        src = self._loop_source()
        assert "not a superforecasting-agent/gateway failure" in src

    def test_guidance_uses_rebranded_command(self):
        src = self._loop_source()
        # The fallback-setup hint must point at our command, not hermes'.
        assert "superforecasting-agent model" in src

    def test_no_hermes_fallback_add_leak(self):
        src = self._loop_source()
        # Upstream's `hermes fallback add` subcommand does not exist here.
        assert "hermes fallback add" not in src
        assert "Hermes/gateway failure" not in src
