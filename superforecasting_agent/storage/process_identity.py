"""Conservative local process identity for durable execution ownership."""

import hashlib
import socket
import uuid


def host_identity() -> str:
    """Stable named-machine/network identity; foreign identities are not local proof."""
    return hashlib.sha256(
        f"{socket.gethostname()}:{uuid.getnode()}".encode()
    ).hexdigest()


def process_has_exited(
    host: str | None, pid: int | None, started: float | None
) -> bool:
    """Only positive local absence or PID reuse authorizes owner retirement."""
    import psutil

    if host != host_identity() or pid is None or started is None:
        return False
    try:
        return psutil.Process(pid).create_time() != started
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, OSError):
        return False
