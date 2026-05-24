"""Regression tests for packaging metadata in pyproject.toml."""

from pathlib import Path
import tomllib


def _load_project():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        return tomllib.load(handle)["project"]


def _load_optional_dependencies():
    return _load_project()["optional-dependencies"]


def _load_package_data():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        tool = tomllib.load(handle)["tool"]
    return tool["setuptools"]["package-data"]


def _load_setuptools_find():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        tool = tomllib.load(handle)["tool"]
    return tool["setuptools"]["packages"]["find"]


def test_matrix_extra_not_in_all():
    """The [matrix] extra pulls `mautrix[encryption]` -> `python-olm`,
    which has Linux-only wheels and no native build path on Windows or
    modern macOS (archived libolm, C++ errors with Clang 21+).

    With matrix in [all], `uv sync --locked` on Windows tried to build
    python-olm from sdist and failed on `make`. As of 2026-05-12 the
    [matrix] extra is excluded from [all] entirely and routed through
    `tools/lazy_deps.py` (LAZY_DEPS["platform.matrix"]) — installs at
    first use, where the user is expected to have a toolchain.
    """
    optional_dependencies = _load_optional_dependencies()

    package_name = _load_project()["name"]
    assert "matrix" in optional_dependencies, f"[matrix] extra must still exist for explicit `pip install {package_name}[matrix]`"
    # Must NOT appear in [all] in any form — neither unconditional nor
    # platform-gated. Lazy-install handles it.
    matrix_in_all = [
        dep for dep in optional_dependencies["all"]
        if "matrix" in dep
    ]
    assert not matrix_in_all, (
        "matrix must not appear in [all] — it's lazy-installed via "
        "tools/lazy_deps.py LAZY_DEPS['platform.matrix']. Found: "
        f"{matrix_in_all}"
    )


def test_lazy_installable_extras_excluded_from_all():
    """Policy (2026-05-12): every extra that has a `LAZY_DEPS` entry
    in `tools/lazy_deps.py` must be excluded from [all].

    The lazy-install system exists so one quarantined PyPI release
    (e.g. mistralai 2.4.6) can't break every fresh install. Putting a
    backend in BOTH [all] and LAZY_DEPS defeats that — fresh installs
    eager-install it and inherit whatever's broken upstream.

    If you're tempted to add an opt-in backend to [all] for "convenience,"
    add it to `LAZY_DEPS` instead so it installs at first use.
    """
    optional_dependencies = _load_optional_dependencies()
    package_name = _load_project()["name"]

    # Hard-coded mirror of the extras that are in LAZY_DEPS as of
    # 2026-05-12. This list intentionally duplicates rather than
    # imports tools/lazy_deps.py so the test stays a contract — if
    # someone adds a new lazy-install backend, they have to update
    # this list AND verify [all] doesn't contain it.
    lazy_covered_extras = {
        "anthropic", "bedrock",
        "exa", "firecrawl", "parallel-web",
        "fal",
        "edge-tts", "tts-premium",
        "voice",  # faster-whisper / sounddevice / numpy
        "modal", "daytona", "vercel",
        "messaging", "slack", "matrix", "dingtalk", "feishu",
        "honcho", "hindsight",
    }
    all_extra_specs = optional_dependencies["all"]
    for extra in lazy_covered_extras:
        offending = [
            spec for spec in all_extra_specs
            if f"{package_name}[{extra}]" in spec
        ]
        assert not offending, (
            f"[{extra}] is in [all] but also in LAZY_DEPS. "
            f"Remove it from [all] in pyproject.toml — it lazy-installs "
            f"at first use. Found in [all]: {offending}"
        )


def test_messaging_extra_includes_qrcode_for_weixin_setup():
    optional_dependencies = _load_optional_dependencies()

    messaging_extra = optional_dependencies["messaging"]
    assert any(dep.startswith("qrcode") for dep in messaging_extra)


def test_dingtalk_extra_includes_qrcode_for_qr_auth():
    """DingTalk's QR-code device-flow auth (hermes_cli/dingtalk_auth.py)
    needs the qrcode package."""
    optional_dependencies = _load_optional_dependencies()

    dingtalk_extra = optional_dependencies["dingtalk"]
    assert any(dep.startswith("qrcode") for dep in dingtalk_extra)


def test_feishu_extra_includes_qrcode_for_qr_login():
    """Feishu's QR login flow (gateway/platforms/feishu.py) needs the
    qrcode package."""
    optional_dependencies = _load_optional_dependencies()

    feishu_extra = optional_dependencies["feishu"]
    assert any(dep.startswith("qrcode") for dep in feishu_extra)


def test_dashboard_plugin_manifests_and_assets_are_packaged():
    """Bundled dashboard plugins need their manifests and built assets in
    wheel installs so /api/dashboard/plugins can discover them outside a
    source checkout."""
    package_data = _load_package_data()
    plugin_data = package_data["plugins"]

    assert "*/dashboard/manifest.json" in plugin_data
    assert "*/dashboard/dist/*" in plugin_data
    assert "*/dashboard/dist/**/*" in plugin_data


def test_forecast_native_package_namespace_is_exposed():
    project = _load_project()
    scripts = project["scripts"]
    include = _load_setuptools_find()["include"]

    assert scripts["forecast"] == "superforecasting_agent.cli:main"
    assert scripts["superforecast"] == "superforecasting_agent.cli:main"
    assert scripts["superforecasting-agent"] == "superforecasting_agent.cli:main"
    assert scripts["hermes-agent"] == "superforecasting_agent.cli:main"
    assert "superforecasting_agent" in include
    assert "superforecasting_agent.*" in include


def test_web_locale_app_brand_is_forecast_native():
    i18n_dir = Path(__file__).resolve().parents[1] / "web" / "src" / "i18n"
    locale_files = []
    for path in sorted(i18n_dir.glob("*.ts")):
        text = path.read_text(encoding="utf-8")
        if ": Translations = {" in text:
            locale_files.append(path)

    assert locale_files
    for path in locale_files:
        text = path.read_text(encoding="utf-8")
        assert 'brand: "Superforecasting Agent"' in text, path
        assert "~/.superforecasting-agent" in text, path
        assert 'brand: "Hermes Agent"' not in text, path
        assert "Hermes Agent ☤" not in text, path
        assert "~/.hermes" not in text, path


def test_web_update_action_names_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "web" / "src" / "App.tsx",
        root / "web" / "src" / "pages" / "SessionsPage.tsx",
        root / "web" / "src" / "lib" / "api.ts",
        root / "web" / "src" / "i18n" / "types.ts",
        *sorted((root / "web" / "src" / "i18n").glob("*.ts")),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "updateAgent" in text
    assert "updatingAgent" in text
    assert "updateLegacyHermes" in text
    assert "updateHermes" not in text
    assert "updatingHermes" not in text


def test_web_dashboard_titles_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "<title>Superforecasting Agent - Forecast Desk</title>" in text
    assert "Hermes Agent - Dashboard" not in text


def test_docker_entrypoint_and_compose_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "SUPERFORECASTING_AGENT_HOME" in entrypoint
    assert "FORECAST_HOME" in entrypoint
    assert "exec superforecasting-agent \"$@\"" in entrypoint
    assert "superforecasting-agent dashboard" in entrypoint
    assert "SUPERFORECASTING_AGENT_DASHBOARD" in entrypoint
    assert "FORECAST_DASHBOARD" in entrypoint
    assert "exec hermes \"$@\"" not in entrypoint
    assert "hermes dashboard" not in entrypoint

    assert "# docker-compose.yml for Superforecasting Agent" in compose
    assert "image: superforecasting-agent" in compose
    assert "container_name: superforecasting-agent-gateway" in compose
    assert "container_name: superforecasting-agent-dashboard" in compose
    assert "~/.superforecasting-agent:/opt/data" in compose
    assert "SUPERFORECASTING_AGENT_HOME=/opt/data" in compose
    assert "image: hermes-agent" not in compose
    assert "container_name: hermes" not in compose
    assert "~/.hermes:/opt/data" not in compose


def test_standalone_gateway_script_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "hermes-gateway").read_text(encoding="utf-8")

    assert "Superforecasting Agent Gateway - standalone optional messaging integration." in text
    assert 'SERVICE_NAME = "superforecasting-agent-gateway"' in text
    assert 'LAUNCHD_LABEL = "ai.superforecasting-agent.gateway"' in text
    assert "display_hermes_home()" in text
    assert "get_hermes_home() / \"logs\"" in text
    assert "Starting Superforecasting Agent Gateway..." in text
    assert "Superforecasting Agent Gateway - Messaging Platform Integration" in text
    assert "Starting Hermes Gateway" not in text
    assert "Hermes Gateway - Messaging Platform Integration" not in text
    assert "Path.home() / \".hermes\" / \"logs\"" not in text
    assert "~/.hermes/logs/gateway.log" not in text


def test_windows_gateway_service_names_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "hermes_cli" / "gateway_windows.py").read_text(encoding="utf-8")

    assert '_TASK_NAME_DEFAULT = "Superforecasting_Agent_Gateway"' in text
    assert '_LEGACY_TASK_NAME_DEFAULT = "Hermes_Gateway"' in text
    assert "Default profile: ``Superforecasting_Agent_Gateway``" in text
    assert "Named profile X: ``Superforecasting_Agent_Gateway_<X>``" in text
    assert "def get_legacy_task_name()" in text
    assert "def get_legacy_startup_entry_path()" in text
    assert "def get_legacy_task_script_path()" in text


def test_install_helpers_use_forecast_native_visible_copy():
    root = Path(__file__).resolve().parents[1]
    install_ps1 = (root / "scripts" / "install.ps1").read_text(encoding="utf-8")
    node_bootstrap = (root / "scripts" / "lib" / "node-bootstrap.sh").read_text(encoding="utf-8")

    assert "Cloning Superforecasting Agent repository" in install_ps1
    assert "Adding Superforecasting Agent to PATH" in install_ps1
    assert "`superforecasting-agent dashboard` will not work" in install_ps1
    assert "`superforecasting-agent dashboard` should now work" in install_ps1
    assert "Superforecasting Agent needs Git Bash" in install_ps1
    assert "forecast-runtime-managed" in install_ps1
    assert "Cloning Hermes repository" not in install_ps1
    assert "Adding Hermes to PATH" not in install_ps1
    assert "`hermes dashboard` will not work" not in install_ps1
    assert "`hermes dashboard` should now work" not in install_ps1
    assert "Hermes needs Git Bash" not in install_ps1
    assert "Hermes-managed" not in install_ps1

    assert "SUPERFORECASTING_AGENT_HOME" in node_bootstrap
    assert "$HOME/.superforecasting-agent" in node_bootstrap
    assert "forecast-runtime-managed" in node_bootstrap
    assert "Hermes-managed" not in node_bootstrap


def test_modal_cleanup_script_is_forecast_native_with_legacy_matching():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "kill_modal.sh").read_text(encoding="utf-8")

    assert "Stop Superforecasting Agent sandboxes" in text
    assert "Stopping Superforecasting Agent sandboxes" in text
    assert "Current Superforecasting Agent Modal status" in text
    assert "superforecasting-agent|hermes-agent" in text
    assert "Stop hermes-agent sandboxes" not in text
    assert "Stopping hermes-agent sandboxes" not in text
    assert "Current hermes-agent status" not in text


def test_runtime_docstrings_use_forecast_native_home_paths():
    root = Path(__file__).resolve().parents[1]
    checked = {
        "gateway/pairing.py": "platforms/pairing",
        "gateway/sticker_cache.py": "sticker_cache.json",
        "gateway/runtime_footer.py": "runtime_footer",
        "hermes_cli/skin_engine.py": "skins/",
        "hermes_cli/skills_config.py": "skills:",
    }
    for rel_path, marker in checked.items():
        text = (root / rel_path).read_text(encoding="utf-8")
        header = text.split('"""', 2)[1]
        assert "~/.superforecasting-agent" in header, rel_path
        assert "legacy ~/.hermes" in header or "legacy ``~/.hermes" in header, rel_path
        assert marker in header, rel_path


def test_model_picker_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "hermes_cli" / "models.py").read_text(encoding="utf-8")

    assert "Superforecasting Agent is tool-calling-first" in text
    assert "superforecasting-agent auth add copilot" in text
    assert "~/.superforecasting-agent/.env" in text
    assert "hermes-agent is tool-calling-first" not in text
    assert "hermes auth add copilot" not in text
    assert "older Hermes that doesn't ship" not in text
    assert "without a Hermes release" not in text


def test_xai_oauth_referrer_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "hermes_cli" / "auth.py").read_text(encoding="utf-8")

    assert '"referrer": "superforecasting-agent"' in text
    assert "referrer=superforecasting-agent" in text
    assert '"referrer": "hermes-agent"' not in text
    assert "referrer=hermes-agent" not in text


def test_codex_runtime_migration_markers_are_forecast_native():
    from hermes_cli.codex_runtime_plugin_migration import (
        LEGACY_MIGRATION_END_MARKER,
        LEGACY_MIGRATION_MARKER,
        MIGRATION_END_MARKER,
        MIGRATION_MARKER,
    )

    root = Path(__file__).resolve().parents[1]
    migration_py = (
        root / "hermes_cli" / "codex_runtime_plugin_migration.py"
    ).read_text(encoding="utf-8")
    runtime_doc = (
        root / "website" / "docs" / "user-guide" / "features"
        / "codex-app-server-runtime.md"
    ).read_text(encoding="utf-8")

    assert "superforecasting-agent" in MIGRATION_MARKER
    assert "superforecasting-agent" in MIGRATION_END_MARKER
    assert "hermes-agent" not in MIGRATION_MARKER
    assert "hermes-agent" not in MIGRATION_END_MARKER
    assert "hermes-agent" in LEGACY_MIGRATION_MARKER
    assert "hermes-agent" in LEGACY_MIGRATION_END_MARKER
    assert "_START_TO_END_MARKERS" in migration_py
    assert "LEGACY_MIGRATION_MARKER" in migration_py
    assert "LEGACY_MIGRATION_END_MARKER" in migration_py
    assert "# managed by superforecasting-agent" in runtime_doc
    assert "# end superforecasting-agent managed section" in runtime_doc
    assert "The marker still uses inherited `hermes-agent` naming" not in runtime_doc


def test_high_attention_docs_navigation_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    sidebars = (root / "website" / "sidebars.ts").read_text(encoding="utf-8")
    docs_paths = [
        root / "website" / "docs" / "developer-guide" / "web-search-provider-plugin.md",
        root / "website" / "docs" / "developer-guide" / "image-gen-provider-plugin.md",
        root / "website" / "docs" / "developer-guide" / "adding-tools.md",
        root / "website" / "docs" / "developer-guide" / "contributing.md",
        root / "website" / "docs" / "developer-guide" / "model-provider-plugin.md",
        root / "website" / "docs" / "user-guide" / "features" / "hooks.md",
    ]
    docs_text = "\n".join(path.read_text(encoding="utf-8") for path in docs_paths)

    assert "Using the Forecast Desk" in sidebars
    assert "Using Hermes" not in sidebars
    assert "Build a Superforecasting Agent Plugin" in docs_text
    assert "Build a Hermes Plugin" not in docs_text
    assert "Building a Hermes Plugin" not in docs_text


def test_contributor_and_skills_index_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
    skills_index = (root / "scripts" / "build_skills_index.py").read_text(
        encoding="utf-8"
    )
    skills_hub = (root / "tools" / "skills_hub.py").read_text(encoding="utf-8")

    assert "# Contributing to Superforecasting Agent" in contributing
    assert "https://github.com/NousResearch/superforecasting-agent.git" in contributing
    assert "superforecasting-agent skills install" in contributing
    assert "forecast status" in contributing
    assert "Building Superforecasting Agent Skills Index" in skills_index
    assert "centralized Superforecasting Agent index" in skills_hub

    combined = "\n".join([contributing, skills_index, skills_hub])
    assert "# Contributing to Hermes Agent" not in combined
    assert "Thank you for contributing to Hermes Agent" not in combined
    assert "https://github.com/NousResearch/hermes-agent.git" not in combined
    assert "`hermes skills install`" not in combined
    assert "`hermes setup`" not in combined
    assert "Building Hermes Skills Index" not in combined
    assert "Hermes Skills Index" not in combined


def test_tool_runtime_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "tools" / "code_execution_tool.py",
        root / "tools" / "debug_helpers.py",
        root / "tools" / "openrouter_client.py",
        root / "tools" / "web_tools.py",
        root / "agent" / "transports" / "hermes_tools_mcp_server.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "Superforecasting Agent tools" in text
    assert "Run `superforecasting-agent tools` to set one up." in text
    assert "Hermes tools" not in text
    assert "Hermes tool" not in text
    assert "Run `hermes tools`" not in text


def test_google_workspace_skill_docs_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "skills" / "productivity" / "google-workspace" / "SKILL.md",
        root / "skills" / "productivity" / "google-workspace" / "scripts" / "_hermes_home.py",
        root / "skills" / "productivity" / "google-workspace" / "scripts" / "setup.py",
        root / "skills" / "productivity" / "google-workspace" / "scripts" / "gws_bridge.py",
        root / "website" / "docs" / "user-guide" / "skills" / "google-workspace.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "bundled"
            / "productivity"
            / "productivity-google-workspace.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "Superforecasting Agent-managed OAuth" in text
    assert "integration for Superforecasting Agent" in text
    assert "ask Superforecasting Agent to set up Google Workspace" in text
    assert "superforecasting-agent-google-client-secret.json" in text
    assert "superforecasting-agent[google]" in text
    assert "https://github.com/NousResearch/superforecasting-agent" in text
    assert "default: ~/.superforecasting-agent" in text
    assert "Google Workspace OAuth setup for Superforecasting Agent" in text
    assert "integration for Hermes" not in text
    assert "ask Hermes" not in text
    assert "Hermes-managed OAuth" not in text
    assert "pip install 'hermes-agent[google]'" not in text
    assert "Google Workspace OAuth setup for Hermes" not in text
    assert "same Hermes profile" not in text
    assert "https://github.com/NousResearch/hermes-agent" not in text


def test_superforecasting_agent_skill_metadata_points_to_fork():
    root = Path(__file__).resolve().parents[1]
    skill = root / "skills" / "autonomous-ai-agents" / "hermes-agent" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")

    assert "homepage: https://github.com/NousResearch/superforecasting-agent" in text
    assert "homepage: https://github.com/NousResearch/hermes-agent" not in text


def test_himalaya_skill_docs_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "skills" / "email" / "himalaya" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "bundled"
            / "email"
            / "email-himalaya.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "Superforecasting Agent Integration Notes" in text
    assert "from Superforecasting Agent" in text
    assert "use this from Superforecasting Agent" in text
    assert "Hermes Integration Notes" not in text
    assert "from Hermes" not in text
    assert "use this from Hermes" not in text


def test_onepassword_skill_docs_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "security" / "1password" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "security"
            / "security-1password.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "enhanced by Superforecasting Agent" in text
    assert "during Superforecasting Agent terminal calls" in text
    assert "Service Account (recommended for Superforecasting Agent)" in text
    assert "Superforecasting Agent Execution Pattern" in text
    assert "Superforecasting Agent terminal commands" in text
    assert "superforecasting-agent-tmux-sockets" in text
    assert "superforecasting-agent-op.sock" in text
    assert "enhanced by Hermes Agent" not in text
    assert "during Hermes terminal calls" not in text
    assert "recommended for Hermes" not in text
    assert "Hermes Execution Pattern" not in text
    assert "Hermes terminal commands" not in text
    assert "hermes-tmux-sockets" not in text
    assert "hermes-op.sock" not in text


def test_skill_examples_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "mcp" / "mcporter" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "mcp"
            / "mcp-mcporter.md"
        ),
        root / "skills" / "productivity" / "notion" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "bundled"
            / "productivity"
            / "productivity-notion.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "recommended for Superforecasting Agent" in text
    assert "Hello from Superforecasting Agent!" in text
    assert "recommended for Hermes" not in text
    assert "Hello from Hermes!" not in text


def test_github_auth_skill_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "skills" / "github" / "github-auth" / "SKILL.md",
        root / "skills" / "github" / "github-auth" / "scripts" / "gh-env.sh",
        root / "skills" / "github" / "github-code-review" / "SKILL.md",
        root / "skills" / "github" / "github-repo-management" / "references" / "github-api-cheatsheet.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "bundled"
            / "github"
            / "github-github-auth.md"
        ),
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "bundled"
            / "github"
            / "github-github-code-review.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert 'name like "superforecasting-agent"' in text
    assert 'title like "superforecasting-agent-' in text
    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "$HOME/.superforecasting-agent" in text
    assert 'name like "hermes-agent"' not in text
    assert 'title like "hermes-agent-' not in text
    assert "$HOME/.hermes/.env" not in text
    assert '${HERMES_HOME:-$HOME/.hermes}/skills/github/github-auth/scripts/gh-env.sh' not in text


def test_skill_helper_runtime_copy_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (
        root / "skills" / "red-teaming" / "godmode" / "scripts" / "auto_jailbreak.py"
    ).read_text(encoding="utf-8")

    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "Restart Superforecasting Agent" in text
    assert "Superforecasting Agent config.yaml" in text
    assert "Path.home() / \".superforecasting-agent\"" in text
    assert "Restart Hermes" not in text
    assert "Hermes config paths" not in text
    assert "Hermes config.yaml" not in text
    assert "Path.home() / \".hermes\"" not in text


def test_external_api_skill_helpers_use_fork_attribution():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "finance" / "stocks" / "scripts" / "stocks_client.py",
        root / "optional-skills" / "blockchain" / "hyperliquid" / "scripts" / "hyperliquid_client.py",
        root / "optional-skills" / "blockchain" / "solana" / "scripts" / "solana_client.py",
        root / "skills" / "research" / "polymarket" / "scripts" / "polymarket.py",
        root / "skills" / "research" / "arxiv" / "scripts" / "search_arxiv.py",
        root / "skills" / "productivity" / "linear" / "scripts" / "linear_api.py",
        root / "skills" / "productivity" / "maps" / "scripts" / "maps_client.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "superforecasting-agent/1.0" in text
    assert "SuperforecastingAgent/1.0" in text
    assert "superforecasting-agent-linear-skill/1.0" in text
    assert "~/.superforecasting-agent/.env" in text
    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "hermes-agent/1.0" not in text
    assert "HermesAgent/1.0" not in text
    assert "hermes-agent-linear-skill/1.0" not in text
    assert "~/.hermes/.env" not in text
    assert "Path(os.environ.get(\"HERMES_HOME\", \"~/.hermes\"))" not in text
    assert "hermes@agent.ai" not in text


def test_watcher_skill_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "devops" / "watchers" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "devops"
            / "devops-watchers.md"
        ),
        root / "optional-skills" / "devops" / "watchers" / "scripts" / "_watermark.py",
        root / "optional-skills" / "devops" / "watchers" / "scripts" / "watch_github.py",
        root / "optional-skills" / "devops" / "watchers" / "scripts" / "watch_http_json.py",
        root / "optional-skills" / "devops" / "watchers" / "scripts" / "watch_rss.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "SuperforecastingAgent-Watcher/1.0" in text
    assert "superforecasting-agent cron create" in text
    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "$AGENT_HOME/watcher-state/" in text
    assert "NousResearch/superforecasting-agent" in text
    assert "Hermes-Watcher/1.0" not in text
    assert "hermes cron create" not in text
    assert "$HERMES_HOME/watcher-state/" not in text
    assert "$HERMES_HOME/skills/devops/watchers/scripts/" not in text
    assert "NousResearch/hermes-agent" not in text
    assert "~/.hermes/.env" not in text


def test_telephony_skill_helper_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "productivity" / "telephony" / "SKILL.md",
        root / "optional-skills" / "productivity" / "telephony" / "scripts" / "telephony.py",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "productivity"
            / "productivity-telephony.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "Superforecasting Agent telephony helper" in text
    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "~/.superforecasting-agent/.env" in text
    assert "~/.superforecasting-agent/telephony_state.json" in text
    assert "Hermes telephony helper" not in text
    assert "Hermes optional telephony skill" not in text
    assert "~/.hermes/.env" not in text
    assert "Path(os.environ.get(\"HERMES_HOME\", \"~/.hermes\"))" not in text


def test_memento_skill_storage_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "productivity" / "memento-flashcards" / "SKILL.md",
        root / "optional-skills" / "productivity" / "memento-flashcards" / "scripts" / "memento_cards.py",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "productivity"
            / "productivity-memento-flashcards.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "Path.home() / \".superforecasting-agent\"" in text
    assert "~/.superforecasting-agent/skills/productivity/memento-flashcards/data/cards.json" in text
    assert "$HERMES_HOME/skills/productivity/memento-flashcards/data/cards.json" not in text
    assert "Path.home() / \".hermes\"" not in text


def test_canvas_skill_examples_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "productivity" / "canvas" / "SKILL.md",
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "productivity"
            / "productivity-canvas.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "SUPERFORECASTING_AGENT_HOME" in text
    assert "FORECAST_HOME" in text
    assert "$AGENT_HOME/skills/productivity/canvas/scripts/canvas_api.py" in text
    assert "$HERMES_HOME/skills/productivity/canvas/scripts/canvas_api.py" not in text


def test_osint_skill_helpers_use_fork_native_attribution():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "optional-skills" / "research" / "osint-investigation" / "SKILL.md",
        root / "optional-skills" / "research" / "osint-investigation" / "scripts" / "_http.py",
        root / "optional-skills" / "research" / "osint-investigation" / "scripts" / "fetch_usaspending.py",
        root / "optional-skills" / "research" / "osint-investigation" / "scripts" / "fetch_icij_offshore.py",
        (
            root
            / "optional-skills"
            / "research"
            / "osint-investigation"
            / "references"
            / "sources"
            / "wikipedia.md"
        ),
        (
            root
            / "optional-skills"
            / "research"
            / "osint-investigation"
            / "references"
            / "sources"
            / "icij-offshore.md"
        ),
        (
            root
            / "website"
            / "docs"
            / "user-guide"
            / "skills"
            / "optional"
            / "research"
            / "research-osint-investigation.md"
        ),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "superforecasting-agent-osint-investigation/0.2" in text
    assert "https://github.com/NousResearch/superforecasting-agent" in text
    assert "SUPERFORECASTING_AGENT_OSINT_UA" in text
    assert "SUPERFORECASTING_AGENT_OSINT_CACHE" in text
    assert "~/.cache/superforecasting-agent-osint/icij" in text
    assert "superforecasting-agent osint-investigation" in text
    assert "hermes-osint-investigation" not in text
    assert "https://github.com/NousResearch/hermes-agent" not in text
    assert "set HERMES_OSINT_UA" not in text
    assert "$HERMES_OSINT_CACHE/icij" not in text
    assert "~/.cache/hermes-osint/icij" not in text
    assert "hermes-agent osint-investigation" not in text


def test_classic_cli_visible_labels_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "cli.py").read_text(encoding="utf-8")

    assert "Captain Hermes" not in text
    assert "They call me Hermes" not in text
    assert "[Hermes #" not in text
    assert "while Hermes is busy" not in text
    assert "run hermes -w" not in text
    assert "Hermes-managed isolated debug" not in text


def test_gateway_setup_copy_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "hermes_cli" / "gateway.py").read_text(encoding="utf-8")

    assert "before the Hermes command" not in text
    assert "Hermes will log in directly" not in text
    assert "where Hermes delivers cron results" not in text
    assert "dedicated email account for your Hermes agent" not in text
    assert "email address Hermes will use" not in text
    assert "Hermes connects via the BlueBubbles" not in text
    assert "hermes pairing generate bluebubbles" not in text
    assert "Hermes will connect automatically" not in text
    assert 'signal-cli link -n "HermesAgent"' not in text


def test_codex_runtime_switch_copy_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "hermes_cli" / "codex_runtime_switch.py").read_text(encoding="utf-8")

    assert "Hermes tool callback registered" not in text
    assert "default Hermes runtime" not in text
    assert "Hermes tools available via MCP callback" not in text
    assert "use the default Hermes runtime" not in text


def test_model_tool_and_proxy_guidance_are_forecast_native():
    root = Path(__file__).resolve().parents[1]
    models = (root / "hermes_cli" / "models.py").read_text(encoding="utf-8")
    tools_config = (root / "hermes_cli" / "tools_config.py").read_text(encoding="utf-8")
    config = (root / "hermes_cli" / "config.py").read_text(encoding="utf-8")

    assert "Hermes will still save" not in models
    assert "Hermes cannot verify the model name" not in models
    assert "Hermes routes X searches" not in tools_config
    assert "remote Hermes API server" not in config
    assert "Remote Hermes API server URL" not in config
    assert "remote Superforecasting Agent API server" in config
    assert "Superforecasting Agent auth store" in config


def test_anthropic_oauth_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "agent" / "anthropic_adapter.py").read_text(encoding="utf-8")

    assert "Authorize Superforecasting Agent with your Claude Pro/Max subscription." in text
    assert "Authorize Hermes with your Claude Pro/Max subscription." not in text
    assert "Hermes-managed OAuth" not in text
    assert "Hermes-native PKCE" not in text


def test_google_oauth_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "agent" / "google_oauth.py").read_text(encoding="utf-8")

    assert "Superforecasting Agent looks for a locally installed gemini-cli" in text
    assert "Superforecasting Agent — signed in" in text
    assert "Hermes looks for a locally installed gemini-cli" not in text
    assert "Hermes — signed in" not in text


def test_curator_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (root / "agent" / "curator.py").read_text(encoding="utf-8")

    assert "Superforecasting Agent's background forecast-skill" in text
    assert "CURATOR. This is an" in text
    assert "superforecasting-agent curator run" in text
    assert "superforecasting-agent curator restore <name>" in text
    assert "Hermes' background skill CURATOR" not in text
    assert "`hermes curator run`" not in text
    assert "`hermes curator restore <name>`" not in text


def test_provider_runtime_guidance_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    gemini_native = (root / "agent" / "gemini_native_adapter.py").read_text(encoding="utf-8")
    gemini_cloudcode = (root / "agent" / "gemini_cloudcode_adapter.py").read_text(encoding="utf-8")
    compression = (root / "agent" / "conversation_compression.py").read_text(encoding="utf-8")
    bedrock = (root / "agent" / "bedrock_adapter.py").read_text(encoding="utf-8")
    copilot_acp = (root / "agent" / "copilot_acp_client.py").read_text(encoding="utf-8")

    assert "Superforecasting Agent typically makes 3-10 API calls" in gemini_native
    assert "forecast desk session" in gemini_native
    assert "Hermes typically makes 3-10 API calls" not in gemini_native
    assert "not a Superforecasting Agent issue" in gemini_cloudcode
    assert "not a Hermes issue" not in gemini_cloudcode
    assert "minimum {MINIMUM_CONTEXT_LENGTH:,} required by " in compression
    assert "f\"Superforecasting Agent" in compression
    assert "required by Hermes" not in compression
    assert "install Superforecasting Agent with Bedrock support" in bedrock
    assert "install Hermes with Bedrock support" not in bedrock
    assert "active ACP agent backend for Superforecasting Agent" in copilot_acp
    assert "active ACP agent backend for Hermes" not in copilot_acp
    assert "not supported by Superforecasting Agent yet" in copilot_acp
    assert "not supported by Hermes yet" not in copilot_acp


def test_support_error_copy_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    profile_distribution = (
        root / "hermes_cli" / "profile_distribution.py"
    ).read_text(encoding="utf-8")
    relaunch = (root / "hermes_cli" / "relaunch.py").read_text(encoding="utf-8")
    hooks = (root / "hermes_cli" / "hooks.py").read_text(encoding="utf-8")
    web_server = (root / "hermes_cli" / "web_server.py").read_text(encoding="utf-8")
    auth = (root / "hermes_cli" / "auth.py").read_text(encoding="utf-8")
    main = (root / "hermes_cli" / "main.py").read_text(encoding="utf-8")
    uninstall = (root / "hermes_cli" / "uninstall.py").read_text(encoding="utf-8")

    assert "requires Hermes" not in profile_distribution
    assert "Hermes distribution" not in profile_distribution
    assert "Hermes relaunch failed" not in relaunch
    assert "re-run hermes" not in relaunch
    assert "Hermes wire shape" not in hooks
    assert "Install Hermes inside WSL2" not in web_server
    assert "rely on Hermes' lazy-install" not in auth
    assert "Close Hermes Desktop" not in main
    assert "No Hermes-owned PATH entries" not in uninstall
    assert "No Hermes-set User env vars" not in uninstall


def test_codex_migration_report_copy_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    text = (
        root / "hermes_cli" / "codex_runtime_plugin_migration.py"
    ).read_text(encoding="utf-8")

    assert "No MCP servers found in Hermes config" not in text
    assert "unknown Hermes key" not in text
    assert "configured by Hermes" not in text
    assert "mcp_servers in Hermes config" not in text


def test_readme_primary_links_are_fork_native():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    before_legacy_docs = readme.split("## Legacy Hermes Documentation", 1)[0]

    assert "docs/plans/2026-05-20-superforecasting-agent-fork-prd.md" in before_legacy_docs
    assert '<a href="LICENSE">' in before_legacy_docs
    assert "github.com/NousResearch/hermes-agent/blob/main/LICENSE" not in before_legacy_docs
    assert "github.com/NousResearch/hermes-agent/issues" not in readme
    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme
    assert "upstream Hermes contributing guide" not in readme


def test_high_attention_help_docs_are_fork_local():
    root = Path(__file__).resolve().parents[1]
    main_py = (root / "hermes_cli" / "main.py").read_text(encoding="utf-8")

    assert "website/docs/user-guide/features/curator.md" in main_py
    assert "website/docs/user-guide/features/fallback-providers.md" in main_py
    assert "https://hermes-agent.nousresearch.com/docs/user-guide/features/curator" not in main_py
    assert (
        "https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers"
        not in main_py
    )


def test_update_upstream_metadata_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    main_py = (root / "hermes_cli" / "main.py").read_text(encoding="utf-8")

    assert "https://github.com/NousResearch/superforecasting-agent.git" in main_py
    assert "superforecasting-agent/archive/refs/heads" in main_py
    assert "official Superforecasting Agent repository" in main_py
    assert "https://github.com/NousResearch/hermes-agent.git" not in main_py
    assert "hermes-agent/archive/refs/heads" not in main_py


def test_model_catalog_default_url_is_forecast_native():
    root = Path(__file__).resolve().parents[1]
    config_py = (root / "hermes_cli" / "config.py").read_text(encoding="utf-8")
    catalog_py = (root / "hermes_cli" / "model_catalog.py").read_text(encoding="utf-8")

    expected = (
        "https://raw.githubusercontent.com/NousResearch/"
        "superforecasting-agent/main/website/static/api/model-catalog.json"
    )
    assert expected in config_py
    assert expected in catalog_py
    assert "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json" not in config_py
    assert "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json" not in catalog_py
