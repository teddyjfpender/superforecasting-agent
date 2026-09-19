"""Command catalog, guarded execution and command dispatch RPC handlers.

Handlers capture an explicit command context when registered. Registering another
host never changes previously registered handlers. The singleton server adapter
retains its existing reload behavior. Validation and reusable operations belong to the application package;
this adapter maps their results and errors to the product protocol.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from superforecasting_agent.configuration.goals import configured_goal_turn_budget
from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.hosting.workers import HostStopping

RpcHandler = Callable[[Any, dict[str, Any]], dict[str, Any]]
Registrar = Callable[[str], Callable[[RpcHandler], RpcHandler]]


class ErrorResponse(Protocol):
    def __call__(self, rid: Any, code: int, message: str) -> dict[str, Any]: ...


class DatabaseError(Protocol):
    def __call__(self, rid: Any, *, code: int) -> dict[str, Any]: ...


class Handoff(Protocol):
    def __call__(
        self, rid: Any, message: str, dispatch: str = ...
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CommandContext:
    """Capabilities owned by one command host; no module-global registration state."""

    host: Callable[[], RuntimeHost]
    load_config: Callable[[], dict[str, Any]]
    save_config: Callable[[dict[str, Any]], None]
    database: Callable[[], Any]
    database_error: DatabaseError
    ok: Callable[[Any, dict[str, Any]], dict[str, Any]]
    error: ErrorResponse
    handoff: Handoff
    block: Callable[[str, str, dict[str, Any]], str]
    background_output: Callable[[dict[str, Any], str], str]
    enabled_toolsets: Callable[[], list[str] | None]
    methods: Mapping[str, RpcHandler]
    extra_commands: Sequence[tuple[str, str, str]]
    hidden_commands: frozenset[str]


def register_handlers(
    context: CommandContext, *, method: Registrar, rpc_validated: Registrar
) -> None:
    def bind(
        handler: Callable[[CommandContext, Any, dict[str, Any]], dict[str, Any]],
    ) -> RpcHandler:
        def invoke(rid: Any, params: dict[str, Any]) -> dict[str, Any]:
            try:
                owner = context.host()
                with owner.workers.operation():
                    # Host replacement during this call cannot move its session
                    # lookup or worker ownership into the replacement lifetime.
                    return handler(replace(context, host=lambda: owner), rid, params)
            except HostStopping:
                return context.error(rid, 5030, "runtime host is stopping")

        return invoke

    rpc_validated("commands.catalog")(bind(command_catalog))
    method("cli.exec")(bind(cli_exec))
    method("command.resolve")(bind(command_resolve))
    method("command.dispatch")(bind(command_dispatch))


def register(server) -> None:
    """Adapt the singleton server without changing any previous registration.

    Resolve legacy server callbacks at call time for its explicit reload lifecycle.
    Independent hosts should pass their own bound capabilities to register_handlers.
    """
    context = CommandContext(
        host=lambda: server._host,
        load_config=lambda: server._load_cfg(),
        save_config=lambda cfg: server._save_cfg(cfg),
        database=lambda: server._get_db(),
        database_error=lambda rid, *, code: server._db_unavailable_error(
            rid, code=code
        ),
        ok=lambda rid, value: server._ok(rid, value),
        error=lambda rid, code, message: server._err(rid, code, message),
        handoff=lambda rid, message, dispatch="command.dispatch": (
            server._command_handoff(rid, message, dispatch=dispatch)
        ),
        block=lambda event, sid, payload: server._block(event, sid, payload),
        background_output=lambda session, name: server._background_command_output(
            session, name
        ),
        enabled_toolsets=lambda: server._load_enabled_toolsets(),
        methods=server._methods,
        extra_commands=tuple(server._TUI_EXTRA),
        hidden_commands=frozenset(server._TUI_HIDDEN),
    )
    register_handlers(context, method=server.method, rpc_validated=server.rpc_validated)


__all__ = ["CommandContext", "register", "register_handlers"]


def command_catalog(
    context: CommandContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Registry-backed slash metadata for the TUI — categorized, no aliases."""
    try:
        from superforecasting_agent.application.command_catalog import (
            COMMAND_REGISTRY,
            SUBCOMMANDS,
            _build_description,
        )

        all_pairs: list[list[str]] = []
        canon: dict[str, str] = {}
        categories: list[dict] = []
        cat_map: dict[str, list[list[str]]] = {}
        cat_order: list[str] = []

        for cmd in COMMAND_REGISTRY:
            if cmd.name in context.hidden_commands or cmd.gateway_only:
                continue

            c = f"/{cmd.name}"
            canon[c.lower()] = c
            for a in cmd.aliases:
                canon[f"/{a}".lower()] = c

            desc = _build_description(cmd)
            all_pairs.append([c, desc])

            cat = cmd.category
            if cat not in cat_map:
                cat_map[cat] = []
                cat_order.append(cat)
            cat_map[cat].append([c, desc])

        for name, desc, cat in context.extra_commands:
            all_pairs.append([name, desc])
            if cat not in cat_map:
                cat_map[cat] = []
                cat_order.append(cat)
            cat_map[cat].append([name, desc])

        warning = ""
        try:
            qcmds = context.load_config().get("quick_commands", {}) or {}
            if isinstance(qcmds, dict) and qcmds:
                bucket = "User commands"
                if bucket not in cat_map:
                    cat_map[bucket] = []
                    cat_order.append(bucket)
                for qname, qc in sorted(qcmds.items()):
                    if not isinstance(qc, dict):
                        continue
                    key = f"/{qname}"
                    canon[key.lower()] = key
                    qtype = qc.get("type", "")
                    if qtype == "exec":
                        default_desc = f"exec: {qc.get('command', '')}"
                    elif qtype == "alias":
                        default_desc = f"alias → {qc.get('target', '')}"
                    else:
                        default_desc = qtype or "quick command"
                    qdesc = str(qc.get("description") or default_desc)
                    qdesc = qdesc[:120] + ("…" if len(qdesc) > 120 else "")
                    all_pairs.append([key, qdesc])
                    cat_map[bucket].append([key, qdesc])
        except Exception as e:
            if not warning:
                warning = f"quick_commands discovery unavailable: {e}"

        bundle_keys = set()
        try:
            from agent.skill_bundles import get_skill_bundles

            for key, info in sorted(get_skill_bundles().items()):
                if key.lower() in canon:
                    continue
                description = str(info.get("description") or "Load a skill bundle")
                pair = [
                    key,
                    description[:120] + ("…" if len(description) > 120 else ""),
                ]
                all_pairs.append(pair)
                canon[key.lower()] = key
                bundle_keys.add(key)
                if "Skill bundles" not in cat_map:
                    cat_map["Skill bundles"] = []
                    cat_order.append("Skill bundles")
                cat_map["Skill bundles"].append(pair)
        except Exception as exc:
            warning = warning or f"bundle discovery unavailable: {exc}"

        skill_count = 0
        try:
            from agent.skill_commands import scan_skill_commands

            for k, info in sorted(scan_skill_commands().items()):
                if k in bundle_keys:
                    continue
                d = str(info.get("description", "Skill"))
                all_pairs.append([k, d[:120] + ("…" if len(d) > 120 else "")])
                skill_count += 1
        except Exception as e:
            warning = f"skill discovery unavailable: {e}"

        for cat in cat_order:
            categories.append({"name": cat, "pairs": cat_map[cat]})

        sub = {k: v[:] for k, v in SUBCOMMANDS.items()}
        return context.ok(
            rid,
            {
                "pairs": all_pairs,
                "sub": sub,
                "canon": canon,
                "categories": categories,
                "skill_count": skill_count,
                "warning": warning,
            },
        )
    except Exception as e:
        return context.error(rid, 5020, str(e))


def _cli_exec_blocked(argv: list[str]) -> str | None:
    """Return user hint if this argv must not run headless in the gateway process."""
    if not argv:
        return "bare `superforecasting-agent` is interactive — use `/forecast` commands here, or run `superforecasting-agent -z …` in another terminal"
    a0 = argv[0].lower()
    if a0 == "setup":
        return "`superforecasting-agent setup` needs a full terminal — run it outside the TUI"
    if a0 == "gateway":
        return "`superforecasting-agent gateway` is long-running — run it in another terminal"
    if a0 == "sessions" and len(argv) > 1 and argv[1].lower() == "browse":
        return "`superforecasting-agent sessions browse` is interactive — use /resume here, or run browse in another terminal"
    if a0 == "config" and len(argv) > 1 and argv[1].lower() == "edit":
        return "`superforecasting-agent config edit` needs $EDITOR in a real terminal"
    return None


def cli_exec(
    context: CommandContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Run `python -m superforecasting_agent.runtime.main` with argv; capture stdout/stderr (non-interactive only)."""
    argv = params.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        return context.error(rid, 4003, "argv must be list[str]")
    hint = _cli_exec_blocked(argv)
    if hint:
        return context.ok(
            rid, {"blocked": True, "hint": hint, "code": -1, "output": ""}
        )
    try:
        r = subprocess.run(
            [sys.executable, "-m", "superforecasting_agent.runtime.main", *argv],
            capture_output=True,
            text=True,
            timeout=min(int(params.get("timeout", 240)), 600),
            cwd=os.getcwd(),
            env=os.environ.copy(),
        )
        parts = [r.stdout or "", r.stderr or ""]
        out = "\n".join(p for p in parts if p).strip() or "(no output)"
        return context.ok(
            rid, {"blocked": False, "code": r.returncode, "output": out[:48_000]}
        )
    except subprocess.TimeoutExpired:
        return context.error(rid, 5016, "cli.exec: timeout")
    except Exception as e:
        return context.error(rid, 5017, str(e))


def command_resolve(
    context: CommandContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from superforecasting_agent.application.command_catalog import resolve_command

        r = resolve_command(params.get("name", ""))
        if r:
            return context.ok(
                rid,
                {
                    "canonical": r.name,
                    "description": r.description,
                    "category": r.category,
                },
            )
        return context.error(rid, 4011, f"unknown command: {params.get('name')}")
    except Exception as e:
        return context.error(rid, 5012, str(e))


def _resolve_name(name: str) -> str:
    try:
        from superforecasting_agent.application.command_catalog import resolve_command

        r = resolve_command(name)
        return r.name if r else name
    except Exception:
        return name


def command_dispatch(
    context: CommandContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    from superforecasting_agent.application.command_input import command_fields

    try:
        invocation = command_fields(params.get("name", ""), params.get("arg", ""))
    except ValueError as exc:
        return context.error(rid, 4004, str(exc))
    name, arg = invocation.name, invocation.arguments
    resolved = _resolve_name(name)
    if resolved != name:
        name = resolved
    session = context.host().sessions.get(params.get("session_id", ""))

    from superforecasting_agent.application.command_catalog import (
        configured_command,
        expand_quick_alias,
        resolve_command,
    )

    qcmds = context.load_config().get("quick_commands", {})
    try:
        qc = configured_command(name, qcmds)
        if qc is not None and qc["type"] == "alias":
            # The client appends the invocation's original arguments once.
            target = expand_quick_alias(f"/{name}", qcmds)
            return context.ok(rid, {"type": "alias", "target": target.lstrip("/")})
    except ValueError as exc:
        return context.error(rid, 4018, str(exc))
    if qc is not None:
        if qc.get("type") == "exec":
            from superforecasting_agent.runtime.quick_commands import execute_sync

            result = execute_sync(qc["command"])
            if result.error:
                return context.error(rid, 4018, result.error)
            return context.ok(rid, {"type": "exec", "output": result.message})

    try:
        from superforecasting_agent.runtime.plugins import (
            get_plugin_command_handler,
            resolve_plugin_command_result,
        )

        handler = None if resolve_command(name) else get_plugin_command_handler(name)
        if handler:
            try:
                result = resolve_plugin_command_result(handler(arg))
            except Exception as exc:
                return context.error(rid, 5030, f"Plugin command error: {exc}")
            return context.ok(rid, {"type": "plugin", "output": str(result or "")})
    except Exception:
        pass

    try:
        from agent.skill_bundles import get_skill_bundles
        from superforecasting_agent.application.command_catalog import resolve_command

        bundle = None if resolve_command(name) else get_skill_bundles().get(f"/{name}")
    except Exception:
        bundle = None
    if bundle is not None:
        from agent.skill_bundles import build_bundle_invocation_message

        try:
            result = build_bundle_invocation_message(
                f"/{name}",
                arg,
                task_id=session.get("session_key", "") if session else "",
            )
            if result is None:
                return context.error(rid, 4018, f"Failed to load bundle for /{name}")
            message, loaded, missing = result
            notice = f"Loading bundle: {bundle['name']} ({len(loaded)} skills)"
            if missing:
                notice += f"\nSkipped missing skills: {', '.join(missing)}"
            return context.ok(
                rid, {"type": "send", "notice": notice, "message": message}
            )
        except Exception as exc:
            return context.error(rid, 5030, f"Bundle command error: {exc}")

    try:
        from agent.skill_commands import (
            build_skill_invocation_message,
            scan_skill_commands,
        )

        cmds = scan_skill_commands()
        key = f"/{name}"
        if key in cmds:
            try:
                msg = build_skill_invocation_message(
                    key, arg, task_id=session.get("session_key", "") if session else ""
                )
            except Exception as exc:
                return context.error(rid, 5030, f"Skill command error: {exc}")
            if not msg:
                return context.error(rid, 4018, f"skill payload missing message: {key}")
            if msg:
                return context.ok(
                    rid,
                    {
                        "type": "skill",
                        "message": msg,
                        "name": cmds[key].get("name", name),
                    },
                )
    except Exception:
        pass

    if name in {"agents", "stop"}:
        if session is None:
            return context.error(rid, 4001, "session not found")
        try:
            return context.ok(
                rid,
                {
                    "type": "exec",
                    "output": context.background_output(session, name),
                },
            )
        except ValueError as exc:
            return context.error(rid, 4004, str(exc))
        except Exception as exc:
            return context.error(rid, 5030, f"Background command failed: {exc}")

    if name == "config":
        from superforecasting_agent.application.configuration_view import (
            configuration_text,
        )

        result = context.methods["config.show"](
            rid, {"session_id": params.get("session_id")}
        )
        if "error" in result:
            return result
        return context.ok(
            rid,
            {
                "type": "exec",
                "output": configuration_text(result["result"]["sections"]),
            },
        )

    if name == "curator":
        from superforecasting_agent.runtime.curator import command_output

        def confirm(question):
            if session is None:
                raise ValueError("Curator confirmation requires an active session")
            return context.block(
                "clarify.request",
                params.get("session_id", ""),
                {"question": question, "choices": ["No", "Yes"]},
            )

        try:
            code, output = command_output(
                arg, confirm=confirm, workers=context.host().workers
            )
            if code:
                return context.error(rid, 5017, output or "Curator command failed")
            return context.ok(rid, {"type": "exec", "output": output})
        except Exception as exc:
            return context.error(rid, 5017, f"Curator command failed: {exc}")

    if name == "cron":
        from superforecasting_agent.runtime.cron_commands import cron_command_output

        try:
            return context.ok(rid, {"type": "exec", "output": cron_command_output(arg)})
        except Exception as exc:
            return context.error(rid, 5017, f"Scheduled task command failed: {exc}")

    if name == "platforms":
        from superforecasting_agent.runtime.platform_commands import (
            platform_configuration_lines,
        )

        try:
            return context.ok(
                rid,
                {
                    "type": "exec",
                    "output": "\n".join(platform_configuration_lines(arg)),
                },
            )
        except ValueError as exc:
            return context.error(rid, 4004, str(exc))
        except Exception as exc:
            return context.error(
                rid, 5017, f"Platform configuration unavailable: {exc}"
            )

    if name == "gquota":
        from superforecasting_agent.runtime.quota_commands import google_quota_lines

        try:
            return context.ok(
                rid, {"type": "exec", "output": "\n".join(google_quota_lines(arg))}
            )
        except ValueError as exc:
            return context.error(rid, 4004, str(exc))
        except Exception as exc:
            return context.error(rid, 5017, str(exc))

    if name == "codex-runtime":
        from superforecasting_agent.runtime import codex_runtime_switch

        value, errors = codex_runtime_switch.parse_args(arg)
        if errors:
            return context.error(rid, 4004, "\n".join(errors))
        try:
            config = context.load_config()
            config_error = context.host().configuration.last_error
            if config_error:
                return context.error(rid, 5017, config_error)
            result = codex_runtime_switch.apply(
                config,
                value,
                persist_callback=context.save_config if value is not None else None,
            )
            if not result.success:
                return context.error(rid, 5017, result.message)
            return context.ok(rid, {"type": "exec", "output": result.message})
        except Exception as exc:
            return context.error(rid, 5017, str(exc))

    if name == "insights":
        from superforecasting_agent.application.insights import parse_insights_arguments

        try:
            query = parse_insights_arguments(arg)
        except ValueError as exc:
            return context.error(rid, 4004, str(exc))
        database = context.database()
        if database is None:
            return context.database_error(rid, code=5017)
        try:
            from agent.insights import InsightsEngine

            engine = InsightsEngine(database)
            report = engine.generate(days=query.days, source=query.source)
            return context.ok(
                rid, {"type": "exec", "output": engine.format_terminal(report)}
            )
        except Exception as exc:
            return context.error(rid, 5017, str(exc))

    if name == "profile":
        from superforecasting_agent.constants import (
            display_agent_home,
            get_active_profile_name,
        )

        output = (
            f"Profile: {get_active_profile_name()}\nHome:    {display_agent_home()}"
        )
        return context.ok(rid, {"type": "exec", "output": output})

    if name == "bundles":
        try:
            from agent.skill_bundles import _bundles_dir, list_bundles

            bundles = list_bundles()
            if not bundles:
                output = (
                    "No skill bundles installed.\n"
                    "Create one with: superforecasting-agent bundles create <name> --skill <s1> --skill <s2>\n"
                    f"Directory: {_bundles_dir()}"
                )
            else:
                lines = [f"Optional Skill Bundles ({len(bundles)} installed):", ""]
                for bundle in bundles:
                    skills = bundle.get("skills", [])
                    description = (
                        bundle.get("description") or f"Load {len(skills)} skills"
                    )
                    lines.append(
                        f"/{bundle['slug']} — {description} ({len(skills)} skills)"
                    )
                    lines.extend(f"    · {skill}" for skill in skills)
                lines.extend([
                    "",
                    "Invoke a bundle with /<slug>. Manage with `superforecasting-agent bundles`.",
                ])
                output = "\n".join(lines)
            return context.ok(rid, {"type": "exec", "output": output})
        except Exception as exc:
            return context.error(rid, 5030, f"Bundle subsystem unavailable: {exc}")

    if name == "toolsets":
        from superforecasting_agent.tooling.inventory import (
            session_toolset_selection,
            toolset_inventory,
        )

        try:
            selection = session_toolset_selection(
                context.host().sessions.get(params.get("session_id", "")),
                context.enabled_toolsets,
            )
            items = toolset_inventory(selection, include_legacy=False)
            lines = ["Forecast Desk Toolsets", ""]
            for item in items:
                marker = "(*)" if item["enabled"] else "   "
                lines.append(
                    f"{marker} {item['name']} [{item['tool_count']} tools] - {item['description']}"
                )
            lines.extend(["", "(*) = currently enabled"])
            return context.ok(rid, {"type": "exec", "output": "\n".join(lines)})
        except Exception as exc:
            return context.error(rid, 5032, str(exc))

    if name == "plugins":
        from superforecasting_agent.runtime.plugin_commands import describe_plugins

        try:
            return context.ok(rid, {"type": "exec", "output": describe_plugins()})
        except Exception as exc:
            return context.error(rid, 5030, f"Plugin system error: {exc}")

    # ── Commands that queue messages onto _pending_input in the CLI ───
    # In the TUI the slash worker subprocess has no reader for that queue,
    # so we handle them here and return a structured payload.

    if name in {"queue", "q"}:
        if not arg:
            return context.error(rid, 4004, "usage: /queue <forecast note>")
        return context.ok(rid, {"type": "send", "message": arg})

    if name == "learn":
        # Open-ended: build the standards-guided prompt and submit it as a
        # normal agent turn. The live agent gathers whatever the user
        # described (dirs, URLs, this conversation, pasted text) with its own
        # tools and authors the skill via skill_manage. Works on any backend.
        from agent.learn_prompt import build_learn_prompt

        return context.ok(rid, {"type": "send", "message": build_learn_prompt(arg)})

    if name == "retry":
        if not session:
            return context.error(rid, 4001, "no active forecast session to retry")
        from superforecasting_agent.application.retry import (
            RetryUnavailable,
            prepare_retry,
        )

        with session["history_lock"]:
            if session.get("running"):
                return context.error(
                    rid,
                    4009,
                    "session busy — /interrupt the current turn before /retry",
                )
            try:
                plan = prepare_retry(session.get("history", []))
            except RetryUnavailable as exc:
                return context.error(rid, 4018, str(exc))
            session["history"] = plan.history
            session["history_version"] = int(session.get("history_version", 0)) + 1
        return context.ok(rid, {"type": "send", "message": plan.message})

    if name == "steer":
        if not arg:
            return context.error(rid, 4004, "usage: /steer <forecast note>")
        agent = session.get("agent") if session else None
        if agent and hasattr(agent, "steer"):
            try:
                accepted = agent.steer(arg)
                if accepted:
                    return context.ok(
                        rid,
                        {
                            "type": "exec",
                            "output": f"⏩ Steer queued — arrives after the next tool call: {arg[:80]}{'...' if len(arg) > 80 else ''}",
                        },
                    )
            except Exception:
                pass
        # Fallback: no active run, treat as next-turn message
        return context.ok(rid, {"type": "send", "message": arg})

    if name in {"goal", "subgoal"}:
        if not session:
            return context.error(rid, 4001, "no active forecast session")
        try:
            from superforecasting_agent.runtime.goals import GoalManager
        except Exception as exc:
            return context.error(rid, 5030, f"goals unavailable: {exc}")

        sid_key = session.get("session_key") or ""
        if not sid_key:
            return context.error(rid, 4001, "no session key")

        try:
            goals_cfg = context.load_config().get("goals") or {}
            max_turns = configured_goal_turn_budget(goals_cfg)
        except Exception:
            max_turns = configured_goal_turn_budget(None)
        mgr = GoalManager(
            session_id=sid_key,
            default_max_turns=max_turns,
            database_provider=context.database,
        )
        if name == "subgoal":
            from superforecasting_agent.application.goals import execute_subgoal

            return context.ok(
                rid, {"type": "exec", "output": execute_subgoal(mgr, arg)}
            )

        from superforecasting_agent.application.goals import execute_goal

        try:
            result = execute_goal(mgr, arg)
        except ValueError as exc:
            return context.error(rid, 4004, f"invalid goal: {exc}")
        state = result.state
        if result.action == "status":
            return context.ok(rid, {"type": "exec", "output": result.status})
        if result.action == "pause":
            out = "No goal set." if state is None else f"⏸ Goal paused: {state.goal}"
            return context.ok(rid, {"type": "exec", "output": out})
        if result.action == "resume":
            if state is None:
                return context.ok(rid, {"type": "exec", "output": "No goal to resume."})
            return context.ok(
                rid,
                {
                    "type": "exec",
                    "output": (
                        f"▶ Goal resumed: {state.goal}\n"
                        "Send any follow-up to continue, or wait — I'll take the next step on the next turn."
                    ),
                },
            )
        if result.action == "clear":
            return context.ok(
                rid,
                {
                    "type": "exec",
                    "output": "✓ Goal cleared."
                    if result.had_goal
                    else "No active goal.",
                },
            )

        assert state is not None

        notice = (
            f"⊙ Goal set ({state.max_turns}-turn budget): {state.goal}\n"
            "I'll keep working until the goal is done, you pause/clear it, or the budget is exhausted.\n"
            "Controls: /goal status · /goal pause · /goal resume · /goal clear"
        )
        # Send the goal text as the kickoff prompt. The TUI client sees
        # {type: send, notice, message} → renders `notice` as a sys line,
        # then submits `message` as a user turn. The post-turn judge
        # wired in _run_prompt_submit takes over from there.
        return context.ok(
            rid,
            {"type": "send", "notice": notice, "message": state.goal},
        )

    if name == "snapshot":
        from superforecasting_agent.application.snapshots import execute_snapshot

        try:
            return context.ok(
                rid,
                {"type": "exec", "output": execute_snapshot(arg, allow_restore=False)},
            )
        except ValueError as exc:
            return context.error(rid, 4004, str(exc))
        except OSError as exc:
            return context.error(rid, 5017, str(exc))

    from superforecasting_agent.application.command_catalog import resolve_command

    if resolve_command(name) is None:
        return context.error(rid, 4011, f"unknown command: {name}")
    from tui_gateway.command_routes import terminal_command_names

    if name in terminal_command_names():
        return context.ok(rid, {"type": "alias", "target": name})
    return context.handoff(
        rid, f"not a quick/plugin/skill command: {name}", dispatch="slash.exec"
    )
