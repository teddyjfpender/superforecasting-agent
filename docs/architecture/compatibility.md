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
| `HermesCLI`, `hermes_client_tag` | Explicit aliases to canonical implementations for downstream imports |
| `HERMES_HOME`, `FORECAST_HOME`, `.hermes` | `superforecasting_agent/constants.py` resolves profile roots, with the canonical variable taking precedence; existing homes are not silently moved |
| Other `HERMES_*` variables | Existing feature-specific alias resolvers accept these at environment boundaries; internal callers should use the canonical resolver |
| `metadata.hermes`, installed plugin identifiers | Published extension schema; changing identifiers would break user plugin configuration and skill metadata |
| `plugins/hermes-achievements` | Existing optional plugin identity, not the forecasting product's default identity |
| `hermes-*` toolset presets | `superforecasting_agent/tooling/catalogs/legacy.py` and `aliases.py`; canonical catalogs own membership |
| Three legacy skill names | Frontmatter aliases on canonical directories; no duplicate bundled directory is maintained |
| Three legacy generated skill-page URLs | `website/scripts/generate-skill-docs.py::page_id` preserves published identifiers separately from canonical source paths |
| Hermes model names, upstream URLs and license attribution | Refer to actual third-party models or upstream provenance; do not rebrand them |
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

Do not perform global string replacement over persisted identifiers. Rename private
helpers and stale product copy directly; retain externally observable aliases at
an explicit boundary until an independently tested migration replaces them.
