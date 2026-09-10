"""Interactive browser connection commands backed by native CDP helpers."""

import os
import time
from urllib.parse import urlparse

from .browser_connect import (
    DEFAULT_BROWSER_CDP_URL,
    is_browser_debug_ready,
    manual_chrome_debug_command,
    try_launch_chrome_debug,
)

def _try_launch_chrome_debug(port: int, system: str) -> bool:
    """Try to launch a Chromium-family browser with remote debugging enabled.

        Uses a dedicated user-data-dir so the debug instance doesn't conflict
        with an already-running browser using the default profile.

        Returns True if a launch command was executed (doesn't guarantee success).
        """
    return try_launch_chrome_debug(port, system)


def _handle_browser_command(self, cmd: str):
    """Handle /browser connect|disconnect|status — manage live Chromium-family CDP connection."""
    import platform as _plat

    parts = cmd.strip().split(None, 1)
    sub = parts[1].lower().strip() if len(parts) > 1 else "status"

    _DEFAULT_CDP = DEFAULT_BROWSER_CDP_URL
    current = os.environ.get("BROWSER_CDP_URL", "").strip()

    if sub.startswith("connect"):
        # Optionally accept a custom CDP URL: /browser connect ws://host:port
        connect_parts = cmd.strip().split(None, 2)  # ["/browser", "connect", "ws://..."]
        cdp_url = connect_parts[2].strip() if len(connect_parts) > 2 else _DEFAULT_CDP
        parsed_cdp = urlparse(cdp_url if "://" in cdp_url else f"http://{cdp_url}")
        if parsed_cdp.scheme not in {"http", "https", "ws", "wss"}:
            print()
            print(
                f"   ⚠ Unsupported browser url scheme: {parsed_cdp.scheme or '(missing)'} "
                "(expected one of: http, https, ws, wss)"
            )
            print()
            return
        try:
            _port = parsed_cdp.port or (443 if parsed_cdp.scheme in {"https", "wss"} else 80)
        except ValueError:
            print()
            print(f"   ⚠ Invalid port in browser url: {cdp_url}")
            print()
            return
        if not parsed_cdp.hostname:
            print()
            print(f"   ⚠ Missing host in browser url: {cdp_url}")
            print()
            return
        _host = parsed_cdp.hostname
        if parsed_cdp.path.startswith("/devtools/browser/"):
            cdp_url = parsed_cdp.geturl()
        else:
            cdp_url = parsed_cdp._replace(
                path="",
                params="",
                query="",
                fragment="",
            ).geturl()

        # Clear any existing browser sessions so the next tool call uses the new backend
        try:
            from tools.browser_tool import cleanup_all_browsers
            cleanup_all_browsers()
        except Exception:
            pass

        print()

        # Check if a Chromium-family browser is already serving CDP on the debug port
        _already_open = is_browser_debug_ready(cdp_url, timeout=1.0)

        if _already_open:
            print(f"   ✓ Chromium-family browser is already listening on port {_port}")
        elif cdp_url == _DEFAULT_CDP:
            # Try to auto-launch a Chromium-family browser with remote debugging
            print("   Chromium-family browser isn't running with remote debugging — attempting to launch...")
            _launched = self._try_launch_chrome_debug(_port, _plat.system())
            if _launched:
                # Wait for the DevTools discovery endpoint to come up
                for _wait in range(10):
                    if is_browser_debug_ready(cdp_url, timeout=1.0):
                        _already_open = True
                        break
                    time.sleep(0.5)
                if _already_open:
                    print(f"   ✓ Chromium-family browser launched and listening on port {_port}")
                else:
                    print(f"   ⚠ Browser launched but port {_port} isn't responding yet")
                    print("     Try again in a few seconds — the debug instance may still be starting")
            else:
                print("   ⚠ Could not auto-launch a Chromium-family browser")
                sys_name = _plat.system()
                chrome_cmd = manual_chrome_debug_command(_port, sys_name)
                if chrome_cmd:
                    print(f"     Launch a Chromium-family browser manually:")
                    print(f"     {chrome_cmd}")
                else:
                    print("     No supported Chromium-family browser executable found in this environment")
        else:
            print(f"   ⚠ Port {_port} is not reachable at {cdp_url}")

        if not _already_open:
            print()
            print("Browser not connected — start a Chromium-family browser with remote debugging and retry /browser connect")
            print()
            return

        os.environ["BROWSER_CDP_URL"] = cdp_url
        # Eagerly start the CDP supervisor so pending_dialogs + frame_tree
        # show up in the next browser_snapshot.  No-op if already started.
        try:
            from tools.browser_tool import _ensure_cdp_supervisor  # type: ignore[import-not-found]
            _ensure_cdp_supervisor("default")
        except Exception:
            pass
        print()
        print("🌐 Browser connected to live Chromium-family browser via CDP")
        print(f"   Endpoint: {cdp_url}")
        print()

        # Inject context message so the model knows this slash command
        # intentionally makes the dev/debug CDP browser available for use.
        if hasattr(self, '_pending_input'):
            self._pending_input.put(
                "[System note: The user invoked /browser connect and connected your browser tools to "
                "a Chromium-family dev/debug browser via Chrome DevTools Protocol. "
                "Your browser_navigate, browser_snapshot, browser_click, and other browser tools now "
                "control that CDP browser. The command itself is a signal that using browser tools for "
                "their current browser-related request is expected; do not wait for separate permission "
                "just because CDP is connected. This is typically a Superforecasting Agent-managed isolated debug "
                "profile, not the user's main everyday browser. It is still user-visible and may contain "
                "pages, logged-in sessions, or cookies in that debug profile, so avoid destructive actions, "
                "closing tabs, or navigating away unless the user's task calls for it.]"
            )

    elif sub == "disconnect":
        if current:
            os.environ.pop("BROWSER_CDP_URL", None)
            try:
                from tools.browser_tool import cleanup_all_browsers, _stop_cdp_supervisor
                _stop_cdp_supervisor("default")
                cleanup_all_browsers()
            except Exception:
                pass
            print()
            print("🌐 Browser disconnected from live Chromium-family browser")
            print("   Browser tools reverted to default mode (local headless or cloud provider)")
            print()

            if hasattr(self, '_pending_input'):
                self._pending_input.put(
                    "[System note: The user has disconnected the browser tools from their live Chromium-family browser. "
                    "Browser tools are back to default mode (headless local browser or cloud provider).]"
                )
        else:
            print()
            print("Browser is not connected to a live Chromium-family browser (already using default mode)")
            print()

    elif sub == "status":
        print()
        if current:
            print("🌐 Browser: connected to live Chromium-family browser via CDP")
            print(f"   Endpoint: {current}")

            _port = 9222
            try:
                _port = int(current.rsplit(":", 1)[-1].split("/")[0])
            except (ValueError, IndexError):
                pass
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(("127.0.0.1", _port))
                s.close()
                print("   Status: ✓ reachable")
            except (OSError, Exception):
                print("   Status: ⚠ not reachable (browser may not be running)")
        else:
            try:
                from tools.browser_tool import _get_cloud_provider
                provider = _get_cloud_provider()
            except Exception:
                provider = None

            if provider is not None:
                print(f"🌐 Browser: {provider.provider_name()} (cloud)")
            else:
                # Show engine info for local mode
                try:
                    from tools.browser_tool import _get_browser_engine
                    engine = _get_browser_engine()
                except Exception:
                    engine = "auto"
                if engine == "lightpanda":
                    print("🌐 Browser: local Lightpanda (agent-browser --engine lightpanda)")
                    print("   ⚡ Lightpanda: faster navigation, no screenshot support")
                    print("   Automatic Chromium fallback for screenshots and failed commands")
                elif engine == "chrome":
                    print("🌐 Browser: local headless Chromium (agent-browser --engine chrome)")
                else:
                    print("🌐 Browser: local headless Chromium (agent-browser)")
        print()
        print("   /browser connect      — connect to your live Chromium-family browser")
        print("   /browser disconnect   — revert to default")
        print()

    else:
        print()
        print("Usage: /browser connect|disconnect|status")
        print()
        print("   connect      Connect browser tools to your live Chromium-family browser session")
        print("   disconnect   Revert to default browser backend")
        print("   status       Show current browser mode")
        print()
