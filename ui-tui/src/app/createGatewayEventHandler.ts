import { STARTUP_IMAGE, STARTUP_QUERY } from '../config/env.js'
import { GATEWAY_STDERR_COALESCE_MS, STREAM_BATCH_MS } from '../config/timing.js'
import { AUTH_EXPIRED_RE, AUTH_EXPIRED_TITLE, buildAuthExpiredSections } from '../content/auth.js'
import { buildSetupRequiredSections, SETUP_REQUIRED_TITLE } from '../content/setup.js'
import type {
  BuildInfoPayload,
  CommandsCatalogResponse,
  ConfigFullResponse,
  DelegationStatusResponse,
  ForecastDashboardResponse,
  GatewayEvent,
  GatewaySkin,
  SessionMostRecentResponse
} from '../gatewayTypes.js'
import { rpcErrorMessage } from '../lib/rpc.js'
import { topLevelSubagents } from '../lib/subagentTree.js'
import { formatToolCall, stripAnsi } from '../lib/text.js'
import { resolveVoiceSubmission } from '../lib/voiceIntent.js'
import { WireEvent } from '../protocol/generated.js'
import { fromSkin } from '../theme.js'
import type { Msg, SubagentProgress, SubagentStatus } from '../types.js'

import { agentsActiveFromResult, setAgentsActive } from './agentsActiveStore.js'
import { applyCommandEvent } from './commandStore.js'
import { applyDelegationStatus, getDelegationState } from './delegationStore.js'
import { forecastDeskRailSections, forecastDeskStatusLabel } from './forecastPanel.js'
import { getGatewayLink, markLinkLive, takeResumeSid } from './gatewayLinkStore.js'
import type { GatewayEventHandlerContext } from './interfaces.js'
import { raisePrompt } from './overlayStore.js'
import { turnController } from './turnController.js'
import { getUiState, patchUiState } from './uiStore.js'
import { writeActiveSessionFile } from './useSessionLifecycle.js'
import { isWarningsRunActive } from './warningsRunStore.js'

const NO_PROVIDER_RE = /\bNo (?:LLM|inference) provider configured\b/i

const statusFromBusy = () => (getUiState().busy ? 'running…' : 'ready')

// Map the persisted appearance ('light'|'dark'|'auto') to fromSkin's explicit
// light/dark override so the user's choice applies app-wide; 'auto'/unset
// leaves terminal auto-detection in charge.
const appearanceToOverride = (appearance?: string): boolean | undefined =>
  appearance === 'light' ? true : appearance === 'dark' ? false : undefined

const applySkin = (s: GatewaySkin) =>
  patchUiState({
    theme: fromSkin(
      s.colors ?? {},
      s.branding ?? {},
      s.banner_logo ?? '',
      s.banner_hero ?? '',
      s.tool_prefix ?? '',
      s.help_header ?? '',
      appearanceToOverride(s.appearance)
    )
  })

const dropBgTask = (taskId: string) =>
  patchUiState(state => {
    const next = new Set(state.bgTasks)
    next.delete(taskId)

    return { ...state, bgTasks: next }
  })

const pushUnique =
  (max: number) =>
  <T>(xs: T[], x: T): T[] =>
    xs.at(-1) === x ? xs : [...xs, x].slice(-max)

const pushThinking = pushUnique(6)
const pushNote = pushUnique(6)
const pushTool = pushUnique(8)

const KNOWN_SUBAGENT_STATUSES = new Set<SubagentStatus>([
  'completed',
  'error',
  'failed',
  'interrupted',
  'queued',
  'running',
  'timeout'
])

const normalizeSubagentStatus = (status: unknown, fallback: SubagentStatus): SubagentStatus => {
  if (typeof status !== 'string') {
    return fallback
  }

  const normalized = status.toLowerCase() as SubagentStatus

  return KNOWN_SUBAGENT_STATUSES.has(normalized) ? normalized : fallback
}

export function createGatewayEventHandler(ctx: GatewayEventHandlerContext): (ev: GatewayEvent) => void {
  const { rpc } = ctx.gateway
  const { STARTUP_RESUME_ID, newSession, resumeById, setCatalog } = ctx.session
  const { bellOnComplete, stdout, sys } = ctx.system
  const { appendMessage, panel, setHistoryItems } = ctx.transcript
  const { setInput } = ctx.composer
  const { submitRef } = ctx.submission

  const {
    setProcessing: setVoiceProcessing,
    setRecording: setVoiceRecording,
    setSpeaking: setVoiceSpeaking,
    setVoiceEnabled
  } = ctx.voice

  let pendingThinkingStatus = ''
  let thinkingStatusTimer: null | ReturnType<typeof setTimeout> = null
  let startupPromptSubmitted = false
  let startupForecastDashboardShown = false

  // ── gateway.stderr coalescer ────────────────────────────────────────────────
  // A throttle over the diagnostic-noise channel: the FIRST line of a burst paints
  // immediately (leading edge), then further lines within the window are collapsed
  // to the latest one, flushed once when the window closes (trailing edge). A storm
  // of N lines therefore costs O(N / window) re-renders, not N — killing the "keeps
  // repainting to the bottom like log spam" loop while still surfacing the newest
  // line. The full stream is untouched in the gateway-client log buffer.
  let stderrPending: null | string = null
  let stderrTimer: null | ReturnType<typeof setTimeout> = null

  const flushStderr = () => {
    stderrTimer = null

    if (stderrPending !== null) {
      const line = stderrPending
      stderrPending = null
      turnController.pushActivity(line, 'info')
      // A line arrived during this window → keep the pump running so a sustained
      // storm still flushes at the bounded rate instead of stalling.
      stderrTimer = setTimeout(flushStderr, GATEWAY_STDERR_COALESCE_MS)
    }
  }

  const pushStderrCoalesced = (line: string) => {
    stderrPending = line

    if (stderrTimer === null) {
      flushStderr() // leading edge: paint now, then open the coalescing window
    }
  }

  // Inject the disk-save callback into turnController so recordMessageComplete
  // can fire-and-forget a persist without having to plumb a gateway ref around.
  turnController.persistSpawnTree = async (subagents, sessionId) => {
    try {
      const startedAt = subagents.reduce<number>((min, s) => {
        if (!s.startedAt) {
          return min
        }

        return min === 0 ? s.startedAt : Math.min(min, s.startedAt)
      }, 0)

      const top = topLevelSubagents(subagents)
        .map(s => s.goal)
        .filter(Boolean)
        .slice(0, 2)

      const label = top.length ? top.join(' · ') : `${subagents.length} subagents`

      await rpc('spawn_tree.save', {
        finished_at: Date.now() / 1000,
        label: label.slice(0, 120),
        session_id: sessionId ?? 'default',
        started_at: startedAt ? startedAt / 1000 : null,
        subagents
      })
    } catch {
      // Persistence is best-effort; in-memory history is the authoritative
      // same forecast-session source.  A write failure doesn't block the turn.
    }
  }

  // Refresh delegation caps at most every 5s so the status bar HUD can
  // render a /warning close to the configured cap without spamming the RPC.
  let lastDelegationFetchAt = 0

  const refreshDelegationStatus = (force = false) => {
    const now = Date.now()

    if (!force && now - lastDelegationFetchAt < 5000) {
      return
    }

    lastDelegationFetchAt = now
    const sessionId = getUiState().sid

    if (!sessionId) {return}
    rpc<DelegationStatusResponse>('delegation.status', { session_id: sessionId })
      .then(r => {
        if (getUiState().sid === sessionId) {applyDelegationStatus(r)}
      })
      .catch(() => {})
  }

  const setStatus = (status: string) => {
    pendingThinkingStatus = ''

    if (thinkingStatusTimer) {
      clearTimeout(thinkingStatusTimer)
      thinkingStatusTimer = null
    }

    patchUiState({ status })
  }

  const scheduleThinkingStatus = (status: string) => {
    pendingThinkingStatus = status

    if (thinkingStatusTimer) {
      return
    }

    thinkingStatusTimer = setTimeout(() => {
      thinkingStatusTimer = null

      // React can replace this handler while its timer is pending. Completion
      // then clears the new handler's timer, so this old callback must not
      // overwrite the completed desk with a stale "running" label.
      if (!getUiState().busy) {
        return
      }

      patchUiState({ status: pendingThinkingStatus || statusFromBusy() })
    }, STREAM_BATCH_MS)
  }

  const restoreStatusAfter = (ms: number) => {
    turnController.clearStatusTimer()
    turnController.statusTimer = setTimeout(() => {
      turnController.statusTimer = null
      patchUiState({ status: statusFromBusy() })
    }, ms)
  }

  const scheduleStartupPrompt = () => {
    if (startupPromptSubmitted || (!STARTUP_QUERY && !STARTUP_IMAGE)) {
      return
    }

    startupPromptSubmitted = true
    setTimeout(async () => {
      let sid = getUiState().sid

      for (let i = 0; !sid && i < 40; i += 1) {
        await new Promise(resolve => setTimeout(resolve, 100))
        sid = getUiState().sid
      }

      if (!sid) {
        return sys('startup query skipped: no active forecast session')
      }

      if (STARTUP_IMAGE) {
        try {
          await rpc('image.attach', { path: STARTUP_IMAGE, session_id: sid })
        } catch (e) {
          sys(`startup image attach failed: ${rpcErrorMessage(e)}`)
        }
      }

      submitRef.current(STARTUP_QUERY || 'What do you see in this image?')
    }, 0)
  }

  // Pull the desk dashboard and refresh the rail sections (the Home "Today"
  // panel) + the bottom status line. Deliberately does NOT dump a panel into the
  // transcript — that clobbered the clean landing. The full dashboard stays one
  // command away (`/forecast desk`).
  const pullForecastDeskRail = () => {
    rpc<ForecastDashboardResponse>('forecast.dashboard', { fast: true, limit: 8 })
      .then(r => {
        if (!r?.summary && !String(r?.output || '').trim()) {
          return
        }

        patchUiState({
          forecastDeskRailSections: forecastDeskRailSections(r || {}),
          forecastDeskStatus: forecastDeskStatusLabel(r || {})
        })
      })
      .catch(() => {})
    pullContestedCount()
  }

  // The open contested-triage count that drives the Today feed's hand-label badge.
  // A cheap, separate read so a slow/failed triage query never perturbs the rail.
  const pullContestedCount = () => {
    rpc<{ contested?: unknown[]; count?: number }>('forecast.triage.contested', { limit: 200 })
      .then(r => {
        const count = typeof r?.count === 'number' ? r.count : Array.isArray(r?.contested) ? r.contested.length : 0

        patchUiState({ forecastContestedCount: Math.max(0, count) })
      })
      .catch(() => {})
  }

  // Refresh the live-agents aggregate ($agentsActive) immediately on an event that
  // can change the running-job count, so the status-bar "✦ N agents running" chip
  // reacts at once instead of waiting up to a full ~7s poll cycle. Cheap: one
  // aggregate over three local job stores, no network. Best-effort — a failed read
  // leaves the last summary in place (the interval poll will reconcile it).
  const pullAgentsActive = () => {
    rpc<{ count?: number; headline?: string }>('agents.active.summary', {})
      .then(r => setAgentsActive(agentsActiveFromResult(r)))
      .catch(() => {})
  }

  const showStartupForecastDashboard = () => {
    if (startupForecastDashboardShown) {
      return
    }

    startupForecastDashboardShown = true
    pullForecastDeskRail()
  }

  const startNewSession = () => {
    void Promise.resolve(newSession()).finally(showStartupForecastDashboard)
    scheduleStartupPrompt()
  }

  const startResume = (id: string, onUnresumable?: (reason: string) => void) => {
    // Only the gateway-recovery path has a fallback to offer. Every other caller
    // keeps the original single-argument call shape exactly.
    if (onUnresumable) {
      resumeById(id, onUnresumable)
    } else {
      resumeById(id)
    }

    setTimeout(showStartupForecastDashboard, 250)
    scheduleStartupPrompt()
  }

  // Terminal statuses are never overwritten by late-arriving live events —
  // otherwise a stale `subagent.start` / `spawn_requested` can clobber a
  // terminal state from complete (failed/interrupted/timeout/error).
  const isTerminalStatus = (s: SubagentProgress['status']) =>
    s === 'completed' || s === 'error' || s === 'failed' || s === 'interrupted' || s === 'timeout'

  const keepTerminalElseRunning = (s: SubagentProgress['status']) => (isTerminalStatus(s) ? s : 'running')

  // The running application build. Emitted on gateway.ready AND (refreshed) on
  // session.info; an older gateway omits it entirely, so a missing payload must
  // leave whatever we already learned in place rather than blanking it.
  const applyBuild = (build?: BuildInfoPayload | null) => {
    if (build?.version) {
      patchUiState({ build })
    }
  }

  let startupGeneration = 0

  const handleReady = (skin?: GatewaySkin) => {
    const generation = ++startupGeneration
    const currentStartup = () => generation === startupGeneration && getGatewayLink().phase === 'live'

    if (skin) {
      applySkin(skin)
    }

    // Was this ready a RECOVERY rather than a cold start? markLinkLive answers
    // that and flips the link back to 'live' in one step.
    const recovered = markLinkLive()
    // The session that was live when the transport died (single-use).
    const resumeSid = takeResumeSid()

    rpc<CommandsCatalogResponse>('commands.catalog', {})
      .then(r => {
        if (!r?.pairs) {
          return
        }

        setCatalog({
          canon: (r.canon ?? {}) as Record<string, string>,
          categories: r.categories ?? [],
          pairs: r.pairs as [string, string][],
          skillCount: (r.skill_count ?? 0) as number,
          sub: (r.sub ?? {}) as Record<string, string[]>
        })

        if (r.warning) {
          turnController.pushActivity(String(r.warning), 'warn')
        }
      })
      .catch((e: unknown) => turnController.pushActivity(`command catalog unavailable: ${rpcErrorMessage(e)}`, 'info'))

    // ── recovery path ────────────────────────────────────────────────────────
    // A respawned gateway must come back as the SAME desk. Resuming the captured
    // session is what makes the recovery honest: the transcript, usage and info
    // the operator was looking at are genuinely re-established, not quietly
    // replaced by a blank session that merely looks healthy.
    if (recovered) {
      if (resumeSid) {
        patchUiState({ status: 'gateway reconnected · restoring session…' })
        turnController.pushActivity('gateway reconnected · restoring session', 'info')
        // If the session cannot be restored (the gateway died mid-write, the
        // ledger rolled back), open a fresh one and SAY the old one is gone —
        // never leave the desk sid-less and mute.
        startResume(resumeSid, reason => {
          turnController.pushActivity(
            `gateway reconnected · previous session could not be restored (${reason}) · starting a new one`,
            'warn'
          )
          startNewSession()
        })

        return
      }

      // Nothing to restore (the crash landed before a session existed). Say so
      // out loud rather than letting a fresh session pass for the old one.
      patchUiState({ status: 'gateway reconnected · new session' })
      turnController.pushActivity('gateway reconnected · session was reset', 'warn')
      startNewSession()

      return
    }

    if (STARTUP_RESUME_ID) {
      patchUiState({ status: 'resuming…' })
      startResume(STARTUP_RESUME_ID)

      return
    }

    // Opt-in: when `display.tui_auto_resume_recent` is true, look up
    // the most recent human-facing forecast session and resume it instead of
    // starting a brand-new one.  Mirrors classic CLI's
    // `superforecasting-agent -c` / `superforecasting-agent tui` flow
    // and addresses the audit's "forecast session
    // unrecoverable after disconnection" gap.  Default off so existing
    // users aren't surprised.
    rpc<ConfigFullResponse>('config.get', { key: 'full' })
      .then(cfg => {
        if (!currentStartup()) {
          return
        }

        if (!cfg?.config) {
          throw new Error('configuration unavailable')
        }

        if (!cfg.config.display?.tui_auto_resume_recent) {
          patchUiState({ status: 'starting forecast session…' })
          startNewSession()

          return
        }

        return rpc<SessionMostRecentResponse>('session.most_recent', {}).then(r => {
          if (!currentStartup()) {
            return
          }

          if (!r || !('session_id' in r)) {
            throw new Error('saved session lookup unavailable')
          }

          const target = r.session_id

          if (target) {
            patchUiState({ status: 'resuming most recent…' })
            startResume(target)

            return
          }

          patchUiState({ status: 'starting forecast session…' })
          startNewSession()
        })
      })
      .catch((error: unknown) => {
        if (!currentStartup()) {
          return
        }

        patchUiState({ status: 'session startup unavailable' })
        turnController.pushActivity(
          `Could not check saved session state: ${rpcErrorMessage(error)}. Use /resume to retry, or /new to explicitly start a session.`,
          'error'
        )
      })
  }

  let currentTurnId: string | null = null
  const finishedTurnIds = new Set<string>()

  return (ev: GatewayEvent) => {
    const sid = getUiState().sid

    if (applyCommandEvent(ev)) {
      return
    }

    if (ev.session_id && sid && ev.session_id !== sid && !ev.type.startsWith('gateway.')) {
      return
    }

    const turnId = (ev.payload as { turn_id?: string } | undefined)?.turn_id

    if (
      turnId &&
      (
        [WireEvent.MESSAGE_START, WireEvent.MESSAGE_DELTA, WireEvent.MESSAGE_COMPLETE, WireEvent.ERROR] as string[]
      ).includes(ev.type)
    ) {
      if (finishedTurnIds.has(turnId)) {
        return
      }

      if (ev.type === WireEvent.MESSAGE_START) {
        currentTurnId = turnId
      } else if (currentTurnId && turnId !== currentTurnId) {
        return
      }

      if (ev.type === WireEvent.MESSAGE_COMPLETE || ev.type === WireEvent.ERROR) {
        finishedTurnIds.add(turnId)

        // Only recent transport duplicates need retaining; old sessions use
        // a different handler and session identity.
        if (finishedTurnIds.size > 64) {
          finishedTurnIds.delete(finishedTurnIds.values().next().value!)
        }
      }
    }

    switch (ev.type) {
      case WireEvent.GATEWAY_READY:
        // The build identity rides the FIRST frame, so the version is on screen
        // from first paint — no round trip, no waiting on session.info.
        applyBuild(ev.payload?.build)
        handleReady(ev.payload?.skin)

        return

      case WireEvent.SKIN_CHANGED:
        if (ev.payload) {
          applySkin(ev.payload)
        }

        return
      case WireEvent.SESSION_INFO: {
        const info = ev.payload

        if (info.durable_session_id) {
          writeActiveSessionFile(info.durable_session_id)
        }

        // session.info lands after the background update check has usually
        // finished, so it UPGRADES a cold-cache "version only" build into a real
        // staleness verdict. Same store slot, same reducer — one source of truth.
        applyBuild(info.build)

        patchUiState(state => ({
          ...state,
          info,
          status: state.status === 'starting agent…' ? 'ready' : state.status,
          usage: info.usage ? { ...state.usage, ...info.usage } : state.usage
        }))

        setHistoryItems(prev => prev.map(m => (m.kind === 'intro' ? { ...m, info } : m)))

        return
      }

      case WireEvent.THINKING_DELTA: {
        const text = ev.payload?.text

        if (text !== undefined) {
          const value = String(text)
          scheduleThinkingStatus(value || statusFromBusy())

          if (value) {
            turnController.recordReasoningDelta(value)
          }
        }

        return
      }

      case WireEvent.MESSAGE_START:
        turnController.startMessage()

        return
      case WireEvent.STATUS_UPDATE: {
        const p = ev.payload

        if (!p?.text) {
          return
        }

        if (p.kind === 'goal') {
          sys(p.text)

          const brief = p.text.startsWith('✓')
            ? '✓ goal complete'
            : p.text.startsWith('↻')
              ? '↻ goal continuing'
              : p.text.startsWith('⏸')
                ? '⏸ goal paused'
                : 'ready'

          setStatus(brief)
          restoreStatusAfter(6000)

          return
        }

        setStatus(p.text)

        if (p.kind === 'compressing') {
          sys(p.text)

          return
        }

        if (!p.kind || p.kind === 'status') {
          return
        }

        if (turnController.lastStatusNote !== p.text) {
          turnController.lastStatusNote = p.text
          turnController.pushActivity(
            p.text,
            p.kind === 'error' ? 'error' : p.kind === 'warn' || p.kind === 'approval' ? 'warn' : 'info'
          )
        }

        restoreStatusAfter(4000)

        return
      }

      case WireEvent.GATEWAY_STDERR: {
        const line = String(ev.payload.line).slice(0, 120)

        // While the Warnings view owns a live automode pass, its runner logs one
        // (often failing) line PER alert. Those lines are already in the
        // gateway-client log buffer (/logs) — do NOT also stream them into the
        // transcript, or a 130-alert failure scrolls the whole view up and down.
        // The pass's progress + a folded error line render as a fixed bar in the
        // Warnings chrome instead (see warningsRunStore).
        if (isWarningsRunActive()) {
          return
        }

        pushStderrCoalesced(line)

        return
      }

      case WireEvent.BROWSER_PROGRESS: {
        const message = String(ev.payload?.message ?? '').trim()

        if (message) {
          sys(message)
        }

        return
      }

      case WireEvent.VOICE_STATUS: {
        // Continuous VAD loop reports its internal state so the status bar
        // can show listening / transcribing / idle without polling.
        const state = String(ev.payload?.state ?? '')

        if (state === 'listening') {
          setVoiceRecording(true)
          setVoiceProcessing(false)
          setVoiceSpeaking?.(false)
        } else if (state === 'transcribing') {
          setVoiceRecording(false)
          setVoiceProcessing(true)
          setVoiceSpeaking?.(false)
        } else if (state === 'speaking') {
          // The gateway brackets TTS playback with speaking/idle so the status bar can
          // show a live audiogram for the real duration the agent is talking.
          setVoiceRecording(false)
          setVoiceProcessing(false)
          setVoiceSpeaking?.(true)
        } else {
          setVoiceRecording(false)
          setVoiceProcessing(false)
          setVoiceSpeaking?.(false)
        }

        return
      }

      case WireEvent.VOICE_TRANSCRIPT: {
        // CLI parity: the 3-strikes silence detector flipped off automatically.
        // Mirror that on the UI side and tell the user why the mode is off.
        if (ev.payload?.no_speech_limit) {
          setVoiceEnabled(false)
          setVoiceRecording(false)
          setVoiceProcessing(false)
          sys('voice: no speech detected 3 times, continuous mode stopped')

          return
        }

        const text = String(ev.payload?.text ?? '').trim()

        if (!text) {
          return
        }

        // CLI parity: _pending_input.put(transcript) unconditionally feeds
        // the transcript to the agent as its next turn — draft handling
        // doesn't apply because voice-mode users are speaking, not typing.
        //
        // We can't branch on composer input from inside a setInput updater
        // (React strict mode double-invokes it, duplicating the submit).
        // Just clear + defer submit so the cleared input is committed before
        // submit reads it.
        // Map a spoken COMMAND (e.g. "voice off", "open markets") to its slash
        // command so it dispatches instead of becoming an agent turn; dictation and
        // unconfirmed-destructive intents submit verbatim (no risky auto-fire).
        const { submit } = resolveVoiceSubmission(text)
        setInput('')
        setTimeout(() => submitRef.current(submit), 0)

        return
      }

      case WireEvent.GATEWAY_START_TIMEOUT: {
        const { cwd, python, stderr_tail: stderrTail } = ev.payload ?? {}
        const trace = python || cwd ? ` · ${String(python || '')} ${String(cwd || '')}`.trim() : ''

        setStatus('gateway startup timeout')
        turnController.pushActivity(`gateway startup timed out${trace} · /logs to inspect`, 'error')

        // Surface the most useful stderr lines inline so users can tell
        // "wrong python", "missing dep", and "config parse failure"
        // apart without leaving the TUI.  Filter blank rows BEFORE
        // taking the last N so trailing empty lines in the buffer
        // don't crowd out actual content; truncate to match the
        // 120-char clip used for `gateway.stderr` activity entries.
        const STDERR_LINE_CAP = 120
        const STDERR_LINES_MAX = 8

        const tailLines = (stderrTail ?? '')
          .split('\n')
          .map(l => l.trim())
          .filter(Boolean)
          .slice(-STDERR_LINES_MAX)

        for (const line of tailLines) {
          turnController.pushActivity(line.slice(0, STDERR_LINE_CAP), 'error')
        }

        return
      }

      case WireEvent.GATEWAY_PROTOCOL_ERROR:
        setStatus('protocol warning')
        restoreStatusAfter(4000)

        if (!turnController.protocolWarned) {
          turnController.protocolWarned = true
          turnController.pushActivity('protocol noise detected · /logs to inspect', 'info')
        }

        if (ev.payload?.preview) {
          turnController.pushActivity(`protocol noise: ${String(ev.payload.preview).slice(0, 120)}`, 'info')
        }

        return

      case WireEvent.REASONING_DELTA:
        if (ev.payload?.text) {
          turnController.recordReasoningDelta(ev.payload.text)
        }

        return

      case WireEvent.REASONING_AVAILABLE:
        turnController.recordReasoningAvailable(String(ev.payload?.text ?? ''))

        return

      case WireEvent.TOOL_PROGRESS:
        if (ev.payload?.preview && ev.payload.name) {
          turnController.recordToolProgress(ev.payload.name, ev.payload.preview)
        }

        return

      case WireEvent.TOOL_GENERATING:
        if (ev.payload?.name) {
          turnController.pushTrail(`drafting ${ev.payload.name}…`)
        }

        return

      case WireEvent.TOOL_START:
        turnController.recordTodos(ev.payload.todos)
        turnController.recordToolStart(ev.payload.tool_id, ev.payload.name ?? 'tool', ev.payload.context ?? '')

        return
      case WireEvent.TOOL_COMPLETE: {
        // Fold the cumulative usage the gateway now ships on tool.complete into
        // the session usage store — the SAME path message.complete uses. This
        // lands the fresh-work delta (usage.input + usage.output) mid-turn, so
        // the liveness counter's `reported` term climbs on every tool call
        // instead of staying pinned at the turn-start baseline until end-of-turn.
        if (ev.payload.usage) {
          patchUiState(state => ({ ...state, usage: { ...state.usage, ...ev.payload.usage } }))
        }

        const inlineDiffText =
          ev.payload.inline_diff && getUiState().inlineDiffs ? stripAnsi(String(ev.payload.inline_diff)).trim() : ''

        if (inlineDiffText) {
          turnController.recordInlineDiffToolComplete(
            inlineDiffText,
            ev.payload.tool_id,
            ev.payload.name,
            ev.payload.error,
            ev.payload.duration_s
          )
        } else {
          turnController.recordToolComplete(
            ev.payload.tool_id,
            ev.payload.name,
            ev.payload.error,
            ev.payload.summary,
            ev.payload.duration_s,
            ev.payload.todos
          )
        }

        return
      }

      case WireEvent.CLARIFY_REQUEST:
        raisePrompt({
          clarify: { choices: ev.payload.choices, question: ev.payload.question, requestId: ev.payload.request_id }
        })
        setStatus('waiting for input…')

        return
      case WireEvent.APPROVAL_REQUEST: {
        const description = String(ev.payload.description ?? 'dangerous command')

        raisePrompt({ approval: { command: String(ev.payload.command ?? ''), description } })
        setStatus('approval needed')

        return
      }

      case WireEvent.SUDO_REQUEST:
        raisePrompt({ sudo: { requestId: ev.payload.request_id } })
        setStatus('sudo password needed')

        return

      case WireEvent.SECRET_REQUEST:
        raisePrompt({
          secret: { envVar: ev.payload.env_var, prompt: ev.payload.prompt, requestId: ev.payload.request_id }
        })
        setStatus('secret input needed')

        return

      case WireEvent.BACKGROUND_COMPLETE:
        dropBgTask(ev.payload.task_id)
        sys(`[bg ${ev.payload.task_id}] ${ev.payload.text}`)
        // A background process just finished → the live-agent count likely dropped;
        // refresh the chip now rather than waiting for the next poll tick.
        pullAgentsActive()

        return
      case WireEvent.CRON_FIRED: {
        // The gateway's background cron ticker ran and fired N scheduled jobs
        // (nightly self-checks / reforecast sweeps). Surface it as a one-line
        // transient toast — the status line flashes it, then falls back to
        // ready — and re-pull the desk rail so the Home "Today" panel reflects
        // any forecasts that just refreshed. Sessionless event (no session_id).
        const count = Number(ev.payload?.count ?? 0)

        if (count > 0) {
          const label = `nightly self-check ran — ${count} job${count === 1 ? '' : 's'} fired`
          setStatus(label)
          turnController.pushActivity(label, 'info')
          restoreStatusAfter(6000)
          pullForecastDeskRail()
          // Cron can fire reforecast sweeps → new detached jobs; refresh the chip.
          pullAgentsActive()
        }

        return
      }

      case WireEvent.REVIEW_SWEEP: {
        // The gateway due-sweeper acted on due-ness (mirrors cron.fired). 'started'
        // arms a running marker (with the due count) that the Desk turns into a
        // spinner; 'done' clears it, flashes a transient toast built from the REAL
        // payload fields (proposals / alerts / wall time), and re-pulls the desk
        // rail so the Home "Today" panel reflects the proposed updates.
        // Sessionless (no session_id).
        const payload = ev.payload

        if (payload?.phase === 'started') {
          patchUiState({ reviewSweep: { dueCount: Number(payload.due_count ?? 0) } })

          return
        }

        if (payload?.phase === 'done') {
          patchUiState({ reviewSweep: null })

          const proposals = Number(payload.proposals ?? 0)
          const alerts = Number(payload.alerts ?? 0)
          const secs = (Number(payload.duration_ms ?? 0) / 1000).toFixed(1)
          const label = `review sweep: ${proposals} proposed${alerts > 0 ? ` · ${alerts} alert${alerts === 1 ? '' : 's'}` : ''} · ${secs}s`
          setStatus(label)
          turnController.pushActivity(label, 'info')
          restoreStatusAfter(6000)
          pullForecastDeskRail()
          // A sweep can auto-start reforecast/quorum jobs → refresh the chip now.
          pullAgentsActive()
        }

        return
      }

      case WireEvent.REVIEW_SUMMARY: {
        // Self-improvement background review emitted a persistent summary
        // of what it saved to memory/skills. Surface it as a system line
        // in the transcript so it never gets lost to a transient status
        // flash. Python-side already formats it as "💾 Self-improvement
        // review: …".
        const text = String(ev.payload?.text ?? '').trim()

        if (text) {
          sys(text)
        }

        return
      }

      case WireEvent.SUBAGENT_SPAWN_REQUESTED:
        // Child built but not yet running (waiting on ThreadPoolExecutor slot).
        // Preserve completed state if a later event races in before this one.
        turnController.upsertSubagent(ev.payload, c => (isTerminalStatus(c.status) ? {} : { status: 'queued' }))

        // Prime the status-bar HUD: fetch caps (once every 5s) so we can
        // warn as depth/concurrency approaches the configured ceiling.
        if (getDelegationState().maxSpawnDepth === null) {
          refreshDelegationStatus(true)
        } else {
          refreshDelegationStatus()
        }

        return

      case WireEvent.SUBAGENT_START:
        turnController.upsertSubagent(ev.payload, c => (isTerminalStatus(c.status) ? {} : { status: 'running' }))

        return
      case WireEvent.SUBAGENT_THINKING: {
        const text = String(ev.payload.text ?? '').trim()

        if (!text) {
          return
        }

        // Update-only: never resurrect subagents whose spawn_requested/start
        // we missed or that already flushed via message.complete.
        turnController.upsertSubagent(
          ev.payload,
          c => ({
            status: keepTerminalElseRunning(c.status),
            thinking: pushThinking(c.thinking, text)
          }),
          { createIfMissing: false }
        )

        return
      }

      case WireEvent.SUBAGENT_TOOL: {
        const line = formatToolCall(
          ev.payload.tool_name ?? 'delegate_task',
          ev.payload.tool_preview ?? ev.payload.text ?? ''
        )

        turnController.upsertSubagent(
          ev.payload,
          c => ({
            status: keepTerminalElseRunning(c.status),
            tools: pushTool(c.tools, line)
          }),
          { createIfMissing: false }
        )

        return
      }

      case WireEvent.SUBAGENT_PROGRESS: {
        const text = String(ev.payload.text ?? '').trim()

        if (!text) {
          return
        }

        turnController.upsertSubagent(
          ev.payload,
          c => ({
            notes: pushNote(c.notes, text),
            status: keepTerminalElseRunning(c.status)
          }),
          { createIfMissing: false }
        )

        return
      }

      case WireEvent.SUBAGENT_COMPLETE:
        turnController.upsertSubagent(
          ev.payload,
          c => ({
            durationSeconds: ev.payload.duration_seconds ?? c.durationSeconds,
            status: normalizeSubagentStatus(ev.payload.status, 'completed'),
            summary: ev.payload.summary || ev.payload.text || c.summary
          }),
          { createIfMissing: false }
        )

        return

      case WireEvent.MESSAGE_DELTA:
        turnController.recordMessageDelta(ev.payload ?? {})

        return
      case WireEvent.MESSAGE_COMPLETE: {
        const { finalMessages, finalText, wasInterrupted } = turnController.recordMessageComplete(ev.payload ?? {})

        if (!wasInterrupted) {
          const msgs: Msg[] = finalMessages.length ? finalMessages : [{ role: 'assistant', text: finalText }]
          msgs.forEach(appendMessage)

          if (bellOnComplete && stdout?.isTTY) {
            stdout.write('\x07')
          }
        }

        setStatus(
          ev.payload?.durable_status === 'unavailable'
            ? 'recovery state not saved'
            : ev.payload?.status === 'error'
              ? 'turn failed · ready to retry'
              : 'ready'
        )

        if (ev.payload?.usage) {
          patchUiState(state => ({ ...state, usage: { ...state.usage, ...ev.payload!.usage } }))
        }

        return
      }

      case WireEvent.ERROR:
        turnController.recordError()

        {
          const message = String(ev.payload?.message || 'unknown error')

          // Auth/credential expiry: show actionable re-auth steps instead of
          // dumping the raw provider 401 dict at the user.
          if (AUTH_EXPIRED_RE.test(message)) {
            turnController.pushActivity('authentication expired — sign in again', 'error')
            panel(AUTH_EXPIRED_TITLE, buildAuthExpiredSections())
            setStatus('sign-in required')

            return
          }

          turnController.pushActivity(message, 'error')

          if (NO_PROVIDER_RE.test(message)) {
            panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections())
            setStatus('setup required')

            return
          }

          sys(`error: ${message}`)
          setStatus('ready')
        }
    }
  }
}
