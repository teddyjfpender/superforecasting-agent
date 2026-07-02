import { atom } from 'nanostores'

// The pending g-chord leader. Holds the leader glyph ("g") while we wait ~1.5s
// for the second key, so a tiny footer indicator can show "g …". null when no
// chord is armed. Lives in a store (not a ref) so the indicator re-renders.

export const $chordPending = atom<null | string>(null)

let chordTimer: null | ReturnType<typeof setTimeout> = null

export const clearChord = () => {
  if (chordTimer) {
    clearTimeout(chordTimer)
    chordTimer = null
  }

  if ($chordPending.get() !== null) {
    $chordPending.set(null)
  }
}

// Arm the chord leader and auto-cancel after `ms`. Re-arming resets the timer.
export const armChord = (leader: string, ms = 1500) => {
  if (chordTimer) {
    clearTimeout(chordTimer)
  }

  $chordPending.set(leader)
  chordTimer = setTimeout(() => {
    chordTimer = null
    $chordPending.set(null)
  }, ms)
}
