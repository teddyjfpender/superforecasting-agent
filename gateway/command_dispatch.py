"""Gateway command-hook protocol and authorization after command rewrites."""
from dataclasses import dataclass
import logging

from superforecasting_agent.runtime.commands import is_gateway_known_command, resolve_command as _resolve_cmd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    command: str
    canonical: str
    intercepted: bool = False
    response: str | None = None


async def dispatch_command_hooks(runner, event, command, canonical):
    source = event.source
    # Fire the ``command:<canonical>`` hook for any recognized slash
    # command — built-in OR plugin-registered. Handlers can return a
    # dict with ``{"decision": "deny" | "handled" | "rewrite", ...}``
    # to intercept dispatch before core handling runs. This replaces
    # the previous fire-and-forget emit(): return values are now
    # honored, but handlers that return nothing behave exactly as
    # before (telemetry-style hooks keep working).
    if command and is_gateway_known_command(canonical):
        raw_args = event.get_command_args().strip()
        hook_ctx = {
            "platform": source.platform.value if source.platform else "",
            "user_id": source.user_id,
            "command": canonical,
            "raw_command": command,
            "args": raw_args,
            "raw_args": raw_args,
        }
        try:
            hook_results = await runner.hooks.emit_collect(
                f"command:{canonical}", hook_ctx
            )
        except Exception as _hook_err:
            logger.debug(
                "command:%s hook dispatch failed (non-fatal): %s",
                canonical, _hook_err,
            )
            hook_results = []

        for hook_result in hook_results:
            if not isinstance(hook_result, dict):
                continue
            decision = str(hook_result.get("decision", "")).strip().lower()
            if not decision or decision == "allow":
                continue
            if decision == "deny":
                message = hook_result.get("message")
                if isinstance(message, str) and message:
                    return DispatchResult(command, canonical, True, message)
                return DispatchResult(command, canonical, True, f"Command `/{command}` was blocked by a hook.")
            if decision == "handled":
                message = hook_result.get("message")
                return DispatchResult(command, canonical, True, message if isinstance(message, str) and message else None)
            if decision == "rewrite":
                new_command = str(
                    hook_result.get("command_name", "")
                ).strip().lstrip("/")
                if not new_command:
                    continue
                new_args = str(hook_result.get("raw_args", "")).strip()
                event.text = f"/{new_command} {new_args}".strip()
                command = event.get_command()
                _cmd_def = _resolve_cmd(command) if command else None
                canonical = _cmd_def.name if _cmd_def else command
                if is_gateway_known_command(canonical):
                    denied = runner._check_slash_access(source, canonical)
                    if denied is not None:
                        return DispatchResult(command, canonical, True, denied)
                break

    return DispatchResult(command, canonical)
