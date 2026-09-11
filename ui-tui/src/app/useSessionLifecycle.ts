import { writeFileSync } from 'node:fs'

import type { ScrollBoxHandle } from '@superforecasting/ink'
import { evictInkCaches } from '@superforecasting/ink'
import { type RefObject, useCallback } from 'react'

import { buildSetupRequiredSections, SETUP_REQUIRED_TITLE } from '../content/setup.js'
import { introMsg, toTranscriptMessages } from '../domain/messages.js'
import { ZERO } from '../domain/usage.js'
import { type GatewayClient } from '../gatewayClient.js'
import type {
  SessionCloseResponse,
  SessionCreateResponse,
  SessionResumeResponse,
  SessionTitleResponse,
  SetupStatusResponse
} from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'
import type { Msg, PanelSection, SessionInfo, Usage } from '../types.js'

import type { ComposerActions, GatewayRpc, StateSetter } from './interfaces.js'
import { clearPendingPrompts, patchOverlayState } from './overlayStore.js'
import { turnController } from './turnController.js'
import { patchTurnState } from './turnStore.js'
import { getUiState, patchUiState } from './uiStore.js'

const usageFrom = (info: null | SessionInfo): Usage => (info?.usage ? { ...ZERO, ...info.usage } : ZERO)

export const activeSessionFileFromEnv = (env = process.env) =>
  (
    env.SUPERFORECASTING_AGENT_TUI_ACTIVE_SESSION_FILE ??
    env.FORECAST_TUI_ACTIVE_SESSION_FILE ??
    env.HERMES_TUI_ACTIVE_SESSION_FILE ??
    ''
  ).trim() || undefined

export const writeActiveSessionFile = (sessionId: null | string, file = activeSessionFileFromEnv()) => {
  if (!file || !sessionId) {
    return
  }

  try {
    writeFileSync(file, JSON.stringify({ session_id: sessionId }), { mode: 0o600 })
  } catch {
    // Best-effort shell epilogue hint only; never break live forecast-session changes.
  }
}

const trimTail = (items: Msg[]) => {
  const q = [...items]

  while (q.at(-1)?.role === 'assistant' || q.at(-1)?.role === 'tool') {
    q.pop()
  }

  if (q.at(-1)?.role === 'user') {
    q.pop()
  }

  return q
}

export interface UseSessionLifecycleOptions {
  colsRef: { current: number }
  composerActions: ComposerActions
  gw: GatewayClient
  panel: (title: string, sections: PanelSection[]) => void
  rpc: GatewayRpc
  scrollRef: RefObject<null | ScrollBoxHandle>
  setHistoryItems: StateSetter<Msg[]>
  setLastUserMsg: StateSetter<string>
  setSessionStartedAt: StateSetter<number>
  setStickyPrompt: StateSetter<string>
  setVoiceProcessing: StateSetter<boolean>
  setVoiceRecording: StateSetter<boolean>
  sys: (text: string) => void
}

export function useSessionLifecycle(opts: UseSessionLifecycleOptions) {
  const {
    colsRef,
    composerActions,
    gw,
    panel,
    rpc,
    scrollRef,
    setHistoryItems,
    setLastUserMsg,
    setSessionStartedAt,
    setStickyPrompt,
    setVoiceProcessing,
    setVoiceRecording,
    sys
  } = opts

  const closeSession = useCallback(
    (targetSid?: null | string) =>
      targetSid ? rpc<SessionCloseResponse>('session.close', { session_id: targetSid }) : Promise.resolve(null),
    [rpc]
  )

  const resetSession = useCallback(() => {
    turnController.fullReset()
    // A session switch / `/new` abandons any prompts buffered behind the
    // (now-defunct) active prompt of the OLD session.  fullReset() does not
    // touch the module-global prompt buffer, so without this the leftovers
    // would leak into and pop up in the NEXT session.
    clearPendingPrompts()
    setVoiceRecording(false)
    setVoiceProcessing(false)
    patchUiState({ bgTasks: new Set(), info: null, sid: null, usage: ZERO })
    setHistoryItems([])
    setLastUserMsg('')
    setStickyPrompt('')
    composerActions.setPasteSnips([])
    // Half-prune: new forecast sessions have new keys, but keep a warm pool
    // in case the user resumes back to the prior forecast session.
    evictInkCaches('half')
  }, [composerActions, setHistoryItems, setLastUserMsg, setStickyPrompt, setVoiceProcessing, setVoiceRecording])

  const resetVisibleHistory = useCallback(
    (info: null | SessionInfo = null) => {
      turnController.idle()
      turnController.clearReasoning()
      turnController.turnTools = []
      turnController.persistedToolLabels.clear()

      setHistoryItems(info ? [introMsg(info)] : [])
      setStickyPrompt('')
      setLastUserMsg('')
      composerActions.setPasteSnips([])
      patchTurnState({ activity: [] })
      patchUiState({ info, usage: usageFrom(info) })
    },
    [composerActions, setHistoryItems, setLastUserMsg, setStickyPrompt]
  )

  const newSession = useCallback(
    async (msg?: string, title?: string) => {
      const setup = await rpc<SetupStatusResponse>('setup.status', {})

      if (setup?.provider_configured === false) {
        panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections())
        patchUiState({ status: 'setup required' })

        return
      }

      const previousSid = getUiState().sid
      const r = await rpc<SessionCreateResponse>('session.create', { cols: colsRef.current })

      if (!r) {
        return patchUiState({ status: 'ready' })
      }

      try {
        await closeSession(previousSid)
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err)
        sys(`warning: new forecast session created, but the previous session did not close: ${message}`)
      }

      const info = r.info ?? null
      const requestedTitle = title?.trim() ?? ''

      resetSession()
      setSessionStartedAt(Date.now())

      writeActiveSessionFile(r.session_id)
      patchUiState({
        info,
        sid: r.session_id,
        status: info?.version || info?.lazy ? 'ready' : 'starting agent…',
        usage: usageFrom(info)
      })

      if (info) {
        setHistoryItems([introMsg(info)])
      }

      if (info?.credential_warning) {
        sys(`warning: ${info.credential_warning}`)
      }

      if (info?.config_warning) {
        sys(`warning: ${info.config_warning}`)
      }

      if (msg) {
        sys(msg)
      }

      if (requestedTitle) {
        rpc<SessionTitleResponse>('session.title', {
          session_id: r.session_id,
          title: requestedTitle
        })
          .then(result => {
            if (!result || getUiState().sid !== r.session_id) {
              return
            }

            const nextTitle = (result.title ?? requestedTitle).trim()
            const suffix = result.pending ? ' (queued while forecast session initializes)' : ''
            sys(`forecast session title set: ${nextTitle}${suffix}`)
          })
          .catch((err: unknown) => {
            if (getUiState().sid !== r.session_id) {
              return
            }

            const message = err instanceof Error ? err.message : String(err)
            sys(`warning: failed to set forecast session title: ${message}`)
          })
      }
    },
    [closeSession, colsRef, panel, resetSession, rpc, setHistoryItems, setSessionStartedAt, sys]
  )

  // `onUnresumable` fires when the requested session could NOT be restored, so a
  // caller that has no other session to fall back on (the gateway-recovery path)
  // can open a fresh one instead of leaving the desk sid-less and mute. Callers
  // that omit it keep the previous behaviour exactly.
  const resumeById = useCallback(
    (id: string, onUnresumable?: (reason: string) => void) => {
      patchOverlayState({ picker: false })
      patchUiState({ status: 'resuming…' })

      const failed = (reason: string) => {
        patchUiState({ status: 'ready' })

        if (onUnresumable) {
          onUnresumable(reason)
        } else {
          sys(`error: ${reason}`)
        }
      }

      rpc<SetupStatusResponse>('setup.status', {}).then(setup => {
        if (setup?.provider_configured === false) {
          panel(SETUP_REQUIRED_TITLE, buildSetupRequiredSections())
          patchUiState({ status: 'setup required' })

          return
        }

        const previousSid = getUiState().sid

        gw.request<SessionResumeResponse>('session.resume', {
          cols: colsRef.current,
          replace_session_id: previousSid,
          session_id: id
        })
          .then(raw => {
            const r = asRpcResult<SessionResumeResponse>(raw)

            if (!r) {
              return failed('invalid response: session.resume')
            }

            resetSession()
            setSessionStartedAt(Date.now())

            const resumed = toTranscriptMessages(r.messages)
            const recovery = r.recovery

            setHistoryItems(r.info ? [introMsg(r.info), ...resumed] : resumed)

            if (recovery && recovery.status !== 'complete') {
              sys(`Previous turn: ${String(recovery.status)}. Its recovery receipt is retained in the session store.`)

              if (typeof recovery.partial_text === 'string' && recovery.partial_text) {
                sys(`Recovered partial response (not a completed answer):\n${recovery.partial_text}`)
              }
            }

            writeActiveSessionFile(r.resumed ?? r.session_id)
            patchUiState({
              info: r.info ?? null,
              sid: r.session_id,
              status: 'ready',
              usage: usageFrom(r.info ?? null)
            })
            setTimeout(() => scrollRef.current?.scrollToBottom(), 0)
          })
          .catch((e: Error) => failed(e.message))
      })
    },
    [colsRef, gw, panel, resetSession, rpc, scrollRef, setHistoryItems, setSessionStartedAt, sys]
  )

  const guardBusySessionSwitch = useCallback(
    (what = 'switch forecast sessions') => {
      if (!getUiState().busy) {
        return false
      }

      sys(`interrupt the current turn before trying to ${what}`)

      return true
    },
    [sys]
  )

  return {
    closeSession,
    guardBusySessionSwitch,
    newSession,
    resetSession,
    resetVisibleHistory,
    resumeById,
    trimLastExchange: trimTail
  }
}
