import { atom, computed } from 'nanostores'

import type { OverlayState } from './interfaces.js'

const buildOverlayState = (): OverlayState => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  alerts: false,
  approval: null,
  calendar: false,
  calibration: false,
  clarify: null,
  confirm: null,
  demoViz: false,
  forecasts: false,
  forecastsInitialId: null,
  help: false,
  hooks: false,
  markets: false,
  messaging: false,
  modelPicker: false,
  news: false,
  newsInitialQuery: null,
  obsidian: false,
  onboard: false,
  pager: null,
  picker: false,
  secret: null,
  skillsHub: false,
  sudo: null,
  themePicker: false
})

export const $overlayState = atom<OverlayState>(buildOverlayState())

/**
 * The BLOCKING prompt overlays.  They are MUTUALLY EXCLUSIVE — at most one
 * may be shown at a time — and historically a freshly-raised prompt (e.g. an
 * `approval.request` from the gateway) would clobber whichever prompt was
 * already pending (e.g. a `confirm`), silently dropping the user's answer to
 * the first one.  `raisePrompt` + the pump below close that hole with a minimal
 * FIFO buffer: a second prompt defers instead of clobbering.
 *
 * NOTE: `pager` is intentionally NOT in this set.  It is a PASSIVE viewer
 * (opened via patchOverlayState, not a blocking gateway worker awaiting a
 * reply) and can legitimately be open mid-turn.  If it participated in the
 * queue, a real blocking prompt would defer behind a passive pager — exactly
 * backwards.  Only the 5 BLOCKING prompts queue.
 */
export const PROMPT_KEYS = ['approval', 'clarify', 'confirm', 'sudo', 'secret'] as const

type PromptKey = (typeof PROMPT_KEYS)[number]

/** FIFO buffer of prompts that were raised while another prompt was active. */
let pendingPrompts: Array<Partial<OverlayState>> = []

/** The first prompt key currently shown, or null when no prompt is active. */
const activePromptKey = (state: OverlayState): null | PromptKey =>
  PROMPT_KEYS.find(key => state[key] != null) ?? null

/** Test/teardown helper: drop every buffered prompt. */
export const clearPendingPrompts = () => {
  pendingPrompts = []
}

/** Test-only inspection of the buffer depth. */
export const pendingPromptCount = () => pendingPrompts.length

export const $isBlocked = computed(
  $overlayState,
  ({
    agents,
    alerts,
    approval,
    calendar,
    calibration,
    clarify,
    confirm,
    demoViz,
    forecasts,
    help,
    hooks,
    markets,
    messaging,
    modelPicker,
    news,
    obsidian,
    onboard,
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
        calendar ||
        calibration ||
        clarify ||
        confirm ||
        demoViz ||
        forecasts ||
        help ||
        hooks ||
        markets ||
        messaging ||
        modelPicker ||
        news ||
        obsidian ||
        onboard ||
        pager ||
        picker ||
        secret ||
        skillsHub ||
        sudo ||
        themePicker
    )
)

export const getOverlayState = () => $overlayState.get()

export const patchOverlayState = (next: Partial<OverlayState> | ((state: OverlayState) => OverlayState)) => {
  const prev = $overlayState.get()
  let resolved = typeof next === 'function' ? next(prev) : { ...prev, ...next }

  // Pump the prompt queue: when this patch clears the active prompt and no other
  // prompt is now showing, re-raise the next buffered prompt (FIFO) in the SAME
  // store write.  When the buffer is empty this is a no-op, so single-prompt
  // behaviour is byte-identical to before the queue existed.
  if (activePromptKey(prev) != null && activePromptKey(resolved) == null && pendingPrompts.length > 0) {
    resolved = { ...resolved, ...pendingPrompts.shift() }
  }

  $overlayState.set(resolved)
}

/**
 * Raise a BLOCKING prompt overlay (approval / clarify / confirm / sudo /
 * secret).  If a prompt is already active the new one is BUFFERED and
 * re-raised once the active prompt resolves (see the pump in
 * `patchOverlayState`).  `patch` MUST set exactly one prompt key.
 */
export const raisePrompt = (patch: Partial<OverlayState>) => {
  if (activePromptKey($overlayState.get()) != null) {
    // KNOWN LIMITATION: a buffered BLOCKING prompt can _block-time out
    // gateway-side while it sits hidden in this queue (sudo ~120s, approval
    // ~300s).  When the active prompt finally resolves, the pump may surface
    // a prompt the gateway has already abandoned, so answering it is a no-op.
    // Buffering is still strictly better than the old clobber-and-lose
    // behaviour (we never silently drop the user's first answer); a proper
    // fix is a liveness handshake (re-check the gateway request is still
    // pending before re-raising) and is left as a follow-up.
    pendingPrompts.push(patch)

    return
  }

  patchOverlayState(patch)
}

/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => {
  pendingPrompts = []
  $overlayState.set(buildOverlayState())
}

/**
 * Soft reset: drop FLOW-scoped overlays (approval / clarify / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, skills hub, session picker.  Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = () => {
  // A turn ended/was interrupted: any prompts buffered behind the (now-cleared)
  // active prompt belong to that turn and must NOT pop back up afterwards.
  pendingPrompts = []
  $overlayState.set({
    ...buildOverlayState(),
    agents: $overlayState.get().agents,
    agentsInitialHistoryIndex: $overlayState.get().agentsInitialHistoryIndex,
    // User-toggled fullscreen views — opened deliberately, so they must
    // survive a turn ending (e.g. asking the desk from inside Obsidian).
    alerts: $overlayState.get().alerts,
    calendar: $overlayState.get().calendar,
    calibration: $overlayState.get().calibration,
    demoViz: $overlayState.get().demoViz,
    forecasts: $overlayState.get().forecasts,
    forecastsInitialId: $overlayState.get().forecastsInitialId,
    help: $overlayState.get().help,
    hooks: $overlayState.get().hooks,
    markets: $overlayState.get().markets,
    messaging: $overlayState.get().messaging,
    modelPicker: $overlayState.get().modelPicker,
    news: $overlayState.get().news,
    newsInitialQuery: $overlayState.get().newsInitialQuery,
    obsidian: $overlayState.get().obsidian,
    onboard: $overlayState.get().onboard,
    picker: $overlayState.get().picker,
    skillsHub: $overlayState.get().skillsHub,
    themePicker: $overlayState.get().themePicker
  })
}
