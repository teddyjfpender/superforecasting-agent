import { afterEach, expect, it } from 'vitest'

import { applyDelegationStatus, getDelegationState, resetDelegationState } from '../app/delegationStore.js'
import { patchUiState, resetUiState } from '../app/uiStore.js'

afterEach(() => {
  resetUiState()
  resetDelegationState()
})

it('drops the previous session pause and caps on session handoff', () => {
  patchUiState({ sid: 'first' })
  applyDelegationStatus({ paused: true, max_spawn_depth: 3 })
  expect(getDelegationState().paused).toBe(true)
  patchUiState({ sid: 'second' })
  expect(getDelegationState()).toMatchObject({ paused: false, maxSpawnDepth: null, updatedAt: null })
})

it('retains fetched state through unrelated screen updates', () => {
  patchUiState({ sid: 'first' })
  applyDelegationStatus({ paused: true })
  patchUiState({ status: 'ready' })
  expect(getDelegationState().paused).toBe(true)
})
