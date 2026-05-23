---
sidebar_position: 16
title: "LSP Semantic Diagnostics"
description: "Run language-server diagnostics after file writes."
---

# Language Server Protocol (LSP)

Superforecasting Agent can run full language servers such as pyright, gopls, rust-analyzer, typescript-language-server, clangd, and others as background subprocesses. Their diagnostics are fed into the post-write checks used by `write_file` and `patch`.

For the forecast desk, LSP is engineering support. It helps keep source adapters, benchmark fixtures, model scripts, tests, plugins, and analysis notebooks correct. It does not validate a forecast probability, evidence claim, resolution, score, postmortem, or calibration lesson.

## When LSP Runs

LSP is gated on git workspace detection. When the working directory, or the edited file, is inside a git repository, LSP runs against that workspace. Outside a git repository, LSP stays dormant.

The check is layered:

1. Fast in-process syntax check.
2. Language-server diagnostics when syntax is clean.
3. Silent fallback to syntax-only results if a server is missing, flaky, or unsupported.

On every successful `write_file` or `patch`:

1. The runtime captures baseline diagnostics for the file.
2. It performs the write.
3. It re-queries the language server.
4. It shows only diagnostics introduced by the edit.

Example result:

```json
{
  "bytes_written": 42,
  "dirs_created": false,
  "lint": {"status": "ok", "output": ""},
  "lsp_diagnostics": "LSP diagnostics introduced by this edit:\n<diagnostics file=\"/path/to/source_adapter.py\">\nERROR [42:5] Cannot find name 'fetch_feed' [reportUndefinedVariable] (Pyright)\n</diagnostics>"
}
```

The `lint` field is the syntax result. The `lsp_diagnostics` field is the semantic result from the language server. A syntax-clean file can still produce semantic diagnostics.

## Forecast-Desk Uses

Use LSP when working on:

- forecast source adapters
- benchmark dataset importers
- scoring and calibration code
- model-run scripts
- plugin hooks
- tests for ledger behavior
- TUI/dashboard support code

Do not treat LSP as evidence quality control. A type-correct extractor can still import a stale, misleading, or badly resolved source. Ledger updates still need citations, timestamps, source reliability, assumptions, and review.

## Supported Languages

| Language | Server | Auto-install |
|----------|--------|--------------|
| Python | `pyright-langserver` | npm |
| TypeScript / JavaScript / JSX / TSX | `typescript-language-server` | npm |
| Vue | `@vue/language-server` | npm |
| Svelte | `svelte-language-server` | npm |
| Astro | `@astrojs/language-server` | npm |
| Go | `gopls` | `go install` |
| Rust | `rust-analyzer` | manual |
| C / C++ | `clangd` | manual |
| Bash / Zsh | `bash-language-server` | npm |
| YAML | `yaml-language-server` | npm |
| Lua | `lua-language-server` | manual |
| PHP | `intelephense` | npm |
| OCaml | `ocaml-lsp` | manual |
| Dockerfile | `dockerfile-language-server-nodejs` | npm |
| Terraform | `terraform-ls` | manual |
| Dart | `dart language-server` | manual |
| Haskell | `haskell-language-server` | manual |
| Julia | `julia` + LanguageServer.jl | manual |
| Clojure | `clojure-lsp` | manual |
| Nix | `nixd` | manual |
| Zig | `zls` | manual |
| Gleam | `gleam lsp` | manual |
| Elixir | `elixir-ls` | manual |
| Prisma | `prisma language-server` | manual |
| Kotlin | `kotlin-language-server` | manual |
| Java | `jdtls` | manual |

For manual entries, install the server through the language's normal toolchain. The runtime detects binaries on `PATH` or in the profile LSP bin directory.

Some servers need peer dependencies. For example, `typescript-language-server` needs the `typescript` SDK in the same `node_modules` tree; the installer handles that pairing.

## CLI

```bash
superforecasting-agent lsp status
superforecasting-agent lsp list
superforecasting-agent lsp install <id>
superforecasting-agent lsp install-all
superforecasting-agent lsp restart
superforecasting-agent lsp which <id>
```

`superforecasting-agent lsp status` is the best starting point. It shows which languages will get semantic diagnostics and which need a server binary.

## Configuration

Defaults work for common setups. Configure under `lsp` in `~/.superforecasting-agent/config.yaml`:

```yaml
lsp:
  enabled: true
  wait_mode: document
  wait_timeout: 5.0
  install_strategy: auto
  servers:
    pyright:
      disabled: false
      command: ["/abs/path/to/pyright-langserver", "--stdio"]
      env: { PYRIGHT_LOG_LEVEL: "info" }
      initialization_options:
        python:
          analysis:
            typeCheckingMode: "strict"
    typescript:
      disabled: true
```

Per-server keys:

- `disabled: true` skips that server.
- `command: [bin, ...args]` pins a custom binary and bypasses auto-install.
- `env` adds environment variables for the server process.
- `initialization_options` merges into the LSP `initialize` payload.

## Installation Locations

When `install_strategy: auto`, binaries install into:

```text
~/.superforecasting-agent/lsp/bin/
```

NPM packages land in:

```text
~/.superforecasting-agent/lsp/node_modules/
```

Go binaries install with `GOBIN` pointed at the profile staging directory. Nothing is installed to `/usr/local/`, `~/.local/`, or other shared locations.

During migration, legacy profiles may use `<HERMES_HOME>/lsp/bin` or `~/.hermes/lsp/bin`.

## Performance

LSP servers are lazy-spawned on first use. A Python project may spawn pyright in 1-3 seconds; rust-analyzer can take longer on cold projects.

Subsequent edits in the same workspace reuse the running server. Clean writes typically add only a small delay. When diagnostics are emitted, the wait budget is `wait_timeout`.

Servers stay alive for the life of the process because re-indexing on every write would be more expensive than keeping the daemon.

## Disabling

Disable the whole layer:

```yaml
lsp:
  enabled: false
```

Disable one language:

```yaml
lsp:
  servers:
    rust-analyzer:
      disabled: true
```

When disabled, post-write checks fall back to syntax-only validation.

## Troubleshooting

### `superforecasting-agent lsp status` shows a server as missing

The binary is not on `PATH` and not in the profile LSP bin directory.

Try:

```bash
superforecasting-agent lsp install <server_id>
```

or install the server manually through the language's normal toolchain.

### `Backend warnings` appears in status

Some servers are wrappers around another diagnostic binary. The most common case is `bash-language-server`, which delegates diagnostics to `shellcheck`.

Install the named sidecar:

```bash
apt install shellcheck
brew install shellcheck
scoop install shellcheck
```

The same warning is logged once at server spawn time.

### Server starts but never returns diagnostics

Check:

```bash
superforecasting-agent logs --component lsp
```

or inspect `~/.superforecasting-agent/logs/agent.log` for `[agent.lsp.client]` entries.

Some servers, especially rust-analyzer, need to finish project-wide indexing before they emit per-file diagnostics.

### Server crashed

A crashed server is added to a broken set and is not retried for the rest of the process.

Restart LSP clients:

```bash
superforecasting-agent lsp restart
```

The next matching edit re-spawns the server.

### Editing a file outside a git repo

By design, LSP only runs inside a git repository. Run `git init` to enable semantic diagnostics for that workspace, or accept the syntax-only fallback.
