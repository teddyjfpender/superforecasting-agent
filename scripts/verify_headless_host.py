"""Exercise an installed headless host outside the checkout, including its logs."""

import json
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Origin


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="forecast-remote-host-") as directory:
        root = Path(directory)
        token = root / "host.token"
        token.write_text("isolated-host-verification", encoding="utf-8")
        token.chmod(0o600)
        env = {
            **os.environ,
            "SUPERFORECASTING_AGENT_HOME": str(root / "profile"),
            "SUPERFORECASTING_AGENT_TUI_CRON_TICKER": "0",
        }
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "superforecasting_agent.hosting",
                "--port",
                "0",
                "--token-file",
                str(token),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        stderr = child.stderr
        assert stderr is not None
        lines: queue.Queue[str] = queue.Queue()

        def drain():
            for line in stderr:
                lines.put(line)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        log = []
        try:
            deadline = time.monotonic() + 20
            port = None
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    if child.poll() is not None:
                        raise AssertionError("host exited: " + "".join(log))
                    continue
                log.append(line)
                found = re.search(r"http://127\.0\.0\.1:(\d+)", line)
                if found:
                    port = int(found.group(1))
                    break
            assert port is not None, "".join(log)
            for query, origin in [
                ("rejected-host-token", None),
                ("isolated-host-verification", "https://untrusted.example"),
            ]:
                try:
                    with connect(
                        f"ws://127.0.0.1:{port}/api/ws?token={query}",
                        origin=Origin(origin) if origin else None,
                        open_timeout=10,
                    ):
                        raise AssertionError("unauthorized connection accepted")
                except InvalidStatus as exc:
                    assert exc.response.status_code == 403
            with connect(
                f"ws://127.0.0.1:{port}/api/ws?token=isolated-host-verification",
                open_timeout=10,
            ) as ws:
                ready = json.loads(ws.recv(timeout=10))["params"]["payload"]
                ws.send(
                    json.dumps({
                        "id": 1,
                        "method": "host.negotiate",
                        "params": {
                            "protocol_version": ready["protocol_version"],
                            "required_capabilities": ["forecast.operation"],
                        },
                    })
                )
                reply = json.loads(ws.recv(timeout=10))
                assert "forecast.operation" in reply["result"]["capabilities"], reply
            print(
                "Installed headless host: actual localhost WebSocket negotiation passed"
            )
        finally:
            if child.poll() is None:
                if os.name == "nt":
                    child.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
                raise AssertionError("headless host failed to exit after termination")
            finally:
                reader.join(timeout=1)
                while not lines.empty():
                    log.append(lines.get_nowait())
                stderr.close()
            for credential in ("isolated-host-verification", "rejected-host-token"):
                assert credential not in "".join(log), (
                    "host logged authentication token"
                )
            assert "[redacted]" in "".join(log), "handshake logs were not exercised"
        # Uvicorn re-raises the captured signal after orderly ASGI shutdown.
        # A signal exit alone is insufficient: require the completion marker too.
        assert "Application shutdown complete." in "".join(log), "".join(log)
        expected = (
            (0, 0xC000013A, -1073741510) if os.name == "nt" else (0, -signal.SIGTERM)
        )
        assert child.returncode in expected, "".join(log)
        print(
            "Installed headless host: clean termination and no credential logging passed"
        )


if __name__ == "__main__":
    main()
