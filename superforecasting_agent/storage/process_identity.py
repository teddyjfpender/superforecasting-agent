"""Conservative local process identity for durable execution ownership."""

import hashlib
import math
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path


def _windows_boot_uuid() -> uuid.UUID:
    """Probe SystemBootEnvironmentInformation; unsupported native layouts fail closed.

    Fixed-width ABI: GUID(16), firmware enum(4), alignment(4), boot flags(8).
    The class/layout is documented by phnt's ntexapi.h, not a public Win32 contract.
    """
    import ctypes

    load = getattr(ctypes, "WinDLL", None)
    if load is None:
        raise OSError("native Windows library loading is unavailable")
    # LOAD_LIBRARY_SEARCH_SYSTEM32 avoids searching the cwd or profile directory.
    query = load("ntdll.dll", winmode=0x00000800).NtQuerySystemInformation
    query.argtypes = [
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    query.restype = ctypes.c_int32
    data = (ctypes.c_uint64 * 4)()  # 32 bytes, aligned for the 64-bit flags field.
    returned = ctypes.c_uint32()
    status = query(90, ctypes.byref(data), ctypes.sizeof(data), ctypes.byref(returned))
    if status != 0 or returned.value != ctypes.sizeof(data):
        raise OSError(
            "Windows boot identity query failed or returned an unsupported layout"
        )
    boot = uuid.UUID(bytes_le=bytes(data)[:16])
    if boot.int == 0:
        raise ValueError("empty Windows boot identity")
    return boot


def host_identity() -> str:
    """Identify a local PID namespace without UUID's per-process random fallback."""
    if sys.platform.startswith("linux"):
        try:
            boot = uuid.UUID(
                Path("/proc/sys/kernel/random/boot_id")
                .read_text(encoding="ascii")
                .strip()
            )
            if boot.int == 0:
                raise ValueError("empty boot identity")
            namespace = os.stat("/proc/self/ns/pid").st_ino
            if namespace <= 0:
                raise ValueError("invalid PID namespace")
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Durable ownership requires Linux boot and PID namespace identity"
            ) from exc
        return hashlib.sha256(f"linux:{boot}:{namespace}".encode()).hexdigest()
    if sys.platform == "darwin":
        # The kernel boot session is shared across processes and independent of
        # network interfaces. Never cache a failed probe or use UUID random fallback.
        try:
            result = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
                capture_output=True,
                text=True,
                encoding="ascii",
                check=True,
                timeout=2,
            )
            boot = uuid.UUID(result.stdout.strip())
            if boot.int == 0:
                raise ValueError("empty boot identity")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                "Durable ownership requires macOS kernel boot identity"
            ) from exc
        return "v2:darwin:" + hashlib.sha256(str(boot).encode()).hexdigest()
    if sys.platform == "win32":
        try:
            boot = _windows_boot_uuid()
        except (OSError, ValueError, AttributeError) as exc:
            raise RuntimeError(
                "Durable ownership requires Windows kernel boot identity; the native capability is unavailable"
            ) from exc
        return "v2:win32:" + hashlib.sha256(str(boot).encode()).hexdigest()
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

    if (
        not host
        or type(pid) is not int
        or pid <= 0
        or isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(started)
        or started <= 0
    ):
        return False
    if host != host_identity():
        return False
    try:
        return psutil.Process(pid).create_time() != started
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, OSError):
        return False
