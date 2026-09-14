"""Detect Linux cross-VM mounts before admitting SQLite shared-memory journaling."""

import os
import re
import sys
from pathlib import Path

_CROSS_VM_TYPES = frozenset({
    "virtiofs",
    "fuse.virtiofs",
    "9p",
    "9p2000",
    "9p2000.l",
    "9p2000.u",
})


def filesystem_type(directory: str, mountinfo: str) -> str:
    """Select the longest containing mount, including procfs octal escapes."""
    best = ""
    result = ""
    for line in mountinfo.splitlines():
        fields, separator, suffix = line.partition(" - ")
        columns = fields.split()
        kinds = suffix.split()
        if not separator or len(columns) < 5 or not kinds:
            continue
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), columns[4])
        if directory == mount or directory.startswith(mount.rstrip("/") + "/"):
            if len(mount) > len(best):
                best, result = mount, kinds[0].lower()
    return result


def cross_vm_filesystem(database: str) -> bool:
    """No cache: mounts can change while a long-running gateway remains alive."""
    if sys.platform != "linux" or not database:
        return False
    try:
        directory = os.path.dirname(os.path.realpath(database))
        mounts = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8", errors="replace"
        )
    except (OSError, ValueError):
        return (
            False  # Unknown platforms/filesystems retain the existing reactive check.
        )
    return filesystem_type(directory, mounts) in _CROSS_VM_TYPES
