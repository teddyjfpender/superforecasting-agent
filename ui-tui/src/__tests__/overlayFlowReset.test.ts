import { beforeEach, describe, expect, it } from 'vitest'

import { $overlayState, patchOverlayState, resetFlowOverlays, resetOverlayState } from '../app/overlayStore.js'

beforeEach(() => resetOverlayState())

describe('resetFlowOverlays (turn-end teardown)', () => {
  it('preserves user-toggled fullscreen views so a turn ending does not close them', () => {
    // Asking the desk from inside Obsidian runs a turn; turnController.idle()
    // calls resetFlowOverlays() on completion. The obsidian view (and the
    // other deliberately-opened views) must survive it.
    patchOverlayState({ alerts: true, calendar: true, calibration: true, forecasts: true, help: true, obsidian: true })

    resetFlowOverlays()

    const s = $overlayState.get()
    expect(s.obsidian).toBe(true)
    expect(s.calendar).toBe(true)
    expect(s.alerts).toBe(true)
    expect(s.help).toBe(true)
    expect(s.calibration).toBe(true)
    expect(s.forecasts).toBe(true)
  })

  it('still drops flow-scoped overlays (approval / clarify / sudo)', () => {
    patchOverlayState({
      approval: { command: 'rm -rf', description: 'danger' },
      clarify: { choices: null, question: 'which?', requestId: '1' },
      obsidian: true
    })

    resetFlowOverlays()

    const s = $overlayState.get()
    expect(s.approval).toBeNull()
    expect(s.clarify).toBeNull()
    // …while the user-opened view stays.
    expect(s.obsidian).toBe(true)
  })
})
