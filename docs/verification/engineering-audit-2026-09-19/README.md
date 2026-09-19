# Engineering audit evidence

Captured on 19 September 2026 against default-branch commit
`df8e3e33cd4d08c6eaad38a275f6e217e92a3375` in an isolated worktree.

## Static inventory

Run from the repository root using Python 3.11 or newer:

```sh
python docs/verification/engineering-audit-2026-09-19/collect_inventory.py > inventory.json
```

The committed inventory was generated with Python 3.13.12. The collector reads tracked
files, not untracked audit artifacts, and imports no application code. Adding these audit
files to Git changes tracked-file totals; reproduce the historical baseline using the
specified source commit with the collector supplied externally. `source_sha` records HEAD;
use a clean baseline tree because the collector reads working-tree contents.

Physical line counts include comments and blanks. Runtime selection excludes plugins,
skills, scripts and tests. It includes root Python modules and the prefixes listed in the
collector. TUI excludes test/testing directories and generated protocol. Strict coverage
means membership in `scripts/dev.py:STRICT_PYTHON`, not absence of all other checks and not
branch/test coverage. AST decision counts include nested functions and are not McCabe scores.

## Recorded remote checks

Read existing completed job results and failed logs; no polling or rerunning CI.

| Workflow | Observed outcome and evidence |
|---|---|
| [Tests](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602150) | Main test job fails at `test_cmd_model_forwards_nous_login_tls_options`; TUI, e2e, Python 3.12/3.13 and Windows installer jobs succeed |
| [Product quality](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602183) | macOS Node 22 recovery fails with unavailable stable machine identity; other listed installed-product matrix jobs succeed |
| [Docs](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602274) | Reference freshness fails for protocol, tool actions, job types, providers, config/environment |
| [Lint](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602156) | Blocking lint/architecture/actionlint/Windows checks succeed |
| [OSV](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602463) | Lockfile scan and critical-vulnerability blocking job succeed |
| [Nix](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602182) | Linux and macOS jobs succeed |
| [Docker build](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/35441602177) | amd64/arm64 build jobs succeed; channel-moving jobs are skipped |

`gh api repos/teddyjfpender/superforecasting-agent/commits/<sha>/check-runs` supplies job
status and URLs. `gh run view <run-id> --log-failed` supplies the failure evidence.
Paginated Dependabot alert inspection returned zero alerts with state `open` at capture.
These are point-in-time observations, not an ongoing release certification.

## Verification of this deliverable

Only planning documents and the inventory collector were added. Validate collector syntax,
Ruff formatting/lint, inventory JSON, baseline counts, Markdown relative links and whitespace.
The application suite is intentionally not repeated for this documentation-only deliverable.
No profile data, credentials, private messages or raw provider payloads are included.

See the [audit](../../plans/2026-09-19-engineering-audit.md) and
[implementation specification](../../plans/2026-09-19-engineering-improvement-specification.md).
