import { afterEach, expect, it } from 'vitest'

import { selectNavView } from '../app/navRoutes.js'
import { $overlayState, $primaryRoute, patchOverlayState, resetFlowOverlays, resetOverlayState } from '../app/overlayStore.js'
import { PRIMARY_FLAGS } from '../app/primaryRoute.js'

afterEach(resetOverlayState)

it('publishes one primary view atomically while retaining independent modal state', () => {
  const seen: string[][] = []
  const stop = $overlayState.listen(state => { seen.push(PRIMARY_FLAGS.filter(flag => state[flag])) })
  patchOverlayState({ news: true, palette: true })
  patchOverlayState({ markets: true })
  expect($primaryRoute.get()).toBe('markets')
  expect($overlayState.get().palette).toBe(true)
  expect($overlayState.get().news).toBe(false)
  expect(seen).toEqual([['news'], ['markets']])
  stop()
})

it('rejects ambiguous navigation without changing the prior route', () => {
  selectNavView('desk')
  const before = $overlayState.get()
  expect(() => patchOverlayState({ news: true, markets: true })).toThrow('only one primary view')
  expect($overlayState.get()).toBe(before)
  expect($primaryRoute.get()).toBe('desk')
})

it('ignores a late dismissal of the preceding view and supports functional adapters', () => {
  patchOverlayState({ news: true })
  patchOverlayState(state => ({ ...state, markets: true }))
  patchOverlayState({ news: false })
  expect($primaryRoute.get()).toBe('markets')
  patchOverlayState({ markets: false })
  expect($primaryRoute.get()).toBe('home')
})

it('preserves questionnaire identity across turn completion without changing its parent view', () => {
  patchOverlayState({ news: true, onboard: true, onboardInterviewId: 'draft', onboardQuestionId: 'question' })
  resetFlowOverlays()
  expect($primaryRoute.get()).toBe('news')
  expect($overlayState.get()).toMatchObject({ onboard: true, onboardInterviewId: 'draft', onboardQuestionId: 'question' })
  resetOverlayState()
  expect($primaryRoute.get()).toBe('home')
  expect($overlayState.get().onboardInterviewId).toBeNull()
})
