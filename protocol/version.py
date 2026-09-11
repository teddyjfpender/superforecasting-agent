"""The single wire-protocol version for the gateway.

Bumped when a breaking change lands on the wire. The gateway advertises
``PROTOCOL_VERSION`` and ``MIN_SUPPORTED`` in its hello response. Clients must
select a supported version and verify required operation capabilities before
starting a session. There is no per-message
versioning — the whole wire is one version.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
MIN_SUPPORTED = 1

__all__ = ["PROTOCOL_VERSION", "MIN_SUPPORTED"]
