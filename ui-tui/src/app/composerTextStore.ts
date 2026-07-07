import { computed, map } from 'nanostores'

// The composer's live text (the single field that changes on every keystroke)
// lives HERE, out of the AppLayout prop tree, so a keypress updates only the
// components that subscribe to this store — the composer's own input subtree —
// and never re-renders AppLayout, the NavBar, the hero, the Today panel, or the
// status bar. useComposerState keeps the canonical React state (all the submit /
// keyboard / slash consumers read it synchronously and unchanged); it mirrors
// input + inputBuf here so the display path can read them reactively without
// dragging the whole frame through a re-render.
export interface ComposerText {
  input: string
  inputBuf: string[]
}

export const $composerText = map<ComposerText>({ input: '', inputBuf: [] })

/** Mirror the canonical composer text into the store. No-op when unchanged so a
 *  redundant sync never notifies subscribers. */
export const syncComposerText = (input: string, inputBuf: string[]) => {
  const cur = $composerText.get()

  if (cur.input !== input || cur.inputBuf !== inputBuf) {
    $composerText.set({ input, inputBuf })
  }
}

export const setComposerInput = (input: string) => {
  if ($composerText.get().input !== input) {
    $composerText.setKey('input', input)
  }
}

export const resetComposerText = () => {
  const cur = $composerText.get()

  if (cur.input !== '' || cur.inputBuf.length) {
    $composerText.set({ input: '', inputBuf: [] })
  }
}

// Coarse "the composer is empty" boolean. AppLayout's landing soft-focus gate
// needs to know whether the composer is armable (empty), but NOT the text
// itself — a computed atom only notifies when the boolean flips, so AppLayout
// re-renders on empty→typed (rare), never per keystroke. When input is empty
// completions are empty too (completion only fires on non-empty input), so this
// matches the old `!completions.length && !inputBuf.length && !input` predicate.
export const $composerArmable = computed(
  $composerText,
  ({ input, inputBuf }) => input.length === 0 && inputBuf.length === 0
)
