"""Serialize browser endpoint changes and surface incomplete cleanup."""

from collections.abc import Callable, MutableMapping

from superforecasting_agent.hosting.browser_sessions import browser_endpoint_transition


def change_browser_endpoint(
    endpoint: str | None,
    *,
    environment: MutableMapping[str, str],
    cleanup: Callable[[], None],
) -> None:
    """Drain old resources before publishing, then drain resources from the swap.

    The guard drains admitted browser lifecycles before publication. A failure
    before publication preserves the old setting. After publication the desired
    setting remains visible and the caller must report incomplete cleanup.
    """
    with browser_endpoint_transition():
        cleanup()
        if endpoint is None:
            # Empty is an explicit process override: do not fall back to config.
            environment["BROWSER_CDP_URL"] = ""
        else:
            environment["BROWSER_CDP_URL"] = endpoint
        try:
            cleanup()
        except Exception as exc:
            raise RuntimeError(
                "Browser endpoint changed, but cleanup is incomplete"
            ) from exc
