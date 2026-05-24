Homebrew packaging notes for Superforecasting Agent.

Use `packaging/homebrew/superforecasting-agent.rb` as a tap or `homebrew-core` starting point.

Key choices:
- Stable builds should target the semver-named sdist asset attached to each GitHub release, not the CalVer tag tarball.
- `faster-whisper` now lives in the `voice` extra, which keeps wheel-only transitive dependencies out of the base Homebrew formula.
- The wrapper exports `SUPERFORECASTING_AGENT_BUNDLED_SKILLS` / `FORECAST_BUNDLED_SKILLS` / `HERMES_BUNDLED_SKILLS`, `SUPERFORECASTING_AGENT_OPTIONAL_SKILLS` / `FORECAST_OPTIONAL_SKILLS` / `HERMES_OPTIONAL_SKILLS`, and `SUPERFORECASTING_AGENT_MANAGED=homebrew` / `FORECAST_MANAGED=homebrew` / `HERMES_MANAGED=homebrew` so packaged installs keep runtime assets and defer upgrades to Homebrew.

Typical update flow:
1. Bump the formula `url`, `version`, and `sha256`.
2. Refresh Python resources with `brew update-python-resources --print-only superforecasting-agent`.
3. Keep `ignore_packages: %w[certifi cryptography pydantic]`.
4. Verify `brew audit --new --strict superforecasting-agent` and `brew test superforecasting-agent`.
