// The `?` cheat-sheet was absorbed into the unified Help modal (helpOverlay):
// one modal now carries the per-view guide prose AND the grouped shortcut table,
// opened by `h` on every view (with `?` kept as an alias). This thin re-export
// keeps the old names resolving for any lingering import.
export { openHelpOverlay } from '../app/overlayStore.js'
export { HelpOverlay as CheatSheetOverlay } from './helpOverlay.js'
