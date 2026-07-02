import { useEffect } from 'react'

// Centralized hardware-cursor ownership.
//
// A terminal shows its hardware (blinking) cursor by default, and Ink parks it
// wherever it last drew each frame. A fullscreen view with no focused text input
// therefore leaves a STRAY cursor blinking at the bottom-left. The old fix was
// ad hoc: a handful of views each wrote `\x1b[?25l`/`?25h` in their own effects,
// which (a) left the un-copied views (Desk, Calendar, Calibration, Hooks) with a
// stray cursor and (b) fought across view switches — one view's unmount cleanup
// re-showed the cursor the next view never re-hid.
//
// The ownership is now split in exactly two places:
//   • useHideCursorWhileFullscreen — the LAYOUT-level owner. Hides the cursor
//     while ANY fullscreen view is mounted; restores it on return to the
//     landing/composer.
//   • useInputCursor — the INPUT-level exception. The focused text field shows
//     the cursor while typing and re-hides it on blur/unmount. It runs AFTER the
//     layout mount-hide, so a text field placed inside a fullscreen view still
//     re-shows the cursor while typing and leaves the view's hidden state intact
//     once it blurs.

const HIDE = '\x1b[?25l'
const SHOW = '\x1b[?25h'

// The minimal write surface we need — matches Node's WriteStream and the fake
// stdout the unit tests drive.
export interface CursorStream {
  isTTY?: boolean
  write: (data: string) => unknown
}

export const hideHardwareCursor = (stdout?: CursorStream | null): void => {
  if (stdout?.isTTY) {
    stdout.write(HIDE)
  }
}

export const showHardwareCursor = (stdout?: CursorStream | null): void => {
  if (stdout?.isTTY) {
    stdout.write(SHOW)
  }
}

// LAYOUT-LEVEL OWNER. Hide the hardware cursor while `fullscreen` is true (any
// fullscreen view is mounted) and restore it when it goes false (return to the
// landing/composer). This is the single owner — no view writes cursor escapes.
export function useHideCursorWhileFullscreen(fullscreen: boolean, stdout?: CursorStream | null): void {
  useEffect(() => {
    if (!fullscreen || !stdout?.isTTY) {
      return
    }

    hideHardwareCursor(stdout)

    return () => showHardwareCursor(stdout)
  }, [fullscreen, stdout])
}

// INPUT-LEVEL EXCEPTION. The focused text field owns the cursor while it is the
// active field: SHOW it (positioned by useDeclaredCursor) when a native cursor
// is wanted, and HIDE it otherwise (selection, terminal-blur, field blur). A
// separate unmount hide leaves the view's hidden cursor state intact when a field
// mounted inside a fullscreen view goes away while it was still showing.
export function useInputCursor(showNativeCursor: boolean, stdout?: CursorStream | null): void {
  // Reflect the current show/hide state on every change (no cleanup here, so a
  // simple show→hide toggle writes exactly one escape).
  useEffect(() => {
    if (!stdout?.isTTY) {
      return
    }

    stdout.write(showNativeCursor ? SHOW : HIDE)
  }, [showNativeCursor, stdout])

  // On unmount, re-hide so a field that goes away while showing does not strand a
  // visible cursor over a fullscreen view.
  useEffect(() => {
    if (!stdout?.isTTY) {
      return
    }

    return () => hideHardwareCursor(stdout)
  }, [stdout])
}
