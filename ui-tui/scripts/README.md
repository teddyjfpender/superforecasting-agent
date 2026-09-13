# Terminal build and verification scripts

Contains tooling for terminal development, bundle builds and behavioral verification.

## Ownership and boundaries

Keep build artifacts separate from source and distinguish renderer checks from native installed-product verification.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                           | Responsibility                                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------- |
| [gen-header.py](gen-header.py) | Convert an image into a high-resolution, theme-agnostic luminance bitmap for the TUI header. |

## Working in this directory

From the repository root, run:

```sh
npm --prefix ui-tui run type-check
npm --prefix ui-tui run lint
npm --prefix ui-tui test
```

For input, resize or shutdown changes, also run the relevant installed-terminal
verification on the affected native platform; renderer tests do not establish
ConPTY or PTY behavior.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
