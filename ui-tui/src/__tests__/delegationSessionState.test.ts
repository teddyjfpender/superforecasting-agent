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

it('uses backend snapshots for background work and preserves them through partial replies', () => {
  patchUiState({ sid: 'first' })
  applyDelegationStatus({
    active: [{ kind: 'background', subagent_id: 'bg', goal: 'research', status: 'running', started_at: 1.5 }]
  })
  expect(getDelegationState().backgroundAgents[0]).toMatchObject({
    id: 'bg',
    status: 'running',
    goal: 'research',
    startedAt: 1500
  })
  applyDelegationStatus({ paused: true })
  expect(getDelegationState().backgroundAgents).toHaveLength(1)
  applyDelegationStatus({
    active: [{ kind: 'background', subagent_id: 'bg', goal: 'research', status: 'cleanup_pending' }]
  })
  expect(getDelegationState().backgroundAgents[0]).toMatchObject({
    status: 'error',
    goal: 'research · cleanup pending'
  })
  expect(getDelegationState().backgroundAgents[0]?.summary).toContain('/stop')
  applyDelegationStatus({ active: [] })
  expect(getDelegationState().backgroundAgents).toEqual([])
})

it('never carries backend background records into a replacement session', () => {
  patchUiState({ sid: 'first' })
  applyDelegationStatus({ active: [{ kind: 'background', subagent_id: 'bg', status: 'running' }] })
  patchUiState({ sid: 'second' })
  expect(getDelegationState().backgroundAgents).toEqual([])
})
