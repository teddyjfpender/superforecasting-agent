# Canonical identity and compatibility boundaries

New product APIs, commands, documentation and profile creation use
`superforecasting_agent`, `superforecasting-agent`, Superforecasting Agent and
`~/.superforecasting-agent`. Compatibility is input translation to those owners;
it must not become a second implementation or a second writable configuration.

| Retained identity | Boundary and reason |
| --- | --- |
| `hermes`, `setup-hermes.sh`, `scripts/hermes-gateway` | Thin launch adapters to canonical entry points; existing automation remains callable |
| `nix/hermes-agent.nix` | Imports the canonical package expression |
| `agent/transports/hermes_tools_mcp_server.py` | Imports the canonical forecast tools MCP entry point |
| `HermesCLI`, `hermes_client_tag`, legacy OAuth/LSP/configuration exports and `HermesTokenStorage` | Explicit aliases to canonical implementations for downstream imports |
| `HERMES_HOME`, `FORECAST_HOME`, `.hermes` | `superforecasting_agent/constants.py` resolves profile roots, with the canonical variable taking precedence; existing homes are not silently moved |
| Other `HERMES_*` variables | Existing feature-specific alias resolvers accept these at environment boundaries; internal callers should use the canonical resolver |
| `metadata.hermes`, installed plugin identifiers | Published extension schema; changing identifiers would break user plugin configuration and skill metadata |
| `plugins/hermes-achievements` | Existing optional plugin identity, not the forecasting product's default identity |
| `hermes-*` toolset presets | `superforecasting_agent/tooling/catalogs/legacy.py` and `aliases.py`; canonical catalogs own membership |
| Three legacy skill names | Frontmatter aliases on canonical directories; no duplicate bundled directory is maintained |
| Three legacy generated skill-page URLs | `website/scripts/generate-skill-docs.py::page_id` preserves published identifiers separately from canonical source paths |
| Hermes model names, upstream URLs and license attribution | Refer to actual third-party models or upstream provenance; do not rebrand them |
| `.github/actions/hermes-smoke-test` | Published composite-action path; visible identity and executed commands are canonical |
| `hermes_tools`, `hermes-tools` | Saved sandbox scripts share the canonical `forecast_tools` module through an adapter; persisted MCP server identifiers retain their migration boundary |
| `plugins/kanban/systemd/hermes-kanban-dispatcher.service` | Explicitly deprecated standalone compatibility service; canonical operation runs inside the gateway |
| Historical migration filenames and tests | Describe the compatibility behavior being exercised, rather than new product entry points |

The bundled directories are now `autonomous-ai-agents/superforecasting-agent`,
`software-development/superforecasting-agent-skill-authoring` and
`software-development/debugging-superforecasting-tui-commands`. Old slash commands
resolve through their declared aliases. Disabled legacy skill names must still
suppress the corresponding canonical skill. User-owned skills are not rewritten.

Regression coverage: `tests/test_constants.py` covers native/legacy/custom profile
roots, including service environments without an OS user home;
`tests/agent/test_skill_commands.py` checks actual moved bundled skills and legacy
alias disable behavior. `tools/skills_sync.py::_migrate_bundled_path` moves only
unchanged manifest-owned copies, carries old manifest keys and deletion intent,
and retains customized or conflicting copies for explicit reset. Sync and reset
share a cross-process manifest lock. `tests/tools/test_skills_sync.py` exercises
these migrations, retries and a competing process. Existing profile, configuration and plugin tests remain
part of the mandatory full suite.

Private runtime helpers now use agent names across gateway updates, Windows
shim ownership, Kanban dispatch, credential discovery, environment loading and
LSP installation. Internal callers use canonical public OAuth/LSP/configuration
exports; legacy exports remain at their owning modules for installed plugins.
LSP staging uses the shared profile resolver, and gateway updates prefer the
canonical executable. Windows PATH cleanup matches exact owned directories,
including the canonical installation, rather than unrelated prefix matches.

Do not perform global string replacement over persisted identifiers. Rename private
helpers and stale product copy directly; retain externally observable aliases at
an explicit boundary until an independently tested migration replaces them.

The MCP OAuth owner is `tools.mcp_oauth.AgentTokenStorage`; its legacy class
export is the same class, preserving stored tokens and client registration.
Private home, provider, environment-filter, user-agent and session-log helpers use
canonical names. Retained public storage constants and keyword parameters named
`hermes_home` remain compatibility inputs; their values resolve through the
canonical profile owner. They do not select a separate legacy storage tree.
