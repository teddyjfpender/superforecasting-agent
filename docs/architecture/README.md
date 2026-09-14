# Architecture references

This directory describes the current product boundaries and the engineering
constraints that keep the forecast ledger, agent runtime, and user interfaces
independently maintainable.

Start with the [ownership map](ownership-map.md) to locate the owner of a behavior
before changing a caller. The [research runtime controls](research-runtime-controls.md)
cover background review budgets, MCP response limits, and model-selection notices.
The [gateway protocol](../../protocol/README.md) is the reference for the shared
Python/TypeScript API and interactive prompt recovery.

## Maintaining these references

Describe current behavior and public contracts here. Keep implementation receipts
and completed milestones in `docs/plans/`; keep actionable engineering work in
[`TODO.md`](../../TODO.md). Explain compatibility adapters explicitly instead of
presenting inherited names as new product boundaries.

When changing an owner, update its directory README, affected consumer contracts,
and the relevant boundary tests. The TUI is a consumer of shared application
behavior; desktop and remote hosting should not require separate implementations
of forecasting operations.

[↑ Documentation](../../README.md)
