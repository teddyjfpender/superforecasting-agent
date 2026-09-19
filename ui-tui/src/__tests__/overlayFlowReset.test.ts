import { beforeEach, describe, expect, it } from 'vitest'

import { $overlayState, patchOverlayState, resetFlowOverlays, resetOverlayState } from '../app/overlayStore.js'
import { PRIMARY_FLAGS } from '../app/primaryRoute.js'

beforeEach(() => resetOverlayState())

describe('resetFlowOverlays (turn-end teardown)', () => {
  it.each(PRIMARY_FLAGS)('preserves the selected %s view when a turn ends', flag => {
    patchOverlayState({ [flag]: true })
    resetFlowOverlays()
    const state = $overlayState.get()
    expect(state[flag]).toBe(true)
    expect(PRIMARY_FLAGS.filter(key => state[key])).toEqual([flag])
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
