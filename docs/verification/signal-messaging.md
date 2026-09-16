# Signal contacts and messaging

## Using the desk

- Press **f** in the Messaging chat list to find a contact or conversation.
  **n** opens the same picker for a new chat. Enter a full `+countrycode` number
  for someone not already listed.
- Type a name, nickname, category or topic. Search runs locally across saved
  names and messages, with accent folding, partial matches, small name typos
  and related terms (for example, “inflation” finds discussions of CPI).
  Exact names rank first. This is deterministic intent search, not embeddings.
- **Tab / left / right** change scope; **up / down / Page Up / Page Down**
  move through results; **Enter** opens the selected chat. The detail area
  shows the recipient identifier and a matching message before selection.
- **Ctrl+R** in the picker requests contact/group synchronization from your
  phone. Keep the phone connected. Results refresh every 15 seconds while the
  Messaging view or a picker is open. Failures retain cached contacts.
- **Ctrl+B** from the new-chat picker starts a group; **Ctrl+F** in the group
  form finds members. Creating the group is an explicit final action.
- **c** edits a local display name. Signal names and nicknames remain visible
  on the contact card and searchable; synchronization preserves your label.
- Quick compose uses the same picker. Selecting a recipient does not send a
  message; review the identifier and draft before **Ctrl+Enter**.

The conversation lists exclude contacts and groups with no captured messages,
nonempty draft or outstanding send attempt. Empty recipients remain discoverable
through **f/n**; opening one lets you write without adding an empty chat to the
list. Leaving it blank returns to the uncluttered list.

## Composer and message status

The chat composer expands as text wraps, up to six visible rows on large
terminals, then scrolls internally. **Enter** sends; **Shift+Enter** inserts a
newline. Quick compose uses **Ctrl+Enter** to send and **Enter** for a newline.
**Left** at the start of the draft returns to navigation; **Esc** returns from
any cursor position. Both preserve the draft.

Message status lives beside the message: **◷** pending, **✓** accepted by the
Signal send operation, **!** delivery unconfirmed. A tick does not imply a
recipient delivery/read receipt. Unconfirmed sends retain the draft and show
the error inside the conversation; retries remain explicit. Pending indicators
are process-local; after a restart, retained drafts must be checked against the
conversation before retrying.

## Names and history

Signal contact names, nicknames and available profile names come from
[`listContacts`](https://github.com/AsamK/signal-cli/blob/master/src/main/java/org/asamk/signal/json/JsonContact.java).
The desk requests all known recipients, caches resolved names and refreshes
contact/group lists after linking. [`sendSyncRequest`](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc)
asks the primary phone for contacts and groups; it does not import messages.
Unknown identities stay as numbers/UUIDs. Message text is never used to guess
someone's identity.

Phone-history transfer remains an [upstream enhancement](https://github.com/AsamK/signal-cli/issues/1708).
This desk retains messages received while connected and successful local sends,
including sends mirrored from another linked device. It keeps up to **500
messages per conversation** in the active profile. It cannot retrieve messages
that signal-cli already consumed while the desk was disconnected. Use a separate
profile for each Signal account; account migration is not implemented.

Contact labels and message caches are local, atomically written with owner-only
permissions. Search does not call an AI provider or export your address book.
Older labels without provenance remain local labels to avoid overwriting edits.

## Engineering ownership and verification

| Owner | Responsibility |
| --- | --- |
| `signalClient.ts` | Signal JSON parsing and RPC errors |
| `signalContacts.ts` | Address-book persistence and name precedence |
| `signalDirectory.ts` | Reactive directory, shared refresh, sync and stale-result guards |
| `messagingSearch.ts` | Pure local ranking and scopes |
| `contactPicker.tsx` | Shared bounded browse/search/select interaction |
| `signalLive.ts` | Single app-wide receiver and durable message cache |

Fixtures cover nickname/profile alternatives, UUID-addressed mirrored sends,
manual-label precedence, failed/stale refreshes, shared polling cleanup, topic
ranking, malformed recipient queries and terminal picker interaction at 80×24
and 120×40. QR tests cover quiet zones, constrained terminals and resize without
restarting linking. Tests use synthetic contacts and controllable providers;
they do not send messages from a real account.
