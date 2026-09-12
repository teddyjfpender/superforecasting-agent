"""Gateway RPCs for the command / CLI-exec family — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``commands.catalog`` (the slash-command
catalog), ``cli.exec`` (guarded shell-through), ``command.resolve`` and the large
``command.dispatch`` router moved here VERBATIM, along with the two helpers used
only by them (``_cli_exec_blocked`` / ``_resolve_name``). The local
``rpc_validated`` / ``method`` decorators capture handlers into ``_REGISTRARS``;
``server.py`` calls :func:`register` (at load AND on ``importlib.reload`` — the
pm_rpc/jobs_rpc sibling contract), replaying them through the REAL
``server.rpc_validated`` / ``server.method`` so registration lands in the same
``tui_gateway.server._methods`` dispatch dict — wire byte-identical.

The monkeypatched ``_load_cfg`` and the mutable ``_sessions`` registry are reached
via the ``_core.`` call-time hop. ``_TUI_EXTRA`` / ``_TUI_HIDDEN`` (catalog
constants) and ``_ok`` / ``_err`` are not patched — imported bare from core.
"""
from __future__ import annotations

import os
import subprocess
import sys

from superforecasting_agent.configuration.goals import configured_goal_turn_budget

import tui_gateway.server as _core
from tui_gateway.server import _TUI_EXTRA, _TUI_HIDDEN, _err, _ok

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def method(name: str):
    def _dec(fn):
        _REGISTRARS.append(("method", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved command/cli.exec handler into ``server._methods``."""
    global _core, _ok, _err, _TUI_EXTRA, _TUI_HIDDEN
    _core = server
    _ok = server._ok
    _err = server._err
    _TUI_EXTRA = server._TUI_EXTRA
    _TUI_HIDDEN = server._TUI_HIDDEN
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]
@rpc_validated("commands.catalog")
def _(rid, params: dict) -> dict:
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
            if cmd.name in _TUI_HIDDEN or cmd.gateway_only:
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

        for name, desc, cat in _TUI_EXTRA:
            all_pairs.append([name, desc])
            if cat not in cat_map:
                cat_map[cat] = []
                cat_order.append(cat)
            cat_map[cat].append([name, desc])

        warning = ""
        try:
            qcmds = _core._load_cfg().get("quick_commands", {}) or {}
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
                pair = [key, description[:120] + ("…" if len(description) > 120 else "")]
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
        return _ok(
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
        return _err(rid, 5020, str(e))


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


@method("cli.exec")
def _(rid, params: dict) -> dict:
    """Run `python -m superforecasting_agent.runtime.main` with argv; capture stdout/stderr (non-interactive only)."""
    argv = params.get("argv", [])
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        return _err(rid, 4003, "argv must be list[str]")
    hint = _cli_exec_blocked(argv)
    if hint:
        return _ok(rid, {"blocked": True, "hint": hint, "code": -1, "output": ""})
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
        return _ok(
            rid, {"blocked": False, "code": r.returncode, "output": out[:48_000]}
        )
    except subprocess.TimeoutExpired:
        return _err(rid, 5016, "cli.exec: timeout")
    except Exception as e:
        return _err(rid, 5017, str(e))


@method("command.resolve")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.application.command_catalog import resolve_command

        r = resolve_command(params.get("name", ""))
        if r:
            return _ok(
                rid,
                {
                    "canonical": r.name,
                    "description": r.description,
                    "category": r.category,
                },
            )
        return _err(rid, 4011, f"unknown command: {params.get('name')}")
    except Exception as e:
        return _err(rid, 5012, str(e))


def _resolve_name(name: str) -> str:
    try:
        from superforecasting_agent.application.command_catalog import resolve_command

        r = resolve_command(name)
        return r.name if r else name
    except Exception:
        return name


@method("command.dispatch")
def _(rid, params: dict) -> dict:
    name, arg = params.get("name", "").lstrip("/"), params.get("arg", "")
    resolved = _resolve_name(name)
    if resolved != name:
        name = resolved
    session = _core._host.sessions.get(params.get("session_id", ""))

    from superforecasting_agent.application.command_catalog import configured_command, expand_quick_alias, resolve_command

    qcmds = _core._load_cfg().get("quick_commands", {})
    try:
        qc = configured_command(name, qcmds)
        if qc is not None and qc["type"] == "alias":
            # The client appends the invocation's original arguments once.
            target = expand_quick_alias(f"/{name}", qcmds)
            return _ok(rid, {"type": "alias", "target": target.lstrip("/")})
    except ValueError as exc:
        return _err(rid, 4018, str(exc))
    if qc is not None:
        if qc.get("type") == "exec":
            from superforecasting_agent.runtime.quick_commands import execute_sync

            result = execute_sync(qc["command"])
            if result.error:
                return _err(rid, 4018, result.error)
            return _ok(rid, {"type": "exec", "output": result.message})

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
                return _err(rid, 5030, f"Plugin command error: {exc}")
            return _ok(rid, {"type": "plugin", "output": str(result or "")})
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
                f"/{name}", arg, task_id=session.get("session_key", "") if session else ""
            )
            if result is None:
                return _err(rid, 4018, f"Failed to load bundle for /{name}")
            message, loaded, missing = result
            notice = f"Loading bundle: {bundle['name']} ({len(loaded)} skills)"
            if missing:
                notice += f"\nSkipped missing skills: {', '.join(missing)}"
            return _ok(rid, {"type": "send", "notice": notice, "message": message})
        except Exception as exc:
            return _err(rid, 5030, f"Bundle command error: {exc}")

    try:
        from agent.skill_commands import (
            scan_skill_commands,
            build_skill_invocation_message,
        )

        cmds = scan_skill_commands()
        key = f"/{name}"
        if key in cmds:
            try:
                msg = build_skill_invocation_message(
                    key, arg, task_id=session.get("session_key", "") if session else ""
                )
            except Exception as exc:
                return _err(rid, 5030, f"Skill command error: {exc}")
            if not msg:
                return _err(rid, 4018, f"skill payload missing message: {key}")
            if msg:
                return _ok(
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
            return _err(rid, 4001, "session not found")
        try:
            return _ok(rid, {"type": "exec", "output": _core._background_command_output(session, name)})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except Exception as exc:
            return _err(rid, 5030, f"Background command failed: {exc}")

    if name == "config":
        from superforecasting_agent.application.configuration_view import configuration_text

        result = _core._methods["config.show"](rid, params)
        if "error" in result:
            return result
        return _ok(rid, {"type": "exec", "output": configuration_text(result["result"]["sections"])})

    if name == "curator":
        from superforecasting_agent.runtime.curator import command_output

        def confirm(question):
            if session is None:
                raise ValueError("Curator confirmation requires an active session")
            return _core._block(
                "clarify.request", params.get("session_id", ""),
                {"question": question, "choices": ["No", "Yes"]},
            )

        try:
            code, output = command_output(arg, confirm=confirm, workers=_core._host.workers)
            if code:
                return _err(rid, 5017, output or "Curator command failed")
            return _ok(rid, {"type": "exec", "output": output})
        except Exception as exc:
            return _err(rid, 5017, f"Curator command failed: {exc}")

    if name == "cron":
        from superforecasting_agent.runtime.cron_commands import cron_command_output

        try:
            return _ok(rid, {"type": "exec", "output": cron_command_output(arg)})
        except Exception as exc:
            return _err(rid, 5017, f"Scheduled task command failed: {exc}")

    if name == "platforms":
        from superforecasting_agent.runtime.platform_commands import platform_configuration_lines

        try:
            return _ok(rid, {"type": "exec", "output": "\n".join(platform_configuration_lines(arg))})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except Exception as exc:
            return _err(rid, 5017, f"Platform configuration unavailable: {exc}")

    if name == "gquota":
        from superforecasting_agent.runtime.quota_commands import google_quota_lines

        try:
            return _ok(rid, {"type": "exec", "output": "\n".join(google_quota_lines(arg))})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except Exception as exc:
            return _err(rid, 5017, str(exc))

    if name == "codex-runtime":
        from superforecasting_agent.runtime import codex_runtime_switch

        value, errors = codex_runtime_switch.parse_args(arg)
        if errors:
            return _err(rid, 4004, "\n".join(errors))
        try:
            config = _core._load_cfg()
            if _core._host.configuration.last_error:
                return _err(rid, 5017, _core._host.configuration.last_error)
            result = codex_runtime_switch.apply(
                config, value,
                persist_callback=_core._save_cfg if value is not None else None,
            )
            if not result.success:
                return _err(rid, 5017, result.message)
            return _ok(rid, {"type": "exec", "output": result.message})
        except Exception as exc:
            return _err(rid, 5017, str(exc))

    if name == "insights":
        from superforecasting_agent.application.insights import parse_insights_arguments

        try:
            query = parse_insights_arguments(arg)
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        database = _core._get_db()
        if database is None:
            return _core._db_unavailable_error(rid, code=5017)
        try:
            from agent.insights import InsightsEngine

            engine = InsightsEngine(database)
            report = engine.generate(days=query.days, source=query.source)
            return _ok(rid, {"type": "exec", "output": engine.format_terminal(report)})
        except Exception as exc:
            return _err(rid, 5017, str(exc))

    if name == "profile":
        from superforecasting_agent.constants import display_agent_home, get_active_profile_name

        output = f"Profile: {get_active_profile_name()}\nHome:    {display_agent_home()}"
        return _ok(rid, {"type": "exec", "output": output})

    if name == "bundles":
        try:
            from agent.skill_bundles import list_bundles, _bundles_dir

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
                    description = bundle.get("description") or f"Load {len(skills)} skills"
                    lines.append(f"/{bundle['slug']} — {description} ({len(skills)} skills)")
                    lines.extend(f"    · {skill}" for skill in skills)
                lines.extend(["", "Invoke a bundle with /<slug>. Manage with `superforecasting-agent bundles`."])
                output = "\n".join(lines)
            return _ok(rid, {"type": "exec", "output": output})
        except Exception as exc:
            return _err(rid, 5030, f"Bundle subsystem unavailable: {exc}")

    if name == "toolsets":
        from superforecasting_agent.tooling.inventory import toolset_inventory, session_toolset_selection

        try:
            selection = session_toolset_selection(
                _core._host.sessions.get(params.get("session_id", "")),
                _core._load_enabled_toolsets,
            )
            items = toolset_inventory(selection, include_legacy=False)
            lines = ["Forecast Desk Toolsets", ""]
            for item in items:
                marker = "(*)" if item["enabled"] else "   "
                lines.append(f"{marker} {item['name']} [{item['tool_count']} tools] - {item['description']}")
            lines.extend(["", "(*) = currently enabled"])
            return _ok(rid, {"type": "exec", "output": "\n".join(lines)})
        except Exception as exc:
            return _err(rid, 5032, str(exc))

    if name == "plugins":
        from superforecasting_agent.runtime.plugin_commands import describe_plugins

        try:
            return _ok(rid, {"type": "exec", "output": describe_plugins()})
        except Exception as exc:
            return _err(rid, 5030, f"Plugin system error: {exc}")

    # ── Commands that queue messages onto _pending_input in the CLI ───
    # In the TUI the slash worker subprocess has no reader for that queue,
    # so we handle them here and return a structured payload.

    if name in {"queue", "q"}:
        if not arg:
            return _err(rid, 4004, "usage: /queue <forecast note>")
        return _ok(rid, {"type": "send", "message": arg})

    if name == "learn":
        # Open-ended: build the standards-guided prompt and submit it as a
        # normal agent turn. The live agent gathers whatever the user
        # described (dirs, URLs, this conversation, pasted text) with its own
        # tools and authors the skill via skill_manage. Works on any backend.
        from agent.learn_prompt import build_learn_prompt

        return _ok(rid, {"type": "send", "message": build_learn_prompt(arg)})

    if name == "retry":
        if not session:
            return _err(rid, 4001, "no active forecast session to retry")
        from superforecasting_agent.application.retry import prepare_retry, RetryUnavailable

        with session["history_lock"]:
            if session.get("running"):
                return _err(rid, 4009, "session busy — /interrupt the current turn before /retry")
            try:
                plan = prepare_retry(session.get("history", []))
            except RetryUnavailable as exc:
                return _err(rid, 4018, str(exc))
            session["history"] = plan.history
            session["history_version"] = int(session.get("history_version", 0)) + 1
        return _ok(rid, {"type": "send", "message": plan.message})

    if name == "steer":
        if not arg:
            return _err(rid, 4004, "usage: /steer <forecast note>")
        agent = session.get("agent") if session else None
        if agent and hasattr(agent, "steer"):
            try:
                accepted = agent.steer(arg)
                if accepted:
                    return _ok(
                        rid,
                        {
                            "type": "exec",
                            "output": f"⏩ Steer queued — arrives after the next tool call: {arg[:80]}{'...' if len(arg) > 80 else ''}",
                        },
                    )
            except Exception:
                pass
        # Fallback: no active run, treat as next-turn message
        return _ok(rid, {"type": "send", "message": arg})

    if name in {"goal", "subgoal"}:
        if not session:
            return _err(rid, 4001, "no active forecast session")
        try:
            from superforecasting_agent.runtime.goals import GoalManager
        except Exception as exc:
            return _err(rid, 5030, f"goals unavailable: {exc}")

        sid_key = session.get("session_key") or ""
        if not sid_key:
            return _err(rid, 4001, "no session key")

        try:
            goals_cfg = _core._load_cfg().get("goals") or {}
            max_turns = configured_goal_turn_budget(goals_cfg)
        except Exception:
            max_turns = configured_goal_turn_budget(None)
        mgr = GoalManager(session_id=sid_key, default_max_turns=max_turns, database_provider=_core._get_db)
        if name == "subgoal":
            from superforecasting_agent.application.goals import execute_subgoal

            return _ok(rid, {"type": "exec", "output": execute_subgoal(mgr, arg)})


        from superforecasting_agent.application.goals import execute_goal

        try:
            result = execute_goal(mgr, arg)
        except ValueError as exc:
            return _err(rid, 4004, f"invalid goal: {exc}")
        state = result.state
        if result.action == "status":
            return _ok(rid, {"type": "exec", "output": result.status})
        if result.action == "pause":
            out = "No goal set." if state is None else f"⏸ Goal paused: {state.goal}"
            return _ok(rid, {"type": "exec", "output": out})
        if result.action == "resume":
            if state is None:
                return _ok(rid, {"type": "exec", "output": "No goal to resume."})
            return _ok(
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
            return _ok(
                rid,
                {
                    "type": "exec",
                    "output": "✓ Goal cleared." if result.had_goal else "No active goal.",
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
        return _ok(
            rid,
            {"type": "send", "notice": notice, "message": state.goal},
        )

    if name == "snapshot":
        from superforecasting_agent.application.snapshots import execute_snapshot

        try:
            return _ok(rid, {"type": "exec", "output": execute_snapshot(arg, allow_restore=False)})
        except ValueError as exc:
            return _err(rid, 4004, str(exc))
        except OSError as exc:
            return _err(rid, 5017, str(exc))

    from superforecasting_agent.application.command_catalog import resolve_command

    if resolve_command(name) is None:
        return _err(rid, 4011, f"unknown command: {name}")
    return _core._command_handoff(rid, f"not a quick/plugin/skill command: {name}", dispatch="slash.exec")
