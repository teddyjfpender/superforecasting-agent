import { forceRedraw, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import { TYPING_IDLE_MS } from '../config/timing.js'
import { resolveViewChord } from '../content/keymaps.js'
import type {
  ApprovalRespondResponse,
  ConfigSetResponse,
  SecretRespondResponse,
  SudoRespondResponse,
  VoiceRecordResponse
} from '../gatewayTypes.js'
import { completionRequestForInput } from '../hooks/useCompletion.js'
import { forecastFindDraft, forecastShortcutForKey } from '../lib/forecastShortcuts.js'
import { RAIL_WIDTH } from '../lib/homeLayout.js'
import { isAction, isCopyShortcut, isMac, isVoiceToggleKey } from '../lib/platform.js'
import { computePrecisionWheelStep, initPrecisionWheel } from '../lib/precisionWheel.js'
import { dismissFirstRunHint } from '../lib/uiFlagsStore.js'
import { computeWheelStep, initWheelAccelForHost } from '../lib/wheelAccel.js'

import { $chordPending, armChord, clearChord } from './chordStore.js'
import { getHomeFocus, type HomePane, setHomePane } from './homeFocusStore.js'
import { getInputSelection } from './inputSelectionStore.js'
import type { InputHandlerContext, InputHandlerResult } from './interfaces.js'
import { activeNavKey, canOpenGlobalOverlay, selectNavView } from './navRoutes.js'
import { $isBlocked, $overlayState, patchOverlayState } from './overlayStore.js'
import { turnController } from './turnController.js'
import { patchTurnState } from './turnStore.js'
import { getUiState } from './uiStore.js'

const isCtrl = (key: { ctrl: boolean }, ch: string, target: string) => key.ctrl && ch.toLowerCase() === target

/**
 * Approval / clarify / confirm overlays mount their own `useInput` handlers
 * for the in-prompt keys (arrows, numbers, Enter, sometimes Esc).  The global
 * input handler used to early-return for any other key while one of those
 * overlays was up, which silently disabled transcript scrolling — the user
 * couldn't read context above the prompt that the prompt itself was asking
 * about.  Returns true when the key is a transcript-scroll input that should
 * fall through to the global scroll handlers even while a prompt is active.
 *
 * Modifier-held wheel (precision mode) is included — a user who wants to
 * scroll a single line at a time during a prompt expects it to work.
 */
export function shouldFallThroughForScroll(key: {
  downArrow: boolean
  pageDown: boolean
  pageUp: boolean
  shift: boolean
  upArrow: boolean
  wheelDown: boolean
  wheelUp: boolean
}): boolean {
  if (key.wheelUp || key.wheelDown) {
    return true
  }

  if (key.pageUp || key.pageDown) {
    return true
  }

  if (key.shift && (key.upArrow || key.downArrow)) {
    return true
  }

  return false
}

/**
 * The landing "Today" attention panel earns a SOFT focus tier between the plain
 * composer and the explicit Ctrl+T full-focus mode: while the composer is empty
 * (chromeArmable), the panel is mounted with actionable rows, and the
 * conversation pane holds focus, ↑/↓ + ⏎ route to the panel instead of the
 * composer's history/queue recall — WITHOUT taking the keyboard from typing
 * (every printable char still flows to the composer). Returns true only where
 * that routing should win; false everywhere history recall must stay live
 * (typing started → chromeArmable false, no Today rows → todayCount 0, the
 * rail/Today pane holds focus, or an overlay owns the keys → chromeArmable false).
 */
export const shouldSoftFocusToday = (chromeArmable: boolean, pane: HomePane, todayCount: number): boolean =>
  chromeArmable && pane === 'conversation' && todayCount > 0

/**
 * `h` is the unified Help key on every view. Over a fullscreen VIEW the view's
 * own useInput raises Help; on the Home route the GLOBAL handler does — but ONLY
 * when the composer is NOT focused (soft-focus sits on the Today/rail pane), so a
 * message that starts with `h` (the common case) is never hijacked. `onHome` is
 * `activeNavKey(overlay) === 'home'`; `canOpenOverlay` is `canOpenGlobalOverlay`.
 */
export const shouldOpenHomeHelp = (onHome: boolean, canOpenOverlay: boolean, pane: HomePane): boolean =>
  onHome && canOpenOverlay && pane !== 'conversation'

/**
 * PgUp/PgDn step: a full viewport MINUS ONE line, so exactly one line of
 * continuity carries across pages (the standard pager convention — the
 * reader never loses their place). Still under Ink's `delta < innerHeight`
 * DECSTBM fast-path threshold. Floor of 1 for degenerate viewports.
 */
export const pageScrollStep = (viewport: number): number => Math.max(1, viewport - 1)

export function applyVoiceRecordResponse(
  response: null | VoiceRecordResponse,
  starting: boolean,
  voice: Pick<InputHandlerContext['voice'], 'setProcessing' | 'setRecording'>,
  sys: (text: string) => void
) {
  if (!starting || response?.status === 'recording') {
    return
  }

  voice.setRecording(false)

  if (response?.status === 'busy') {
    voice.setProcessing(true)
    sys('voice: still transcribing; try again shortly')
  } else {
    voice.setProcessing(false)
  }
}

export function useInputHandlers(ctx: InputHandlerContext): InputHandlerResult {
  const { actions, composer, gateway, terminal, voice, wheelStep } = ctx
  const { actions: cActions, refs: cRefs, state: cState } = composer

  const overlay = useStore($overlayState)
  const isBlocked = useStore($isBlocked)
  const pagerPageSize = Math.max(5, (terminal.stdout?.rows ?? 24) - 6)
  const scrollIdleTimer = useRef<null | ReturnType<typeof setTimeout>>(null)

  // Wheel accel ported from claude-code: inter-event timing drives step size,
  // direction flips reset. wheelStep (WHEEL_SCROLL_STEP) is the base; final
  // rows = wheelStep × accelMult. State mutates in place across renders.
  const wheelAccelRef = useRef(initWheelAccelForHost())

  const precisionWheelRef = useRef(initPrecisionWheel())

  useEffect(() => () => clearTimeout(scrollIdleTimer.current ?? undefined), [])

  const scrollTranscript = (delta: number) => {
    if (getUiState().busy) {
      turnController.boostStreamingForScroll()
      clearTimeout(scrollIdleTimer.current ?? undefined)
      scrollIdleTimer.current = setTimeout(() => {
        scrollIdleTimer.current = null
        turnController.relaxStreaming()
      }, TYPING_IDLE_MS)
    }

    terminal.scrollWithSelection(delta)
  }

  const copySelection = () => {
    // ink's copySelection() already calls setClipboard() which handles
    // pbcopy (macOS), wl-copy/xclip (Linux), tmux, and OSC 52 fallback.
    terminal.selection.copySelection()
  }

  const clearSelection = () => {
    terminal.selection.clearSelection()
  }

  const cancelOverlayFromCtrlC = () => {
    if (overlay.clarify) {
      return actions.answerClarify('')
    }

    if (overlay.approval) {
      return gateway
        .rpc<ApprovalRespondResponse>('approval.respond', { choice: 'deny', session_id: getUiState().sid })
        .then(r => r && (patchOverlayState({ approval: null }), patchTurnState({ outcome: 'denied' })))
    }

    if (overlay.sudo) {
      return gateway
        .rpc<SudoRespondResponse>('sudo.respond', { password: '', request_id: overlay.sudo.requestId })
        .then(r => r && (patchOverlayState({ sudo: null }), actions.sys('sudo cancelled')))
    }

    if (overlay.secret) {
      return gateway
        .rpc<SecretRespondResponse>('secret.respond', { request_id: overlay.secret.requestId, value: '' })
        .then(r => r && (patchOverlayState({ secret: null }), actions.sys('secret entry cancelled')))
    }

    if (overlay.modelPicker) {
      return patchOverlayState({ modelPicker: false })
    }

    if (overlay.themePicker) {
      // ESC (handled inside ThemePicker) reverts to the pre-open theme; a hard
      // Ctrl+C just closes — the previewed theme stays for the session but was
      // never persisted, so a restart restores the saved skin.
      return patchOverlayState({ themePicker: false })
    }

    if (overlay.skillsHub) {
      return patchOverlayState({ skillsHub: false })
    }

    if (overlay.palette) {
      return patchOverlayState({ palette: false })
    }

    if (overlay.cheatSheet) {
      return patchOverlayState({ cheatSheet: false })
    }

    if (overlay.picker) {
      return patchOverlayState({ picker: false })
    }

    if (overlay.agents) {
      return patchOverlayState({ agents: false })
    }

    if (overlay.forecasts) {
      return patchOverlayState({ forecasts: false, forecastsInitialId: null })
    }
  }

  const cycleQueue = (dir: 1 | -1) => {
    const len = cRefs.queueRef.current.length

    if (!len) {
      return false
    }

    const index = cState.queueEditIdx === null ? (dir > 0 ? 0 : len - 1) : (cState.queueEditIdx + dir + len) % len

    cActions.setQueueEdit(index)
    cActions.setHistoryIdx(null)
    cActions.setInput(cRefs.queueRef.current[index] ?? '')

    return true
  }

  const cycleHistory = (dir: 1 | -1) => {
    const h = cRefs.historyRef.current
    const cur = cState.historyIdx

    if (dir < 0) {
      if (!h.length) {
        return
      }

      if (cur === null) {
        cRefs.historyDraftRef.current = cState.input
      }

      const index = cur === null ? h.length - 1 : Math.max(0, cur - 1)

      cActions.setHistoryIdx(index)
      cActions.setQueueEdit(null)
      cActions.setInput(h[index] ?? '')

      return
    }

    if (cur === null) {
      return
    }

    const next = cur + 1

    if (next >= h.length) {
      cActions.setHistoryIdx(null)
      cActions.setInput(cRefs.historyDraftRef.current)
    } else {
      cActions.setHistoryIdx(next)
      cActions.setInput(h[next] ?? '')
    }
  }

  // CLI parity: Ctrl+B toggles a VAD-bounded push-to-talk capture
  // (NOT the voice-mode umbrella bit). The mode is enabled via /voice on;
  // Ctrl+B while the mode is off sys-nudges the user. While the mode is
  // on, the first press starts a single VAD-bounded capture
  // (gateway -> start_continuous(auto_restart=false), VAD auto-stop ->
  // transcribe -> idle), a subsequent press stops and transcribes it.
  // The gateway publishes voice.status + voice.transcript events that
  // createGatewayEventHandler turns into UI badges and composer injection.
  const voiceRecordToggle = () => {
    // While the agent is SPEAKING, the record key stops the speech (barge-in / skip)
    // instead of starting a capture. The gateway's voice.stop emits voice.status idle,
    // which clears the speaking audiogram.
    if (voice.speaking) {
      gateway.rpc('voice.stop', { session_id: getUiState().sid }).catch(() => {})

      return
    }

    if (!voice.enabled) {
      return actions.sys('voice: mode is off — enable with /voice on')
    }

    const starting = !voice.recording
    const action = starting ? 'start' : 'stop'

    // Optimistic UI — flip the REC badge immediately so the user gets
    // feedback while the RPC round-trips; the voice.status event is the
    // authoritative source and may correct us.
    if (starting) {
      voice.setRecording(true)
    } else {
      voice.setRecording(false)
      voice.setProcessing(false)
    }

    gateway
      .rpc<VoiceRecordResponse>('voice.record', { action, session_id: getUiState().sid })
      .then(r => applyVoiceRecordResponse(r, starting, voice, actions.sys))
      .catch((e: Error) => {
        // Revert optimistic UI on failure.
        if (starting) {
          voice.setRecording(false)
        }

        actions.sys(`voice error: ${e.message}`)
      })
  }

  useInput((ch, key, event) => {
    const live = getUiState()

    // ── Global interaction chrome: command palette ──────────────────────────
    // Ctrl+K opens the palette from ANYWHERE — the Home composer or over a
    // fullscreen view — so it sits BEFORE the blocked-overlay early-return.
    // Suppressed only while an input-owning prompt/picker holds the keyboard
    // (canOpenGlobalOverlay). When the palette/cheat-sheet is itself open its
    // own useInput traps first (stopImmediatePropagation), so we never reach
    // here for those keys.
    if (canOpenGlobalOverlay(overlay) && isCtrl(key, ch, 'k')) {
      // Discovering the palette permanently retires the landing "New here?" hint.
      dismissFirstRunHint()

      return patchOverlayState({ palette: true })
    }

    // `?` opens the cheat sheet from ANYWHERE — the Home composer or over a
    // fullscreen view — so, like Ctrl+K, it sits BEFORE the blocked-overlay
    // early-return (a fullscreen view sets $isBlocked, which used to swallow it
    // everywhere but Home). Gated on an EMPTY composer draft so a message that
    // contains `?` is never hijacked; the composer captured the glyph as a
    // sibling, so clear it when we fire.
    if (
      canOpenGlobalOverlay(overlay) &&
      ch === '?' &&
      !key.ctrl &&
      !key.meta &&
      !cState.completions.length &&
      !cState.inputBuf.length &&
      !cState.input
    ) {
      cActions.clearIn()
      // Opening the cheat-sheet is itself the discovery act — retire the hint.
      dismissFirstRunHint()

      return patchOverlayState({ cheatSheet: true })
    }

    // `h` opens the SAME unified Help modal — the primary, consistent help key.
    // Over a fullscreen VIEW the view's own useInput raises it (so `h` yields to
    // that view's chat/filter text modes first); HERE we cover ONLY the Home
    // route, and only when the composer is NOT focused (soft-focus sits on the
    // Today / rail pane). That keeps a message that starts with `h` — the common
    // case — from ever being hijacked, while `h` still summons help off-composer.
    if (
      ch === 'h' &&
      !key.ctrl &&
      !key.meta &&
      shouldOpenHomeHelp(activeNavKey(overlay) === 'home', canOpenGlobalOverlay(overlay), getHomeFocus().pane)
    ) {
      dismissFirstRunHint()

      return patchOverlayState({ cheatSheet: true })
    }

    if (isBlocked) {
      // When approval/clarify/confirm overlays are active, their own useInput
      // handlers must receive keystrokes (arrow keys, numbers, Enter).  Only
      // intercept Ctrl+C here so the user can deny/dismiss — all other keys
      // fall through to the component-level handlers.
      //
      // Scroll inputs (wheel / PageUp / PageDown / Shift+↑↓) are special:
      // they must reach the transcript scroll handlers below even with a
      // prompt up.  Long-thread context the prompt is asking about often
      // lives above the visible viewport, and being unable to read it while
      // answering felt like the prompt had locked the entire UI.  Explicitly
      // skip the prompt-overlay early-return for scroll keys so they fall
      // through to the wheel / PageUp / Shift+arrow handlers below.
      const promptOverlay = overlay.approval || overlay.clarify || overlay.confirm
      const fallThroughForScroll = promptOverlay && shouldFallThroughForScroll(key)

      if (promptOverlay && !fallThroughForScroll) {
        if (isCtrl(key, ch, 'c')) {
          cancelOverlayFromCtrlC()
        }

        return
      }

      if (overlay.pager) {
        if (key.escape || isCtrl(key, ch, 'c') || ch === 'q') {
          return patchOverlayState({ pager: null })
        }

        const move = (delta: number | 'top' | 'bottom') =>
          patchOverlayState(prev => {
            if (!prev.pager) {
              return prev
            }

            const { lines, offset } = prev.pager
            const max = Math.max(0, lines.length - pagerPageSize)
            const step = delta === 'top' ? -lines.length : delta === 'bottom' ? lines.length : delta
            const next = Math.max(0, Math.min(offset + step, max))

            return next === offset ? prev : { ...prev, pager: { ...prev.pager, offset: next } }
          })

        if (key.upArrow || ch === 'k') {
          return move(-1)
        }

        if (key.downArrow || ch === 'j') {
          return move(1)
        }

        if (key.pageUp || ch === 'b') {
          return move(-pagerPageSize)
        }

        if (ch === 'g') {
          return move('top')
        }

        if (ch === 'G') {
          return move('bottom')
        }

        if (key.return || ch === ' ' || key.pageDown) {
          patchOverlayState(prev => {
            if (!prev.pager) {
              return prev
            }

            const { lines, offset } = prev.pager
            const max = Math.max(0, lines.length - pagerPageSize)

            // Auto-close only when already at the last page — otherwise clamp
            // to `max` so the offset matches what the line/page-back handlers
            // can reach (prevents a snap-back jump on the next ↑/↓/PgUp).
            return offset >= max
              ? { ...prev, pager: null }
              : { ...prev, pager: { ...prev.pager, offset: Math.min(offset + pagerPageSize, max) } }
          })
        }

        return
      }

      if (isCtrl(key, ch, 'c')) {
        cancelOverlayFromCtrlC()
      } else if (key.escape && overlay.picker) {
        patchOverlayState({ picker: false })
      }

      // When a prompt overlay is up and the user pressed a scroll key, fall
      // through to the global scroll handlers below instead of returning.
      // Otherwise nothing above this comment matched, and there's nothing
      // useful to do for an arbitrary key while blocked.
      if (!fallThroughForScroll) {
        return
      }
    }

    // ── Global interaction chrome: view chords (Home) ──────────────────────
    // Reached only when NOT blocked — i.e. the Home route, where the composer
    // is focused. The leader is Ctrl+G (armed below), so it can never eat typed
    // text; the SECOND key is a plain letter the composer captures as a sibling,
    // which we drop with `clearIn` when a chord actually fires a switch. Over a
    // fullscreen VIEW these are handled inside the view (after its own filter
    // submode); Ctrl+K / `?` above already cover the palette + cheat sheet
    // everywhere.
    if ($chordPending.get() === 'g') {
      // Second key of a `Ctrl+G …` chord: route to a view, or cancel and fall
      // through so the key still does whatever it normally would.
      const nav = ch ? resolveViewChord(ch) : null

      clearChord()

      if (nav && selectNavView(nav)) {
        cActions.clearIn()
        // A completed Ctrl+G view-chord means the chords are discovered too.
        dismissFirstRunHint()

        return
      }
    }

    const chromeArmable =
      canOpenGlobalOverlay(overlay) && !cState.completions.length && !cState.inputBuf.length && !cState.input

    // Ctrl+G arms the view-chord leader (Ctrl+G then a letter → a view). A
    // NON-printable leader is deliberate: a bare `g` over the focused Home
    // composer hijacked any message starting `g`+a chord letter ("go …",
    // "gather …", "game …"), discarding the draft. The second key is still a
    // plain letter — the composer captures it as a sibling, and `clearChord` +
    // `clearIn` (in the $chordPending branch above) drop the stray glyph when a
    // chord actually fires.
    if (chromeArmable && isCtrl(key, ch, 'g')) {
      return armChord('g')
    }

    // Ctrl+T hands the keyboard to the landing "Today" attention panel (↑↓
    // select, ⏎ open, a alerts, n new). Gated on todayCount so it only grabs
    // focus when the panel is actually mounted with actionable rows (the
    // landing). Ctrl (not a bare `t`) so a message starting with `t` — a very
    // common sentence-initial letter — is never hijacked out of the composer.
    if (chromeArmable && isCtrl(key, ch, 't') && getHomeFocus().todayCount > 0) {
      setHomePane('today')

      return
    }

    // While the landing "Today" panel holds focus, its own useInput drives
    // ↑↓/⏎/a/n; swallow non-wheel keys here so the global handler can't
    // double-handle them (Tab/Esc hand the keyboard back to the composer).
    // Placed BEFORE the rail switch so Tab from Today returns to the composer
    // rather than falling into the rail-entry branch. Wheel still flows below.
    if (getHomeFocus().pane === 'today') {
      if (key.tab || key.escape) {
        setHomePane('conversation')
      }

      if (!key.wheelUp && !key.wheelDown) {
        return
      }
    }

    // Tab EXPLICITLY opens path / @-mention completion for a path-like trailing
    // token. Path completion never auto-fires while typing (that flashed the
    // dropdown on every "and/or" or "@name" — see useCompletion), so Tab is the
    // trigger. Only when the composer is focused, no menu is already open, and
    // the trailing token actually is path-like; otherwise Tab keeps its
    // rail-focus (below) and completion-accept (further down) roles. Plain Tab
    // only — shift+Tab stays the yolo toggle.
    if (
      key.tab &&
      !key.shift &&
      !cState.completions.length &&
      getHomeFocus().pane === 'conversation' &&
      completionRequestForInput(cState.input)?.method === 'complete.path'
    ) {
      cActions.armPath()

      return
    }

    // --- Home conversations rail: keyboard focus switching ---
    // railScrollRef.current is attached only while the rail is shown (wide
    // two-pane Home, no overlay), so it doubles as "rail is available". While
    // the rail holds focus, swallow keyboard input here — the rail's own
    // handler drives ↑↓/Enter — but let wheel/trackpad scroll keep flowing to
    // the pointer-routed handlers below.
    const railAvailable = terminal.railScrollRef.current != null

    if (railAvailable && getHomeFocus().pane === 'rail') {
      if (key.tab || key.escape || key.rightArrow) {
        setHomePane('conversation')
      }

      if (!key.wheelUp && !key.wheelDown) {
        return
      }
    } else if (
      railAvailable &&
      !cState.completions.length &&
      (key.tab || (key.leftArrow && !cState.input && !cState.inputBuf.length))
    ) {
      // Tab (or ← on an empty composer) hands the keyboard to the rail. The
      // composer ignores Tab and a no-op empty-input ← anyway, so there's
      // nothing to suppress on the still-active TextInput this frame.
      setHomePane('rail')

      return
    }

    if (cState.completions.length && cState.input && cState.historyIdx === null && (key.upArrow || key.downArrow)) {
      const len = cState.completions.length

      cActions.setCompIdx(i => (key.upArrow ? (i - 1 + len) % len : (i + 1) % len))

      return
    }

    if (key.wheelUp || key.wheelDown) {
      const dir: -1 | 1 = key.wheelUp ? -1 : 1
      const now = Date.now()
      // Route the wheel to whichever Home pane sits under the pointer. The rail
      // carries its own scroll handle; when the pointer is over it (and it's
      // actually mounted), scroll the rail instead of the transcript. The
      // null-check makes overlays / narrow terminals fall back automatically.
      // Rail scroll needs no selection tracking, so it bypasses scrollTranscript.
      // railScrollRef.current is non-null only in the wide two-pane Home, so it
      // is the authoritative "rail is shown" signal — no need to re-derive the
      // width from stdout (which can disagree with the app's column math and
      // wrongly suppress rail scrolling). mouseCol is 1-indexed; the rail spans
      // columns 1..RAIL_WIDTH.
      const mouseCol = key.mouseCol

      const overRail = mouseCol != null && mouseCol <= RAIL_WIDTH && terminal.railScrollRef.current != null

      const applyWheel = (delta: number) => {
        if (overRail) {
          terminal.railScrollRef.current?.scrollBy(delta)

          return
        }

        scrollTranscript(delta)
      }

      // Modifier-held wheel = precision mode: one row per frame, no accel.
      // Smooth mice / trackpads emit tiny same-frame bursts; coalesce those
      // without the old 80ms throttle that made opt-scroll feel stepped.
      // SGR/X10 mouse encoding only carries shift/meta/ctrl bits; Cmd on
      // macOS is intercepted by the terminal, so we honor Option (meta) on
      // Mac / Alt (meta) on Win+Linux / Ctrl as a portable fallback. Shift
      // is reserved for selection extension.
      const hasModifier = key.meta || key.ctrl
      const precision = computePrecisionWheelStep(precisionWheelRef.current, dir, hasModifier, now)

      if (precision.active) {
        // Entering precision mode must discard any accelerated wheel state;
        // otherwise the next normal wheel event inherits stale momentum.
        if (precision.entered) {
          wheelAccelRef.current = initWheelAccelForHost()
        }

        return precision.rows ? applyWheel(dir * wheelStep) : undefined
      }

      // 0 = direction-flip bounce deferred; skip the no-op scroll.
      const rows = computeWheelStep(wheelAccelRef.current, dir, now)

      return rows ? applyWheel(dir * rows * wheelStep) : undefined
    }

    if (key.shift && key.upArrow) {
      return scrollTranscript(-1)
    }

    if (key.shift && key.downArrow) {
      return scrollTranscript(1)
    }

    if (key.pageUp || key.pageDown) {
      // Viewport-minus-one: one continuity line carries across pages (pager
      // convention) while staying under Ink's `delta < innerHeight` DECSTBM
      // fast-path threshold.
      const viewport = terminal.scrollRef.current?.getViewportHeight() ?? Math.max(6, (terminal.stdout?.rows ?? 24) - 8)
      const step = pageScrollStep(viewport)

      return scrollTranscript(key.pageUp ? -step : step)
    }

    // Escape-based voice bindings (ctrl/alt/super+escape) must win before the
    // generic Esc handlers below; otherwise queue-edit cancel / selection-clear
    // would swallow the chord and /voice would advertise a shortcut that never
    // actually toggles recording in those UI states.
    if (key.escape && isVoiceToggleKey(key, ch, voice.recordKey)) {
      return voiceRecordToggle()
    }

    // Queue-edit cancel beats selection-clear for plain Esc: the queue header
    // explicitly promises "Esc cancel", so honoring it takes priority over the
    // implicit selection-dismissal convention. Without an active edit, fall through.
    if (key.escape && cState.queueEditIdx !== null) {
      return cActions.clearIn()
    }

    if (key.escape && terminal.hasSelection) {
      return clearSelection()
    }

    // ── Landing "Today" soft focus ─────────────────────────────────────────
    // The attention panel owns ↑/↓ (move its selection) + ⏎ (open the row) while
    // the composer is empty and Today has rows. The panel's OWN useInput does the
    // work (its softFocus prop mirrors this predicate); here we only SWALLOW the
    // arrows so the history/queue recall below can't also steal them. Typing is
    // untouched — printable chars never reach this branch, so the first letter of
    // a message always lands in the composer. ⏎ is left to the panel + a no-op
    // empty submit; Esc is left to the panel (it clears its own highlight).
    // Reached only when pane === 'conversation' (the Ctrl+T / rail branches above
    // already returned for their panes) and shift+arrow already scrolled above.
    const homeFocusNow = getHomeFocus()

    if (
      shouldSoftFocusToday(chromeArmable, homeFocusNow.pane, homeFocusNow.todayCount) &&
      (key.upArrow || key.downArrow)
    ) {
      return
    }

    if (key.upArrow && !cState.inputBuf.length) {
      const inputSel = getInputSelection()
      const cursor = inputSel && inputSel.start === inputSel.end ? inputSel.start : null

      const noLineAbove =
        !cState.input || (cursor !== null && cState.input.lastIndexOf('\n', Math.max(0, cursor - 1)) < 0)

      if (noLineAbove) {
        cycleQueue(1) || cycleHistory(-1)

        return
      }
    }

    if (key.downArrow && !cState.inputBuf.length) {
      const inputSel = getInputSelection()
      const cursor = inputSel && inputSel.start === inputSel.end ? inputSel.start : null
      const noLineBelow = !cState.input || (cursor !== null && cState.input.indexOf('\n', cursor) < 0)

      if (noLineBelow || cState.historyIdx !== null) {
        cycleQueue(-1) || cycleHistory(1)

        return
      }
    }

    if (isCopyShortcut(key, ch)) {
      if (terminal.hasSelection) {
        return copySelection()
      }

      const inputSel = getInputSelection()

      if (inputSel && inputSel.end > inputSel.start) {
        inputSel.clear()

        return
      }

      // On macOS, Cmd+C with no selection is a no-op (Ctrl+C below handles interrupt).
      // On non-macOS, isAction uses Ctrl, so fall through to interrupt/clear/exit.
      if (isMac) {
        return
      }
    }

    if (isCtrl(key, ch, 'x') && cState.queueEditIdx !== null) {
      cActions.removeQueue(cState.queueEditIdx)

      return cActions.clearIn()
    }

    if (key.ctrl && ch.toLowerCase() === 'c') {
      if (live.busy && live.sid) {
        return turnController.interruptTurn({
          appendMessage: actions.appendMessage,
          gw: gateway.gw,
          sid: live.sid,
          sys: actions.sys
        })
      }

      if (cState.input || cState.inputBuf.length) {
        return cActions.clearIn()
      }

      return actions.die()
    }

    if (isAction(key, ch, 'd')) {
      return actions.die()
    }

    if (isAction(key, ch, 'l')) {
      clearSelection()
      forceRedraw(terminal.stdout ?? process.stdout)

      return
    }

    if (isVoiceToggleKey(key, ch, voice.recordKey)) {
      return voiceRecordToggle()
    }

    const forecastShortcut = cState.inputBuf.length
      ? null
      : forecastShortcutForKey(ch, key, cState.input, event.keypress.raw)

    if (forecastShortcut) {
      cActions.setHistoryIdx(null)
      cActions.setQueueEdit(null)

      if (forecastShortcut.mode === 'prefill') {
        cActions.setInput(forecastFindDraft(cState.input))

        return
      }

      if (cState.input.trim()) {
        return
      }

      return actions.dispatchSubmission(forecastShortcut.command)
    }

    // Cmd/Ctrl+G, plus Alt+G fallback for VSCode/Cursor (they bind the
    // primary keystroke to "Find Next" before the TUI sees it; Alt+G
    // arrives as meta+g across platforms).
    if (ch.toLowerCase() === 'g' && (isAction(key, ch, 'g') || key.meta)) {
      return void cActions.openEditor().catch((err: unknown) => {
        actions.sys(err instanceof Error ? `failed to open editor: ${err.message}` : 'failed to open editor')
      })
    }

    // shift-tab flips yolo without spending a turn (claude-code parity)
    if (key.shift && key.tab && !cState.completions.length) {
      if (!live.sid) {
        return void actions.sys('yolo needs an active session')
      }

      // gateway.rpc swallows errors with its own sys() message and resolves to null,
      // so we only speak when it came back with a real shape. null = rpc already spoke.
      return void gateway.rpc<ConfigSetResponse>('config.set', { key: 'yolo', session_id: live.sid }).then(r => {
        if (r?.value === '1') {
          return actions.sys('yolo on')
        }

        if (r?.value === '0') {
          return actions.sys('yolo off')
        }

        if (r) {
          actions.sys('failed to toggle yolo')
        }
      })
    }

    if (key.tab && cState.completions.length) {
      const row = cState.completions[cState.compIdx]

      if (row?.text) {
        const text =
          cState.input.startsWith('/') && row.text.startsWith('/') && cState.compReplace > 0
            ? row.text.slice(1)
            : row.text

        cActions.setInput(cState.input.slice(0, cState.compReplace) + text)
      }

      return
    }

    if (isAction(key, ch, 'k') && cRefs.queueRef.current.length && live.sid) {
      const next = cActions.dequeue()

      if (next) {
        cActions.setQueueEdit(null)
        actions.dispatchSubmission(next)
      }
    }
  })

  return { pagerPageSize }
}
