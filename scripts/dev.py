#!/usr/bin/env python3
"""Bootstrap and run the repository's shared, blocking quality checks.

Fresh checkout: python3 scripts/dev.py bootstrap
Existing checkout: python3 scripts/dev.py check
Python-only fast path: python3 scripts/dev.py check --python-only
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The stricter scope grows with ownership extractions. Legacy code still runs
# the repository-wide encoding gate; no silent baseline hides new-layer errors.
STRICT_PYTHON = (
    "scripts/dev.py",
    "scripts/strict_scope.py",
    "forecasting/news",
    "forecasting/interviews",
    "superforecasting_agent/runtime/news_desk.py",
    "superforecasting_agent/runtime/data_desk.py",
    "forecasting/marketdata/catalog.py",
    "forecasting/marketdata/discovery.py",
    "forecasting/marketdata/discovery_worldbank.py",
    "forecasting/marketdata/model.py",
    "forecasting/marketdata/parsing.py",
    "forecasting/marketdata/provider.py",
    "forecasting/marketdata/providers/bcb.py",
    "forecasting/marketdata/providers/country_indicators.py",
    "forecasting/marketdata/providers/europe.py",
    "forecasting/marketdata/providers/nws.py",
    "forecasting/marketdata/providers/regional_statistics.py",
    "forecasting/marketdata/providers/sdmx.py",
    "forecasting/marketdata/providers/weather.py",
    "protocol",
    "agent/review_options.py",
    "tui_gateway/server_requests.py",
    "tools/code_kernel_remote.py",
    "tools/code_kernel_supervisor.py",
    "tools/environments/leases.py",
    "tools/code_calculations.py",
    "tools/code_kernel.py",
    "tools/code_kernel_runner.py",
    "agent/thread_scoped_output.py",
    "tools/code_execution_rpc.py",
    "agent/context_usage.py",
    "agent/compaction_recall.py",
    "scripts/evaluate_context_recall.py",
    "agent/tool_discovery.py",
    "agent/result_references.py",
    "agent/delegation_images.py",
    "agent/reasoning_details.py",
    "gateway/hooks.py",
    "superforecasting_agent/runtime/model_configuration.py",
    "superforecasting_agent/runtime/model_env.py",
    "superforecasting_agent/runtime/interactive_config.py",
    "superforecasting_agent/runtime/interactive_defaults.py",
    "gateway/command_dispatch.py",
    "superforecasting_agent/runtime/cli_output.py",
    "superforecasting_agent/runtime/assistant_text.py",
    "scripts/check_naming.py",
    "scripts/push_plan.py",
    "superforecasting_agent/runtime/diagnostic_service.py",
    "superforecasting_agent/runtime/commands.py",
    "gateway/slash_access.py",
    "gateway/display_config.py",
    "tui_gateway/command_routes.py",
    "tui_gateway/commands_rpc.py",
    "tui_gateway/tools_rpc.py",
    "tui_gateway/completion_rpc.py",
    "tui_gateway/rpc_binding.py",
    "scripts/prepare_upgrade_baselines.py",
    "scripts/verify_profile_migrations.py",
    "tools/mcp_oauth.py",
    "tools/mcp_oauth_manager.py",
    "tools/skills_hub.py",
    "agent/browser_provider.py",
    "agent/file_safety.py",
    "agent/lsp/install.py",
    "tui_gateway/ws.py",
    "tools/skills_sync.py",
    "agent/portal_tags.py",
    "forecasting/economic_measurements.py",
    "agent/http_cleanup.py",
    "superforecasting_agent/credentials",
    "superforecasting_agent/storage",
    "agent/conversation_lifecycle.py",
    "superforecasting_agent/worker.py",
    "superforecasting_agent/configuration",
    "tools/environments/configuration.py",
    "forecasting/appconfig.py",
    "forecasting/sources/dispatch.py",
    "forecasting/sources/kalshi_prices.py",
    "forecasting/sources/kalshi_selection.py",
    "forecasting/sources/polymarket_selection.py",
    "forecasting/sources/requests.py",
    "forecasting/sources/evidence.py",
    "forecasting/sources/filters.py",
    "forecasting/sources/watched.py",
    "forecasting/transports/slack.py",
    "forecasting/configuration",
    "superforecasting_agent/tooling",
    "superforecasting_agent/runtime/subgoal_commands.py",
    "superforecasting_agent/runtime/plugin_commands.py",
    "superforecasting_agent/runtime/quota_commands.py",
    "superforecasting_agent/runtime/platform_commands.py",
    "forecasting/hooks/loader.py",
    "forecasting/hooks/dsl.py",
    "forecasting/hooks/store.py",
    "superforecasting_agent/runtime/quick_commands.py",
    "agent/forecast_stage.py",
    "agent/model_catalog.py",
    "agent/agent_factory.py",
    "agent/background_options.py",
    "agent/startup_prompt.py",
    "agent/openai_clients.py",
    "agent/session_lifecycle.py",
    "agent/review_lifecycle.py",
    "superforecasting_agent/installation.py",
    "superforecasting_agent/startup_environment.py",
    "superforecasting_agent/profile_paths.py",
    "superforecasting_agent/hosting",
    "superforecasting_agent/processes.py",
    "superforecasting_agent/platform_registry.py",
    "superforecasting_agent/session_context.py",
    "forecasting/application",
    "forecasting/panel_selection.py",
    "forecasting/distribution_summary.py",
    "forecasting/distribution_parameters.py",
    "forecasting/__init__.py",
    "superforecasting_agent/application",
    "forecasting/interfaces",
    "scripts/dev.py",
    "scripts/build_profiles.py",
    "scripts/verify_profiles.py",
    "scripts/terminal_session.py",
    "superforecasting_agent/constants.py",
    "superforecasting_agent/bootstrap.py",
    "scripts/verify_headless_host.py",
    "products/tui/superforecasting_agent_tui",
)


# Inherited owners can adopt correctness checks before wholesale formatting/types.
CORRECTNESS_PYTHON = (
    "agent/agent_runtime_helpers.py",
    "tools/code_execution_tool.py",
    "scripts/investigate_native_tls.py",
    "superforecasting_agent/runtime/kanban.py",
    "superforecasting_agent/runtime/kanban_db.py",
)


def run(*command: str, cwd: Path = ROOT) -> None:
    print("+ " + " ".join(command), flush=True)
    started = time.monotonic()
    try:
        subprocess.run(command, cwd=cwd, check=True)
    finally:
        print(f"Elapsed: {time.monotonic() - started:.2f}s", flush=True)


def executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(
            f"Required tool {name!r} is missing; install it before bootstrap"
        )
    return found


def venv_tool(name: str) -> str:
    directory = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    path = directory / (name + ".exe" if os.name == "nt" else name)
    if not path.is_file():
        raise RuntimeError(f"Missing {path}; run python3 scripts/dev.py bootstrap")
    return str(path)


def check(*, python_only: bool = False) -> None:
    run(venv_tool("python"), "scripts/check_naming.py")
    run(venv_tool("python"), "scripts/check-windows-footguns.py", "--all")
    run(venv_tool("ruff"), "check", ".")
    run(venv_tool("python"), "scripts/strict_scope.py")
    run(venv_tool("ruff"), "check", "--select", "E4,E7,E9,F", *CORRECTNESS_PYTHON)
    run(venv_tool("ruff"), "check", "--select", "E4,E7,E9,F,I", *STRICT_PYTHON)
    run(venv_tool("ruff"), "format", "--check", *STRICT_PYTHON)
    run(venv_tool("ty"), "check", "--error-on-warning", *STRICT_PYTHON)
    run(venv_tool("lint-imports"))
    run(venv_tool("python"), "-m", "protocol.codegen", "--check")
    run(venv_tool("python"), "scripts/gen-news-catalog.py", "--check")
    run(venv_tool("python"), "-m", "scripts.docgen", "--check")
    if not python_only:
        npm = executable("npm")
        run(npm, "run", "lint", cwd=ROOT / "ui-tui")
        run(npm, "run", "type-check", cwd=ROOT / "ui-tui")


def bootstrap() -> None:
    # --frozen consumes the checked-in dependency resolution; it cannot silently
    # update the lockfile while setting up a contributor or CI worker.
    run(
        executable("uv"),
        "sync",
        "--frozen",
        "--extra",
        "dev",
        "--extra",
        "web",
        "--extra",
        "pty",
    )
    npm = executable("npm")
    run(npm, "ci", cwd=ROOT / "ui-tui")
    run(npm, "run", "build", cwd=ROOT / "ui-tui")
    run(executable("git"), "config", "core.hooksPath", ".githooks")
    run(executable("git"), "config", "blame.ignoreRevsFile", ".git-blame-ignore-revs")
    check()


def check_snapshot(ref: str | None = None) -> None:
    """Require the files checked in place to match the index or pushed tree.

    This deliberately does not stash user changes or reuse an editable virtual
    environment in a temporary tree (which can import the original checkout).
    """

    def git(*args: str) -> bytes:
        return subprocess.check_output(("git", *args), cwd=ROOT)

    if git("diff", "--name-only", "-z"):
        raise RuntimeError(
            "Unstaged tracked changes would make checks differ from the commit. "
            "Stage the intended changes or set aside the remaining work first."
        )
    untracked = git("ls-files", "--others", "--exclude-standard", "-z")
    if untracked:
        paths = untracked.rstrip(b"\0").split(b"\0")
        preview = ", ".join(repr(os.fsdecode(path)) for path in paths[:10])
        remaining = f" (and {len(paths) - 10} more)" if len(paths) > 10 else ""
        raise RuntimeError(
            "Untracked files can affect imports and checks. "
            "Track, ignore, or move them before running commit/push gates. "
            f"Found: {preview}{remaining}"
        )
    if ref is not None:
        tree = git("rev-parse", "--verify", ref + "^{tree}").strip()
        if tree != git("write-tree").strip():
            raise RuntimeError(
                "The pushed tree differs from the checked index. "
                "Check out that commit with a clean index before pushing it."
            )


# Bounded, credential-free lifecycle coverage. Native/platform skips remain visible;
# this list is an integration feedback tier, not the release support matrix.
INTEGRATION_PYTHON = (
    "tests/hosting/test_pty_spawn.py",
    "tests/runtime_cli/test_local_desk_lifecycle.py",
    "tests/runtime_cli/test_dashboard_pty_reconnect.py",
    "tests/tui_gateway/test_runtime_host_owner.py",
)
INTEGRATION_TUI = (
    "src/__tests__/gatewayRecovery.test.ts",
    "src/__tests__/gatewayClient.test.ts",
    "src/__tests__/useJobAttach.test.ts",
)


def selected_tests(values: list[str], *, frontend: bool) -> list[str]:
    """Admit explicit test files before any command executes; never infer a full suite."""
    root = ROOT / "ui-tui" if frontend else ROOT
    allowed = root / ("src/__tests__" if frontend else "tests")
    result: list[str] = []
    for value in values:
        filename, separator, node = value.partition("::")
        path = (root / filename).resolve()
        if (
            not path.is_relative_to(allowed.resolve())
            or not path.is_file()
            or (frontend and (separator or path.suffix not in {".ts", ".tsx"}))
            or (not frontend and path.suffix != ".py")
            or (separator and not node)
        ):
            raise RuntimeError(
                f"Expected an explicit {'TUI' if frontend else 'Python'} test file: {value!r}"
            )
        normalized = path.relative_to(root.resolve()).as_posix()
        if separator:
            normalized += separator + node
        if normalized not in result:
            result.append(normalized)
    return result


def verify(
    tier: str,
    python_tests: list[str],
    tui_tests: list[str],
    *,
    python_only: bool = False,
) -> None:
    """Share static gates and test runners without confusing feedback with qualification."""
    if tier != "fast" and (python_tests or tui_tests or python_only):
        raise RuntimeError(
            "Test selections and --python-only apply to the fast tier only"
        )
    if python_only and tui_tests:
        raise RuntimeError("--python-only cannot run TUI tests")
    if tier == "fast":
        python_tests = selected_tests(python_tests, frontend=False)
        tui_tests = selected_tests(tui_tests, frontend=True)
        if not python_tests and not tui_tests:
            raise RuntimeError(
                "Fast verification needs --python-test or --tui-test; use check for static checks alone"
            )
    elif tier == "integration":
        python_tests = selected_tests(list(INTEGRATION_PYTHON), frontend=False)
        tui_tests = selected_tests(list(INTEGRATION_TUI), frontend=True)
    elif tier != "qualification":
        raise RuntimeError(f"Unknown verification tier: {tier}")

    started = time.monotonic()
    print(f"Verification tier: {tier} (local checkout; no receipt reuse)", flush=True)
    try:
        check(python_only=python_only)
        if tier != "fast":
            run(executable("npm"), "run", "build", cwd=ROOT / "ui-tui")
        if python_tests or tier == "qualification":
            run(executable("bash"), str(ROOT / "scripts/run_tests.sh"), *python_tests)
        if tui_tests or tier == "qualification":
            run(executable("npm"), "test", "--", *tui_tests, cwd=ROOT / "ui-tui")
    finally:
        print(f"Tier elapsed: {time.monotonic() - started:.2f}s", flush=True)
    print(
        "Local tier passed. Native installed-artifact and upgrade qualification remain separate.",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "check", "snapshot", "verify"))
    parser.add_argument(
        "--python-only",
        action="store_true",
        help="Check Python/contracts without requiring Node",
    )
    parser.add_argument("--ref", help="Pushed commit whose tree must match the index")
    parser.add_argument("--tier", choices=("fast", "integration", "qualification"))
    parser.add_argument(
        "--python-test",
        action="append",
        default=[],
        help="Python test file or node ID; repeatable",
    )
    parser.add_argument(
        "--tui-test",
        action="append",
        default=[],
        help="TUI test file relative to ui-tui; repeatable",
    )
    args = parser.parse_args()
    if args.command != "verify" and (args.tier or args.python_test or args.tui_test):
        parser.error("Tier and test selections apply to verify only")
    if args.ref and args.command != "snapshot":
        parser.error("--ref applies to snapshot only")
    if args.command == "bootstrap" and args.python_only:
        parser.error("--python-only applies to check, not bootstrap")
    try:
        if args.command == "verify":
            verify(
                args.tier or "fast",
                args.python_test,
                args.tui_test,
                python_only=args.python_only,
            )
        elif args.command == "snapshot":
            check_snapshot(args.ref)
        elif args.command == "bootstrap":
            bootstrap()
        else:
            check(python_only=args.python_only)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Development gate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
