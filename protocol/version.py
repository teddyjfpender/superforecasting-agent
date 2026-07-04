"""The single wire-protocol version for the gateway.

Bumped when a breaking change lands on the wire. The gateway advertises
``PROTOCOL_VERSION`` in its hello/info response; the TUI warns (never hard-fails)
when its generated ``PROTOCOL_VERSION`` differs. There is no per-message
versioning — the whole wire is one version.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
MIN_SUPPORTED = 1

__all__ = ["PROTOCOL_VERSION", "MIN_SUPPORTED"]
