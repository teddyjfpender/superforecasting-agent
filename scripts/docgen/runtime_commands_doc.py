"""Inventory the actual built-in runtime parser without entering CLI startup."""

from functools import partial

from scripts.docgen.cli_reference_doc import _subparsers_action
from scripts.docgen.common import header


def render() -> str:
    from superforecasting_agent.runtime.main import build_runtime_parser

    parser, _ = build_runtime_parser(include_plugins=False)
    lines = [
        header(
            "Runtime command inventory",
            "superforecasting_agent/runtime/main.py (build_runtime_parser)",
            blurb="Built-in command paths, parser aliases and bound dispatch callbacks, derived from the same parser used at runtime.",
        ),
        "Plugin commands are intentionally excluded from this built-in inventory: they depend on installed plugins and the active profile. The CLI opts into discovery for possible plugin invocations; metadata inspection does not execute plugin registration hooks.",
        "",
        "The output column records parser flags only. It does not establish a machine-output schema, noninteractive completion, or parity with messaging/TUI. A parent callback is inherited where a subcommand does not bind a separate handler. See [slash-command surfaces](command-surfaces.md) for the separate interactive registry.",
        "",
        "## Entrypoint routing",
        "",
        "This is the runtime parser inventory, not an exhaustive public routing table. `superforecasting_agent/cli.py::main` handles version flags, `tui`, environment-enabled desk startup, profile import and `snapshot` before runtime parsing. It also routes forecast shorthand (including overlapping names such as `status`) to the forecast parser; runtime `config` remains separate from forecast `config doctor`. See the [forecast reference](cli-reference.md). The callbacks below describe runtime-parser bindings, not proof that every same-named public invocation reaches them.",
        "",
        "## Runtime parser bindings",
        "",
        "| Command | Parser aliases | Dispatch callback | Output flag |",
        "| --- | --- | --- | --- |",
    ]

    def visit(node, path, parent_handler=None):
        handler = node._defaults.get("func", parent_handler)
        action = _subparsers_action(node)
        if action is None:
            return
        seen = set()
        for name, child in action.choices.items():
            if id(child) in seen:
                continue
            seen.add(id(child))
            aliases = [
                alias
                for alias, candidate in action.choices.items()
                if candidate is child and alias != name
            ]
            owner = child._defaults.get("func", handler)
            target = owner
            while isinstance(target, partial):
                target = target.func
            if callable(target):
                owner_name = f"{target.__module__}.{getattr(target, '__qualname__', type(target).__qualname__)}"
            else:
                owner_name = "parent dispatch / help"
            flags = sorted({
                option
                for item in child._actions
                for option in item.option_strings
                if option in {"--json", "--format", "--output-format"}
            })
            command = " ".join((*path, name))
            alias_text = ", ".join(f"`{alias}`" for alias in aliases) or "—"
            output = ", ".join(f"`{flag}`" for flag in flags) or "not declared here"
            lines.append(f"| `{command}` | {alias_text} | `{owner_name}` | {output} |")
            visit(child, (*path, name), owner)

    visit(parser, ("superforecasting-agent",))
    return "\n".join(lines) + "\n"
