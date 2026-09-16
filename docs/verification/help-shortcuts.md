# Help and footer shortcut audit

The shared Help modal is the only popup for `?` on Home. `/help` and the Help
navigation tab remain the full reference view. The old inline `HelpHint` was removed.

## Input ownership

- Home intercepts `?` only with an empty composer and no completion menu.
- Every browsing view handles `h` and `?` after its local editing/search/modal guards.
  Punctuation in a search, message or document stays ordinary text.
- Global `Ctrl+K`, `Ctrl+G` and `Alt+M` consume their events so they cannot also
  mutate an editor. On Linux/Windows, use `Alt+G` for the external editor.
- The Help modal consumes its own keys and blocks underlying views. Its current
  view shortcuts precede the global reference; descriptions wrap and scroll.

## Reviewed surfaces

| Surface | Modes checked against handlers and footer rows |
| --- | --- |
| Home / full Help | Empty composer, Today focus, completion, global modal, help scrolling |
| Desk | Forecast/lens navigation, selection actions, detail, settings and tasks |
| Markets | Data, Prediction, Models list/detail/chat, provider/filter modals |
| News | Sources, headline selection, search, reader, feed/starter modals |
| Messaging | Collections, search, contacts/groups, composer, setup and category forms |
| Docs | Collections, folders, search, reader, editor, reconciliation and connections |
| Warnings | Tiers, contested labels, passes and dismissal form |
| Calendar | Grid, agenda, filter and day popover |
| Calibration | Scroll/page/top/bottom, refresh and close |
| Agents | List/detail, sorting, filtering, history and supported delegation controls |
| Hooks | List/inspector, severity/profile, reference, rule wizard and removal |
| Demo visualization | Development-only scrolling and close |

The legacy Markdown and LaTeX components retain guarded `?` aliases, but their old
outline/wiki-link/git shortcut maps no longer describe the default Docs surface.

## Footer contract

`useViewInput` registers the keyboard handler and returns the same guarded handler
for footer actions. `FooterChips` uses it for unambiguous single-action keys that
lack an explicit callback. Existing explicit callbacks remain for compound or
context-dependent actions. Every shortcut uses brackets, including combined navigation hints such as
`[PgUp/Dn Read]`. Only unambiguous actions dispatch mouse clicks. Quick Message
lives in the bottom shortcut rows, not the page-navigation bar. Covered or disabled footers never dispatch.

This closes previously inert clicks for model actions, News Open, Hooks actions,
and Messaging pin/archive/category. Markets uses `M` for Models and `m` for messaging.

## Evidence and limits

`footerActions.test.tsx` checks shared dispatch, disabled actions, modifier fidelity,
non-action hints and wiring across view owners. Existing rendered-view tests cover
modal key trapping, help expansion/scrolling and single-footer layout. Registry tests
check current descriptions and route coverage. The Docs interaction test verifies
that help punctuation is preserved while editing and opens Help after leaving it.

This audit checks local dispatch and UI behavior. It does not claim successful live
provider calls, message delivery or external publishing for every advertised action.
