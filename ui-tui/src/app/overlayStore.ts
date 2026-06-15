import { atom, computed } from 'nanostores'

import type { OverlayState } from './interfaces.js'

const buildOverlayState = (): OverlayState => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  alerts: false,
  approval: null,
  calibration: false,
  clarify: null,
  confirm: null,
  forecasts: false,
  forecastsInitialId: null,
  help: false,
  modelPicker: false,
  pager: null,
  picker: false,
  secret: null,
  skillsHub: false,
  sudo: null,
  themePicker: false
})

export const $overlayState = atom<OverlayState>(buildOverlayState())

export const $isBlocked = computed(
  $overlayState,
  ({
    agents,
    alerts,
    approval,
    calibration,
    clarify,
    confirm,
    forecasts,
    help,
    modelPicker,
    pager,
    picker,
    secret,
    skillsHub,
    sudo,
    themePicker
  }) =>
    Boolean(
      agents ||
        alerts ||
        approval ||
        calibration ||
        clarify ||
        confirm ||
        forecasts ||
        help ||
        modelPicker ||
        pager ||
        picker ||
        secret ||
        skillsHub ||
        sudo ||
        themePicker
    )
)

export const getOverlayState = () => $overlayState.get()

export const patchOverlayState = (next: Partial<OverlayState> | ((state: OverlayState) => OverlayState)) =>
  $overlayState.set(typeof next === 'function' ? next($overlayState.get()) : { ...$overlayState.get(), ...next })

/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => $overlayState.set(buildOverlayState())

/**
 * Soft reset: drop FLOW-scoped overlays (approval / clarify / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, skills hub, session picker.  Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = () =>
  $overlayState.set({
    ...buildOverlayState(),
    agents: $overlayState.get().agents,
    agentsInitialHistoryIndex: $overlayState.get().agentsInitialHistoryIndex,
    calibration: $overlayState.get().calibration,
    forecasts: $overlayState.get().forecasts,
    forecastsInitialId: $overlayState.get().forecastsInitialId,
    modelPicker: $overlayState.get().modelPicker,
    picker: $overlayState.get().picker,
    skillsHub: $overlayState.get().skillsHub,
    themePicker: $overlayState.get().themePicker
  })
