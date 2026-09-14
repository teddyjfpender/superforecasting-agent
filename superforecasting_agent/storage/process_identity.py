"""Conservative local process identity for durable execution ownership."""

import hashlib
import os
import socket
import sys
import uuid
from pathlib import Path


def host_identity() -> str:
    """Identify a local PID namespace without UUID's per-process random fallback."""
    if sys.platform.startswith("linux"):
        try:
            boot = uuid.UUID(
                Path("/proc/sys/kernel/random/boot_id")
                .read_text(encoding="ascii")
                .strip()
            )
            namespace = os.stat("/proc/self/ns/pid").st_ino
            if namespace <= 0:
                raise ValueError("invalid PID namespace")
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Durable ownership requires Linux boot and PID namespace identity"
            ) from exc
        return hashlib.sha256(f"linux:{boot}:{namespace}".encode()).hexdigest()
    node = uuid.getnode()
    if node & (1 << 40):
        # UUID marks its random fallback with the multicast bit. Such a value
        # cannot establish that another process's persisted PID is local.
        raise RuntimeError(
            "No stable machine identity is available for durable ownership"
        )
    return hashlib.sha256(f"{socket.gethostname()}:{node}".encode()).hexdigest()


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
