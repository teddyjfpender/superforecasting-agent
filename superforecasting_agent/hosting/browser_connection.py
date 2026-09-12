"""Serialize browser endpoint changes and surface incomplete cleanup."""

import threading
from collections.abc import Callable, MutableMapping

_change_lock = threading.Lock()


def change_browser_endpoint(
    endpoint: str | None,
    *,
    environment: MutableMapping[str, str],
    cleanup: Callable[[], None],
) -> None:
    """Drain old resources before publishing, then drain resources from the swap.

    The lock serializes connection commands, not browser tool execution. A failure
    before publication preserves the old setting. After publication the desired
    setting remains visible and the caller must report incomplete cleanup.
    """
    with _change_lock:
        cleanup()
        if endpoint is None:
            environment.pop("BROWSER_CDP_URL", None)
        else:
            environment["BROWSER_CDP_URL"] = endpoint
        try:
            cleanup()
        except Exception as exc:
            raise RuntimeError(
                "Browser endpoint changed, but cleanup is incomplete"
            ) from exc
