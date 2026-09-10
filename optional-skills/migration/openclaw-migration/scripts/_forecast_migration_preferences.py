"""Agent, session, browser, tool and approval configuration migration."""

from __future__ import annotations

from _forecast_migration_reports import write_config_archive

import json
from typing import Any, Dict, List, Optional

from _forecast_migration_files import load_yaml_file, dump_yaml_file, yaml


def migrate_command_allowlist(self) -> None:
    source = self.source_root / "exec-approvals.json"
    destination = self.target_root / "config.yaml"
    if not source.exists():
        self.record("command-allowlist", None, destination, "skipped", "No OpenClaw exec approvals file found")
        return
    if yaml is None:
        self.record("command-allowlist", source, destination, "error", "PyYAML is not available")
        return

    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        self.record("command-allowlist", source, destination, "error", f"Invalid JSON: {exc}")
        return

    patterns: List[str] = []
    agents = data.get("agents", {})
    if isinstance(agents, dict):
        for agent_data in agents.values():
            allowlist = agent_data.get("allowlist", []) if isinstance(agent_data, dict) else []
            for entry in allowlist:
                pattern = entry.get("pattern") if isinstance(entry, dict) else None
                if pattern:
                    patterns.append(pattern)

    patterns = sorted(dict.fromkeys(patterns))
    if not patterns:
        self.record("command-allowlist", source, destination, "skipped", "No allowlist patterns found")
        return
    if not destination.exists():
        self.record("command-allowlist", source, destination, "skipped", "Superforecasting Agent config.yaml does not exist yet")
        return

    config = load_yaml_file(destination)
    current = config.get("command_allowlist", [])
    if not isinstance(current, list):
        current = []
    merged = sorted(dict.fromkeys(list(current) + patterns))
    added = [pattern for pattern in merged if pattern not in current]
    if not added:
        self.record("command-allowlist", source, destination, "skipped", "All patterns already present")
        return

    if self.execute:
        backup_path = self.maybe_backup(destination)
        config["command_allowlist"] = merged
        dump_yaml_file(destination, config)
        self.record(
            "command-allowlist",
            source,
            destination,
            "migrated",
            backup=str(backup_path) if backup_path else "",
            added_patterns=added,
        )
    else:
        self.record("command-allowlist", source, destination, "migrated", "Would merge patterns", added_patterns=added)


def migrate_agent_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    agents = config.get("agents") or {}
    defaults = agents.get("defaults") or {}
    agent_list = agents.get("list") or []

    if not defaults and not agent_list:
        self.record("agent-config", None, None, "skipped", "No agent configuration found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    changes = False

    # Map agent defaults
    agent_cfg = target_config.get("agent") or {}
    if defaults.get("contextTokens"):
        # No direct mapping but useful context
        pass
    if defaults.get("timeoutSeconds"):
        agent_cfg["max_turns"] = min(defaults["timeoutSeconds"] // 10, 200)
        changes = True
    if defaults.get("verboseDefault"):
        agent_cfg["verbose"] = defaults["verboseDefault"]
        changes = True
    if defaults.get("thinkingDefault"):
        # Map OpenClaw thinking -> Superforecasting Agent reasoning_effort
        thinking = defaults["thinkingDefault"]
        if thinking in {"always", "high", "xhigh"}:
            agent_cfg["reasoning_effort"] = "high"
        elif thinking in {"auto", "medium", "adaptive"}:
            agent_cfg["reasoning_effort"] = "medium"
        elif thinking in {"off", "low", "none", "minimal"}:
            agent_cfg["reasoning_effort"] = "low"
        changes = True

    # Map compaction -> compression
    compaction = defaults.get("compaction") or {}
    if compaction:
        compression = target_config.get("compression") or {}
        if compaction.get("mode") == "off":
            compression["enabled"] = False
        else:
            compression["enabled"] = True
        if compaction.get("timeout"):
            pass  # No direct mapping
        if compaction.get("model"):
            aux = target_config.setdefault("auxiliary", {})
            aux_comp = aux.setdefault("compression", {})
            aux_comp["model"] = compaction["model"]
        target_config["compression"] = compression
        changes = True

    # Map humanDelay
    human_delay = defaults.get("humanDelay") or {}
    if human_delay:
        hd = target_config.get("human_delay") or {}
        hd_mode = human_delay.get("mode") or ("natural" if human_delay.get("enabled") else None)
        if hd_mode and hd_mode != "off":
            hd["mode"] = hd_mode
        if human_delay.get("minMs"):
            hd["min_ms"] = human_delay["minMs"]
        if human_delay.get("maxMs"):
            hd["max_ms"] = human_delay["maxMs"]
        target_config["human_delay"] = hd
        changes = True

    # Map userTimezone
    if defaults.get("userTimezone"):
        target_config["timezone"] = defaults["userTimezone"]
        changes = True

    # Map terminal/exec settings
    exec_cfg = (config.get("tools") or {}).get("exec") or {}
    if exec_cfg:
        terminal_cfg = target_config.get("terminal") or {}
        if exec_cfg.get("timeoutSec") or exec_cfg.get("timeout"):
            terminal_cfg["timeout"] = exec_cfg.get("timeoutSec") or exec_cfg.get("timeout")
            changes = True
        target_config["terminal"] = terminal_cfg

    # Map sandbox -> terminal docker settings
    sandbox = defaults.get("sandbox") or {}
    if sandbox and sandbox.get("backend") == "docker":
        terminal_cfg = target_config.get("terminal") or {}
        terminal_cfg["backend"] = "docker"
        if sandbox.get("docker", {}).get("image"):
            terminal_cfg["docker_image"] = sandbox["docker"]["image"]
        target_config["terminal"] = terminal_cfg
        changes = True

    if changes:
        target_config["agent"] = agent_cfg
        if self.execute:
            self.maybe_backup(target_config_path)
            dump_yaml_file(target_config_path, target_config)
        self.record("agent-config", "openclaw.json agents.defaults", "config.yaml agent/compression/terminal",
                    "migrated", "Agent defaults mapped to Superforecasting Agent config")

    # Archive multi-agent list
    if agent_list:
        if self.archive_dir and self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "agents-list.json"
            write_config_archive(dest, agent_list)
        self.record("agent-config", "openclaw.json agents.list", "archive/agents-list.json",
                    "archived", f"Multi-agent setup ({len(agent_list)} agents) archived for manual recreation")

    # Archive bindings
    bindings = config.get("bindings") or []
    if bindings:
        if self.archive_dir and self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "bindings.json"
            write_config_archive(dest, bindings)
        self.record("agent-config", "openclaw.json bindings", "archive/bindings.json",
                    "archived", f"Agent routing bindings ({len(bindings)} rules) archived")


def migrate_session_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    session = config.get("session") or {}
    if not session:
        self.record("session-config", None, None, "skipped", "No session configuration found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    sr = target_config.get("session_reset") or {}
    changes = False

    # OpenClaw uses session.reset (structured) and session.resetTriggers (string array)
    reset = session.get("reset") or {}
    reset_triggers = session.get("resetTriggers") or session.get("reset_triggers") or []

    if reset:
        # Structured reset config: has mode, atHour, idleMinutes
        mode = reset.get("mode", "")
        if mode == "daily":
            sr["mode"] = "daily"
        elif mode == "idle":
            sr["mode"] = "idle"
        else:
            sr["mode"] = mode or "none"
        if reset.get("atHour") is not None:
            sr["at_hour"] = reset["atHour"]
        if reset.get("idleMinutes"):
            sr["idle_minutes"] = reset["idleMinutes"]
        changes = True
    elif isinstance(reset_triggers, list) and reset_triggers:
        # Simple string triggers: ["daily", "idle"]
        has_daily = "daily" in reset_triggers
        has_idle = "idle" in reset_triggers
        if has_daily and has_idle:
            sr["mode"] = "both"
        elif has_daily:
            sr["mode"] = "daily"
        elif has_idle:
            sr["mode"] = "idle"
        changes = True

    if changes:
        target_config["session_reset"] = sr
        if self.execute:
            self.maybe_backup(target_config_path)
            dump_yaml_file(target_config_path, target_config)
        self.record("session-config", "openclaw.json session.resetTriggers",
                    "config.yaml session_reset", "migrated")

    # Archive full session config (identity links, thread bindings, etc.)
    complex_keys = {"identityLinks", "threadBindings", "maintenance", "scope", "sendPolicy"}
    complex_session = {k: v for k, v in session.items() if k in complex_keys and v}
    if complex_session and self.archive_dir:
        if self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "session-config.json"
            write_config_archive(dest, complex_session)
        self.record("session-config", "openclaw.json session (advanced)",
                    "archive/session-config.json", "archived",
                    "Advanced session settings archived (identity links, thread bindings, etc.)")


def migrate_browser_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    browser = config.get("browser") or {}
    if not browser:
        self.record("browser-config", None, None, "skipped", "No browser configuration found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    target_browser = target_config.get("browser") or {}
    changed = False

    # Map fields that have Superforecasting Agent equivalents
    if browser.get("cdpUrl"):
        target_browser["cdp_url"] = browser["cdpUrl"]
        changed = True
    if browser.get("headless") is not None:
        target_browser["headless"] = browser["headless"]
        changed = True

    if changed:
        target_config["browser"] = target_browser
        if self.execute:
            self.maybe_backup(target_config_path)
            dump_yaml_file(target_config_path, target_config)
        self.record("browser-config", "openclaw.json browser.*", "config.yaml browser",
                    "migrated")

    # Archive remaining browser settings
    advanced = {k: v for k, v in browser.items()
               if k not in {"cdpUrl", "headless"} and v}
    if advanced and self.archive_dir:
        if self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "browser-config.json"
            write_config_archive(dest, advanced)
        self.record("browser-config", "openclaw.json browser (advanced)",
                    "archive/browser-config.json", "archived")


def migrate_tools_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    tools = config.get("tools") or {}
    if not tools:
        self.record("tools-config", None, None, "skipped", "No tools configuration found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    changed = False

    # Map exec timeout -> terminal timeout (field is timeoutSec in OpenClaw)
    exec_cfg = tools.get("exec") or {}
    timeout_val = exec_cfg.get("timeoutSec") or exec_cfg.get("timeout")
    if timeout_val:
        terminal_cfg = target_config.get("terminal") or {}
        terminal_cfg["timeout"] = timeout_val
        target_config["terminal"] = terminal_cfg
        changed = True

    # Map web search API key (path: tools.web.search.brave.apiKey in OpenClaw)
    web_cfg = tools.get("web") or tools.get("webSearch") or {}
    search_cfg = web_cfg.get("search") or web_cfg if not web_cfg.get("search") else web_cfg["search"]
    brave_cfg = search_cfg.get("brave") or {}
    brave_key = brave_cfg.get("apiKey") or search_cfg.get("braveApiKey") or web_cfg.get("braveApiKey")
    if brave_key and isinstance(brave_key, str) and self.migrate_secrets:
        self._set_env_var("BRAVE_API_KEY", brave_key, "tools.web.search.brave.apiKey")

    if changed and self.execute:
        self.maybe_backup(target_config_path)
        dump_yaml_file(target_config_path, target_config)
        self.record("tools-config", "openclaw.json tools.*", "config.yaml terminal",
                    "migrated")

    # Archive full tools config
    if self.archive_dir:
        if self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "tools-config.json"
            write_config_archive(dest, tools)
        self.record("tools-config", "openclaw.json tools (full)", "archive/tools-config.json",
                    "archived", "Full tools config archived for reference")


def migrate_approvals_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    approvals = config.get("approvals") or {}
    if not approvals:
        self.record("approvals-config", None, None, "skipped", "No approvals configuration found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)

    # Map approval mode (nested under approvals.exec.mode in OpenClaw)
    exec_approvals = approvals.get("exec") or {}
    mode = (exec_approvals.get("mode") if isinstance(exec_approvals, dict) else None) or approvals.get("mode") or approvals.get("defaultMode")
    if mode:
        mode_map = {"auto": "off", "always": "manual", "smart": "smart", "manual": "manual"}
        target_mode = mode_map.get(mode, "manual")
        target_config.setdefault("approvals", {})["mode"] = target_mode
        if self.execute:
            self.maybe_backup(target_config_path)
            dump_yaml_file(target_config_path, target_config)
        self.record("approvals-config", "openclaw.json approvals.mode",
                    "config.yaml approvals.mode", "migrated", f"Mapped '{mode}' -> '{target_mode}'")

    # Archive full approvals config
    if len(approvals) > 1 and self.archive_dir:
        if self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "approvals-config.json"
            write_config_archive(dest, approvals)
        self.record("approvals-config", "openclaw.json approvals (rules)",
                    "archive/approvals-config.json", "archived")
