import { useCallback, useEffect, useRef, useState } from 'react'

import type { CompletionItem } from '../app/interfaces.js'
import { looksLikeSlashCommand } from '../domain/slash.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { CompletionResponse } from '../gatewayTypes.js'
import { asRpcResult } from '../lib/rpc.js'

const TAB_PATH_RE = /((?:["']?(?:[A-Za-z]:[\\/]|\.{1,2}\/|~\/|\/|@|[^"'`\s]+\/))[^\s]*)$/

export function completionRequestForInput(
  input: string
):
  | { method: 'complete.path'; params: { word: string }; replaceFrom: number }
  | { method: 'complete.slash'; params: { text: string }; replaceFrom: number }
  | null {
  const isSlashCommand = looksLikeSlashCommand(input)
  const pathWord = isSlashCommand ? null : (input.match(TAB_PATH_RE)?.[1] ?? null)

  if (!isSlashCommand && !pathWord) {
    return null
  }

  // `/model` uses the two-step ModelPicker (real curated IDs).
  // Slash completion here only showed short aliases + vendor/family meta.
  if (isSlashCommand && /^\/model(?:\s|$)/.test(input)) {
    return null
  }

  if (isSlashCommand) {
    return { method: 'complete.slash', params: { text: input }, replaceFrom: 1 }
  }

  return {
    method: 'complete.path',
    params: { word: pathWord! },
    replaceFrom: input.length - pathWord!.length
  }
}

export function useCompletion(input: string, blocked: boolean, gw: GatewayClient) {
  const [completions, setCompletions] = useState<CompletionItem[]>([])
  const [compIdx, setCompIdx] = useState(0)
  const [compReplace, setCompReplace] = useState(0)
  const ref = useRef('')
  // Path / @-mention completion is EXPLICIT-TRIGGER only (Tab). `pathArm` is a
  // nonce the composer bumps on that Tab; `lastArm` tracks the value the effect
  // last consumed (so a Tab with unchanged input still re-fires), and `armed`
  // stays true while the menu is open so it keeps filtering as you type — until
  // the trailing path token breaks (request === null), which disarms it.
  const [pathArm, setPathArm] = useState(0)
  const lastArm = useRef(0)
  const armed = useRef(false)

  const armPath = useCallback(() => setPathArm(n => n + 1), [])

  useEffect(() => {
    const clear = () => {
      setCompletions(prev => (prev.length ? [] : prev))
      setCompIdx(prev => (prev ? 0 : prev))
      setCompReplace(prev => (prev ? 0 : prev))
    }

    if (blocked) {
      ref.current = ''
      armed.current = false
      clear()

      return
    }

    const armBumped = pathArm !== lastArm.current

    if (input === ref.current && !armBumped) {
      return
    }

    ref.current = input
    lastArm.current = pathArm

    if (armBumped) {
      armed.current = true
    }

    const request = completionRequestForInput(input)

    if (!request) {
      armed.current = false
      clear()

      return
    }

    // Slash COMMANDS (input starts with '/') auto-complete on every keystroke —
    // that menu IS the feature. Path / @ completion does NOT auto-fire: without
    // this gate, typing ordinary prose that merely contains a '/' or '@'
    // ("and/or", "3/4", "@name") mounted the completion dropdown for a frame and
    // tore it down on the next space — a ~16-row region repaint per token that
    // reads as a full-screen flash on terminals without DEC-2026 synchronized
    // output. It opens only once explicitly armed (Tab), then stays live while
    // the trailing token is unbroken and disarms when it breaks (above).
    if (request.method === 'complete.path' && !armed.current) {
      clear()

      return
    }

    armed.current = request.method === 'complete.path'

    const t = setTimeout(() => {
      if (ref.current !== input) {
        return
      }

      gw.request<CompletionResponse>(request.method, request.params)
        .then(raw => {
          if (ref.current !== input) {
            return
          }

          const r = asRpcResult<CompletionResponse>(raw)

          setCompletions(r?.items ?? [])
          setCompIdx(0)
          setCompReplace(request.method === 'complete.slash' ? (r?.replace_from ?? 1) : request.replaceFrom)
        })
        .catch((e: unknown) => {
          if (ref.current !== input) {
            return
          }

          setCompletions([
            {
              text: '',
              display: 'completion unavailable',
              meta: e instanceof Error && e.message ? e.message : 'unavailable'
            }
          ])
          setCompIdx(0)
          setCompReplace(request.replaceFrom)
        })
    }, 60)

    return () => clearTimeout(t)
  }, [blocked, gw, input, pathArm])

  return { armPath, completions, compIdx, setCompIdx, compReplace }
}
