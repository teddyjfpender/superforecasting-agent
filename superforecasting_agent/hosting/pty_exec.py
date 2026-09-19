"""Fresh-interpreter POSIX terminal setup; invoked by pty_spawn, never imported for effects."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import signal
import sys
import termios


def main() -> None:
    # Descriptor 3 reports setup/exec errors and closes atomically on successful exec.
    os.set_inheritable(3, False)
    try:
        # This interpreter has no application threads or allocations to inherit.
        # Close all unrelated inheritable descriptors before launching user code.
        for entry in os.listdir("/dev/fd"):
            fd = int(entry)
            if fd > 3:
                try:
                    os.close(fd)
                except OSError as exc:
                    if exc.errno != errno.EBADF:
                        raise
        cwd, *argv = sys.argv[1:]
        if not argv:
            raise OSError(errno.EINVAL, "PTY command is empty")
        if cwd:
            os.chdir(cwd)
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        os.write(3, b"ready\n")
        os.execvpe(argv[0], argv, os.environ)
    except OSError as exc:
        payload = json.dumps({
            "errno": exc.errno or errno.EIO,
            "filename": exc.filename,
        }).encode()
        os.write(3, payload[:4096])
        os._exit(1)


if __name__ == "__main__":
    main()
