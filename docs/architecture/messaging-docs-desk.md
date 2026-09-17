# Messaging and Docs desk

These views extend the terminal desk's dense, keyboard-first visual system.
Collections stay on the left, the selection in the middle, and readable content
on the right. Small terminals collapse the collection rail into keyboard
navigation. Existing themes, including Terminal Amber, supply all colors.

## Messaging

The dedicated Messaging route is a personal **Signal** client, separate from the
agent's messaging gateway. No Telegram personal-account support is implied.

- **Inbox / Unread / Pinned / Groups / Archived / named categories** organize the
  same stable conversation IDs. `Tab` cycles collections, `/` searches, `p` pins,
  `x` archives/restores, and `C` assigns a category. `c` edits a contact.
- `Enter` opens a conversation with the composer focused. `Esc` returns to the
  list with the draft retained. `PgUp/PgDn` scrolls history independently.
- The navigation badge counts **unread conversations**, not unread messages.
  Reading older history or covering a conversation with a modal does not mark
  incoming messages as read. Read state survives restart.
- **Alt+M**, or the header's Message action, opens quick compose over any view.
  Markets, News, Docs and the inbox also accept plain `m` when browsing. Text
  fields retain ordinary typing. Markets model selection moves to `M`.
- Quick compose searches saved contacts, groups and categories; a valid E.164
  number can start a direct conversation. `Enter` selects the recipient,
  `Ctrl+Enter` sends, `Tab` changes recipient and `Esc` keeps the draft.
  A selected market, article or document is snapshotted for forwarding, previewed
  before send and removable with `Ctrl+R`. News forwards its source link; Docs
  forwards a labelled excerpt of at most 2,000 characters.

### Ownership and failure behavior

| Owner | Responsibility |
| --- | --- |
| `lib/signalLive.ts` | One receiver, message cache, durable unread markers, stale receiver generation rejection. |
| `lib/messagingState.ts` | Atomic profile-local drafts and organization, plus temporary quick-compose state. |
| `lib/signalContacts.ts` | Stable address book and user-supplied names. |
| `lib/messagingSend.ts` | Shared send validation, one in-flight send per account/conversation, confirmed local echo. |
| `lib/useShareItem.ts` | The mounted view's selected forwarding context. |
| `components/quickMessage.tsx` | Recipient selection, preview and explicit send. |

A failed send retains its draft. Ambiguous transport failures are never retried
automatically: users check the conversation before retrying. Storage failures
surface explicitly. No test sends messages to real contacts.

Signal history is the existing profile-local cache (500 persisted messages per
chat); signal-cli does not provide historical backfill. Metadata is owned by the
TUI process for that profile. This does not add server-side multi-device sync.

## Docs

The default surface is a library, document list and independently scrolling
reader. `1` selects Obsidian, `2` selects Overleaf/LaTeX. `Tab` cycles folders,
`/` filters titles and paths, `↑↓` selects documents, and `PgUp/PgDn` scrolls the
reader. Selecting a document starts its reader at the top.

The shared Markdown renderer supports headings, emphasis, tables, lists/tasks,
code highlighting, quotes, links, wiki links and math. Frontmatter is excluded
from the reading body. Wiki links open an unambiguous matching note; ambiguous
or missing matches report an error rather than selecting a guessed target.
LaTeX uses the existing terminal renderer, not a claim of PDF typesetting parity.

`e` edits with the shared text input (cursor movement, selection, paste and undo),
`Ctrl+Enter` saves and `Esc` returns to preview. Drafts checkpoint locally and
recover after leaving the view or restarting. Truncated previews cannot be saved.
Source changes reject stale saves; recovered edits are preserved for reconciliation.
`R` reviews the current source: explicitly keep the draft as a replacement or
discard it in favour of the source, then save separately.

`c` opens a compact Connections modal. Obsidian uses the backend's resolved vault
(`OBSIDIAN_VAULT_PATH` or the managed vault). Overleaf/Git uses the existing local
Docs workspace and authenticated Git/olcli tools. Pull refuses a dirty workspace
and uses fast-forward-only Git. Publishing explicitly confirms that all workspace
changes will be committed and pushed. Authentication stays with those tools;
remote URLs containing embedded credentials are rejected.

### Ownership

| Owner | Responsibility |
| --- | --- |
| `components/documentDesk.tsx` | Selection, folder navigation, loading generations and editing actions. |
| `components/documentReader.tsx` | Bounded Markdown/LaTeX rendering, independent scroll. |
| `components/documentConnections.tsx` | Explicit connection and sync actions. |
| `lib/documentDrafts.ts` | Profile-local recovery snapshots keyed by source identity. |
| `protocol/rpc/obsidian.py`, `tui_gateway/obsidian_rpc.py` | Typed vault RPC contracts and error propagation. |
| `plugins/obsidian/vault.py` | Shared locked, atomic writes and stale-edit rejection. |
| `lib/latexDocs.ts`, `lib/docsCli.ts` | Local LaTeX files and existing Git/olcli subprocess operations. |

Obsidian writes reuse the storage package's cross-process lock and atomic writer.
External editors do not participate in that advisory lock; the expected-content
check catches changes already present when a save starts. LaTeX performs the same
stale-content check before atomic replacement. Collaborative CRDT editing is not
part of this terminal desk.

## Qualification

Review with isolated profiles and controllable transports: draft persistence,
duplicate send suppression, unread restart/reconnect behavior, stale receiver
callbacks, rapid document selection, conflict rejection and independent scrolling.
Real Signal delivery and credentialed Overleaf synchronization require configured
accounts; component tests and local Git fixtures do not claim those integrations
were exercised against a user's accounts.

## Sharing a data feed

On Markets, select a numeric feed and press **m**, choose a recipient, then
review the live chart preview before **Ctrl+Enter** sends it. A caption is optional.
The modal shows the send shortcut and chart/horizon controls; its preview adapts
to terminal height and updates when the presentation or horizon changes.
**Shift+Tab** focuses chart settings: left/right changes bar/line presentation;
up/down selects the latest 6, 12, 24 or 120 observations; Enter returns to writing.
**Ctrl+R** includes/excludes the forwarded item. Sparse observations keep their
actual periods, and a source with only one dated reading displays that limitation.

[`protocol/feed_share.py`](../../protocol/feed_share.py) defines `sfa.feed` versions
1 (calendar periods) and 2 (calendar periods or exact UTC timestamps); TypeScript declarations are generated with the other contracts. The text wire
format is a readable caption followed by a fenced `sfa-feed` JSON block. It works
through Signal's existing text send/receive and history persistence. A future
Telegram adapter can carry the same body without changing chart semantics.
Ordinary clients see the readable caption and JSON; the TUI renders a chart card.
This is **not** a native chart attachment in the Signal phone application.

The payload specifies presentation, an explicit date/time horizon and up to four
feeds, each with provider/series identity, name, unit, kind, revision policy,
public source URL, retrieval time and dated numeric/null observations. Rendering
accepts at most 48 KiB, 120 observations per feed and nonoverlapping chronological
periods. Missing observations remain gaps; horizontal spacing uses actual period-end dates.
Bars use a zero baseline. Each feed
has its own scale; incompatible units are never combined. All text fields reject
terminal control characters. Outgoing source URLs omit queries and fragments.

Snapshots are **sender-supplied claims**, labelled "Shared snapshot". Receiving
one never runs code, fetches a URL, subscribes to a feed or creates settlement
provenance. Unknown versions and malformed payloads remain ordinary text. Shared
Python/TypeScript fixtures cover the boundary. New versions must retain this
fallback, and transport adapters must preserve the complete message body.

Version 2 preserves hourly weather readings and prediction-market price history;
no daily aggregation or invented dates are applied. Calendar-only feeds continue
to emit v1. Older clients display unsupported v2 snapshots as caption plus JSON.
A snapshot must use one consistent time precision and ordered, nonoverlapping
periods. Offset timestamps are converted to UTC without changing the instant.

Prediction-market sharing uses the selected outcome's fetched raw YES-price
history, expressed as percentages, with the venue and contract identity. It does
not substitute the event's normalized distribution or a live tick for history.
History belongs to a backend/profile, event, contract and requested range; old
responses cannot be attached to a replacement selection. While history is
unavailable, forwarding remains text-only with an explicit explanation; close
and reopen the composer once history loads to capture a fresh snapshot.
