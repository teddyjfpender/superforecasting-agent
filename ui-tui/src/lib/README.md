# Terminal support functions

Contains reusable terminal formatting, caches, grouping and platform helpers.

## Ownership and boundaries

Prefer focused pure helpers. Forecast business state stays in the Python
application owners. Existing personal Signal and local Docs integrations live
here: `messagingSend.ts` centralizes sends, `signalLive.ts` owns the receiver,
`messagingState.ts` persists chat organization and drafts, and
`documentDrafts.ts` stores recoverable editor snapshots. These profile-local
owners are not a multi-device service. Components must reuse them rather than
write their files or send directly.

See the [desk architecture](../../../../docs/architecture/messaging-docs-desk.md)
for failure behavior and integration boundaries.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                       | Responsibility    |
| ------------------------------------------ | ----------------- |
| [accentSweep.ts](accentSweep.ts)           | accentSweep.      |
| [audiogram.ts](audiogram.ts)               | audiogram.        |
| [buildInfo.ts](buildInfo.ts)               | buildInfo.        |
| [circularBuffer.ts](circularBuffer.ts)     | circularBuffer.   |
| [clipboard.ts](clipboard.ts)               | clipboard.        |
| [cursorVisibility.ts](cursorVisibility.ts) | cursorVisibility. |
| [deskGroups.ts](deskGroups.ts)             | deskGroups.       |
| [docsCli.ts](docsCli.ts)                   | docsCli.          |

## Subdirectories

- [viz/](viz/README.md) — Terminal chart engine.

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

Signal contact discovery is owned by `signalDirectory.ts` (shared refresh and
reactive cache). `signalContacts.ts` preserves name provenance and local labels;
`messagingSearch.ts` ranks names, categories and saved message context without
external AI calls. See [Signal behavior and tests](../../../../docs/verification/signal-messaging.md).

## Data desk lifetimes

- `deskViewCache.ts` owns bounded, in-memory snapshots keyed by the backend
  connection and active profile/attach address, not by a mounted React view.
  Reattaching a client in place creates a new cache scope; late replies stay in
  their original scope. Different backend/profile clients never share caches. Restarting the TUI starts a new connection cache.
- `marketFetch.ts` coalesces identical pending quote requests. Replies still warm
  their original connection after navigation, while aborted views cannot repaint.
  Source-specific freshness remains authoritative; values stay visible during refresh.
- `newsDesk.ts` retains parsed feeds for ten minutes and reader bodies for thirty,
  deduplicates pending acquisitions, and backs off feed failures for one minute.
  Explicit refresh bypasses feed freshness/backoff. Failed refreshes retain the
  last successful contents and acquisition time.
- `feedShare.ts` validates and serializes portable message snapshots against the
  generated `protocol/feed_share.py` types. `feedShareChart.ts` renders bounded
  charts; `FeedShareCard` presents them without network or ledger effects.
- `pmListCache.ts` retains prediction-market browse snapshots per connection and
  venue for thirty seconds. Explicit refresh and a backend refresh-in-progress
  bypass freshness; stream subscriptions still stop when the view leaves.
