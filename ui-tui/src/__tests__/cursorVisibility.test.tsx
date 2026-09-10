import { PassThrough } from 'stream'

import React, { act } from 'react'
import { describe, expect, it } from 'vitest'

import { type CursorStream, useHideCursorWhileFullscreen, useInputCursor } from '../lib/cursorVisibility.js'

// The centralized hardware-cursor ownership. Two owners:
//   • useHideCursorWhileFullscreen — the LAYOUT owner: hides while any fullscreen
//     view is mounted, restores on the way back to the landing/composer.
//   • useInputCursor — the INPUT exception: the focused text field shows the
//     cursor while typing and re-hides on blur / unmount.
// The raw escapes are impractical to assert through the render pipeline (the
// non-TTY harness keeps cumulative frames), so we drive the hooks directly with a
// fake stdout that captures every write. `act()` flushes passive effects (and
// their unmount cleanups) deterministically.

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const HIDE = '\x1b[?25l'
const SHOW = '\x1b[?25h'

// A capture stream the hooks write to (separate from Ink's own stdout).
const fakeCursor = (isTTY = true): CursorStream & { writes: string[] } => {
  const writes: string[] = []

  return {
    isTTY,
    write: (data: string) => {
      writes.push(data)

      return true
    },
    writes
  }
}

// A minimal Ink stdout so render() has somewhere to paint (unrelated to the
// captured cursor stream above).
const inkStdout = () => {
  const stream = new PassThrough() as PassThrough & {
    columns: number
    isTTY: boolean
    rows: number
  }

  Object.assign(stream, { columns: 80, isTTY: false, rows: 24 })
  stream.on('data', () => undefined)

  return stream
}

const renderProbe = async (element: React.ReactElement) => {
  const { render } = await import('@superforecasting/ink')
  // `render` is async — await it to get the real Instance (rerender/unmount);
  // otherwise `instance` is a Promise and those handles are undefined.
  let instance!: Awaited<ReturnType<typeof render>>
  await act(async () => {
    instance = await render(element, { exitOnCtrlC: false, patchConsole: false, stdout: inkStdout() as never })
  })

  return {
    cleanup: () => {
      instance.unmount?.()
      instance.cleanup?.()
    },
    rerender: async (next: React.ReactElement) => {
      await act(async () => {
        instance.rerender?.(next)
      })
    },
    unmount: async () => {
      await act(async () => {
        instance.unmount?.()
      })
    }
  }
}

describe('useHideCursorWhileFullscreen (layout owner)', () => {
  function LayoutProbe({ cur, fullscreen }: { cur: CursorStream; fullscreen: boolean }) {
    useHideCursorWhileFullscreen(fullscreen, cur)

    return null
  }

  it('hides on view mount and restores on return to the landing/composer', async () => {
    const cur = fakeCursor()
    const probe = await renderProbe(React.createElement(LayoutProbe, { cur, fullscreen: false }))
    // Not fullscreen → the owner writes nothing (the composer's input owns it).
    expect(cur.writes).toEqual([])

    // Enter a fullscreen view → hide.
    await probe.rerender(React.createElement(LayoutProbe, { cur, fullscreen: true }))
    expect(cur.writes).toEqual([HIDE])

    // Return to the landing → restore.
    await probe.rerender(React.createElement(LayoutProbe, { cur, fullscreen: false }))
    expect(cur.writes).toEqual([HIDE, SHOW])
    probe.cleanup()
  })

  it('restores the cursor if the fullscreen view unmounts outright', async () => {
    const cur = fakeCursor()
    const probe = await renderProbe(React.createElement(LayoutProbe, { cur, fullscreen: true }))
    expect(cur.writes).toEqual([HIDE])

    await probe.unmount()
    expect(cur.writes).toEqual([HIDE, SHOW])
    probe.cleanup()
  })

  it('never touches a non-TTY stream', async () => {
    const cur = fakeCursor(false)
    const probe = await renderProbe(React.createElement(LayoutProbe, { cur, fullscreen: true }))
    expect(cur.writes).toEqual([])
    probe.cleanup()
  })
})

describe('useInputCursor (input exception)', () => {
  function InputProbe({ cur, show }: { cur: CursorStream; show: boolean }) {
    useInputCursor(show, cur)

    return null
  }

  it('shows on focus and re-hides on blur while the field stays mounted', async () => {
    const cur = fakeCursor()
    // Focused text field wanting a native cursor → show.
    const probe = await renderProbe(React.createElement(InputProbe, { cur, show: true }))
    expect(cur.writes).toEqual([SHOW])

    // Blur (or a selection) → hide, one escape, no double-write.
    await probe.rerender(React.createElement(InputProbe, { cur, show: false }))
    expect(cur.writes).toEqual([SHOW, HIDE])

    // Focus again → show.
    await probe.rerender(React.createElement(InputProbe, { cur, show: true }))
    expect(cur.writes).toEqual([SHOW, HIDE, SHOW])
    probe.cleanup()
  })

  it('re-hides on unmount so a field inside a view leaves no stray cursor', async () => {
    const cur = fakeCursor()
    const probe = await renderProbe(React.createElement(InputProbe, { cur, show: true }))
    expect(cur.writes).toEqual([SHOW])

    // Field goes away while showing (e.g. a `/` filter closes inside a view).
    await probe.unmount()
    expect(cur.writes).toEqual([SHOW, HIDE])
    probe.cleanup()
  })

  // The composition the operator asked us to verify: a fullscreen view hides the
  // cursor (layout owner), a text field inside it shows it while focused, and the
  // view's hidden state resumes once the field blurs — all on ONE shared stream.
  it('composes with the layout hide: view hides, input shows, blur re-hides', async () => {
    const cur = fakeCursor()

    function Composed({ fieldMounted }: { fieldMounted: boolean }) {
      useHideCursorWhileFullscreen(true, cur)

      return fieldMounted ? React.createElement(InputProbe, { cur, show: true }) : null
    }

    // View mounts with no field → the layout owner hides.
    const probe = await renderProbe(React.createElement(Composed, { fieldMounted: false }))
    expect(cur.writes).toEqual([HIDE])

    // A focused `/` filter appears inside the view → the input re-shows the cursor.
    await probe.rerender(React.createElement(Composed, { fieldMounted: true }))
    expect(cur.writes.at(-1)).toBe(SHOW)

    // The filter closes → its unmount re-hides, so the view's hidden state resumes.
    await probe.rerender(React.createElement(Composed, { fieldMounted: false }))
    expect(cur.writes.at(-1)).toBe(HIDE)
    probe.cleanup()
  })
})
