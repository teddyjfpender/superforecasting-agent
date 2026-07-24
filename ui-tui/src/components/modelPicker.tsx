import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useEffect, useMemo, useState } from 'react'

import { providerDisplayNames } from '../domain/providers.js'
import { TUI_SESSION_MODEL_FLAG } from '../domain/slash.js'
import type { GatewayClient } from '../gatewayClient.js'
import type { ModelOptionProvider, ModelOptionsResponse } from '../gatewayTypes.js'
import { asRpcResult, rpcErrorMessage } from '../lib/rpc.js'
import type { Theme } from '../theme.js'

import { OverlayHint, useOverlayKeys, windowItems } from './overlayControls.js'

const VISIBLE = 12
const MIN_WIDTH = 40
const MAX_WIDTH = 90

type Stage = 'provider' | 'key' | 'model' | 'effort' | 'disconnect'

// Reasoning-effort levels offered when a provider/model is effort-capable.
// Kept in sync with hermes_constants.VALID_REASONING_EFFORTS minus `minimal`
// (codex clamps it to `low`). `none` is prepended below: it disables reasoning
// via the dedicated /reasoning plumbing, so a user whose reasoning is currently
// off isn't forced to re-enable it just to switch models.
const FALLBACK_EFFORTS = ['low', 'medium', 'high', 'xhigh']
const NONE_EFFORT = 'none'
const DEFAULT_EFFORT = 'medium'

const EFFORT_HINTS: Record<string, string> = {
  none: 'disable reasoning (no thinking)',
  low: 'fastest · cheapest · least thorough',
  medium: 'balanced default',
  high: 'slower · pricier · more thorough',
  xhigh: 'slowest · most expensive · most thorough',
}

export function ModelPicker({ gw, onCancel, onConnect, onSelect, sessionId, t }: ModelPickerProps) {
  const [providers, setProviders] = useState<ModelOptionProvider[]>([])
  const [currentModel, setCurrentModel] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [persistGlobal, setPersistGlobal] = useState(true)
  const [providerIdx, setProviderIdx] = useState(0)
  const [modelIdx, setModelIdx] = useState(0)
  const [effortIdx, setEffortIdx] = useState(0)
  const [chosenModel, setChosenModel] = useState('')
  const [currentEffort, setCurrentEffort] = useState(DEFAULT_EFFORT)
  const [stage, setStage] = useState<Stage>('provider')
  const [keyInput, setKeyInput] = useState('')
  const [keySaving, setKeySaving] = useState(false)
  const [keyError, setKeyError] = useState('')

  const { stdout } = useStdout()
  // Pin the picker to a stable width so the FloatBox parent (which shrinks-
  // to-fit with alignSelf="flex-start") doesn't resize as long provider /
  // model names scroll into view, and so `wrap="truncate-end"` on each row
  // has an actual constraint to truncate against.
  const width = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, (stdout?.columns ?? 80) - 6))

  useEffect(() => {
    gw.request<ModelOptionsResponse>('model.options', sessionId ? { session_id: sessionId } : {})
      .then(raw => {
        const r = asRpcResult<ModelOptionsResponse>(raw)

        if (!r) {
          setErr('invalid response: model.options')
          setLoading(false)

          return
        }

        const next = r.providers ?? []
        setProviders(next)
        setCurrentModel(String(r.model ?? ''))
        setCurrentEffort(String(r.reasoning_effort || DEFAULT_EFFORT))
        setProviderIdx(
          Math.max(
            0,
            next.findIndex(p => p.is_current)
          )
        )
        setModelIdx(0)
        setStage('provider')
        setErr('')
        setLoading(false)
      })
      .catch((e: unknown) => {
        setErr(rpcErrorMessage(e))
        setLoading(false)
      })
  }, [gw, sessionId])

  const provider = providers[providerIdx]
  const models = provider?.models ?? []
  const names = useMemo(() => providerDisplayNames(providers), [providers])
  // Provider-level hint: True when ANY model in the lineup is effort-capable.
  // Used only for the coarse step-count display (2 vs 3 steps).
  const supportsEffort = provider?.supports_reasoning_effort === true

  // Per-MODEL gating: the effort step shows only when the SELECTED model takes
  // a reasoning.effort dial. A mixed xAI lineup pairs effort-capable models
  // (grok-3-mini, grok-4.3) with non-capable ones (grok-4, grok-4-fast); the
  // backend lists the capable names in `reasoning_effort_models`. Older
  // payloads omit it — fall back to the provider-level flag for those.
  const modelSupportsEffort = (model: string): boolean => {
    if (!provider) {
      return false
    }

    if (Array.isArray(provider.reasoning_effort_models)) {
      return provider.reasoning_effort_models.includes(model)
    }

    return provider.supports_reasoning_effort === true
  }

  const baseEfforts = provider?.reasoning_efforts?.length ? provider.reasoning_efforts : FALLBACK_EFFORTS
  // Prepend a "none" option so a user with reasoning disabled can keep it off
  // when switching models (firing /reasoning none) instead of being forced to
  // re-enable it.
  const efforts = baseEfforts.includes(NONE_EFFORT) ? baseEfforts : [NONE_EFFORT, ...baseEfforts]

  // Commit the chosen model (and optionally the reasoning effort) back to the
  // host, which runs `/model …` and, when an effort is supplied, `/reasoning …`.
  const commit = (model: string, effort?: string) => {
    if (!provider) {
      return
    }

    onSelect(
      `${model} --provider ${provider.slug}${persistGlobal ? ' --global' : ` ${TUI_SESSION_MODEL_FLAG}`}`,
      effort
    )
  }

  const back = () => {
    if (stage === 'effort') {
      setStage('model')
      setEffortIdx(0)

      return
    }

    if (stage === 'model' || stage === 'key' || stage === 'disconnect') {
      setStage('provider')
      setModelIdx(0)
      setKeyInput('')
      setKeyError('')
      setKeySaving(false)

      return
    }

    onCancel()
  }

  useOverlayKeys({ onBack: back, onClose: onCancel })

  useInput((ch, key) => {
    // Key entry stage handles its own input
    if (stage === 'key') {
      if (keySaving) {
        return
      }

      if (key.return) {
        if (!keyInput.trim()) {
          return
        }

        setKeySaving(true)
        setKeyError('')
        gw.request<{ provider?: ModelOptionProvider }>('model.save_key', {
          slug: provider?.slug,
          api_key: keyInput.trim(),
          ...(sessionId ? { session_id: sessionId } : {}),
        })
          .then(raw => {
            const r = asRpcResult<{ provider?: ModelOptionProvider }>(raw)

            if (!r?.provider) {
              setKeyError('failed to save key')
              setKeySaving(false)

              return
            }

            // Update the provider in our list with fresh data
            setProviders(prev =>
              prev.map(p => p.slug === r.provider!.slug ? r.provider! : p)
            )
            setKeyInput('')
            setKeySaving(false)
            setStage('model')
            setModelIdx(0)
          })
          .catch((e: unknown) => {
            setKeyError(rpcErrorMessage(e))
            setKeySaving(false)
          })

        return
      }

      if (key.backspace || key.delete) {
        setKeyInput(v => v.slice(0, -1))

        return
      }

      // ctrl+u clears input
      if (ch === '\u0015') {
        setKeyInput('')

        return
      }

      if (ch && !key.ctrl && !key.meta) {
        setKeyInput(v => v + ch)
      }

      return
    }

    // Disconnect confirmation stage
    if (stage === 'disconnect') {
      if (ch.toLowerCase() === 'y' || key.return) {
        if (!provider) {
          setStage('provider')

          return
        }

        setKeySaving(true)
        gw.request<{ disconnected?: boolean }>('model.disconnect', {
          slug: provider.slug,
          ...(sessionId ? { session_id: sessionId } : {}),
        })
          .then(raw => {
            const r = asRpcResult<{ disconnected?: boolean }>(raw)

            if (r?.disconnected) {
              // Mark provider as unauthenticated in local state
              setProviders(prev =>
                prev.map(p => p.slug === provider.slug
                  ? { ...p, authenticated: false, models: [], total_models: 0, warning: p.key_env ? `paste ${p.key_env} to activate` : 'press ⏎ to sign in (device-code), or run /auth' }
                  : p
                )
              )
            }

            setKeySaving(false)
            setStage('provider')
          })
          .catch(() => {
            setKeySaving(false)
            setStage('provider')
          })

        return
      }

      if (ch.toLowerCase() === 'n' || key.escape) {
        setStage('provider')

        return
      }

      return
    }

    const count =
      stage === 'provider' ? providers.length : stage === 'effort' ? efforts.length : models.length

    const sel = stage === 'provider' ? providerIdx : stage === 'effort' ? effortIdx : modelIdx

    const setSel =
      stage === 'provider' ? setProviderIdx : stage === 'effort' ? setEffortIdx : setModelIdx

    if (key.upArrow && sel > 0) {
      setSel(v => v - 1)

      return
    }

    if (key.downArrow && sel < count - 1) {
      setSel(v => v + 1)

      return
    }

    if (key.return) {
      if (stage === 'provider') {
        if (!provider) {
          return
        }

        if (provider.authenticated === false) {
          // api_key providers: prompt for key inline
          if (provider.auth_type === 'api_key' && provider.key_env) {
            setStage('key')
            setKeyInput('')
            setKeyError('')

            return
          }

          // OAuth providers (Codex, etc.): launch the in-TUI device-code sign-in.
          if (onConnect) {
            onConnect(provider.slug)
          }

          return
        }

        setStage('model')
        setModelIdx(0)

        return
      }

      if (stage === 'effort') {
        const effort = efforts[effortIdx]

        if (chosenModel && effort) {
          commit(chosenModel, effort)
        } else {
          setStage('model')
        }

        return
      }

      const model = models[modelIdx]

      if (provider && model) {
        // Effort-capable SELECTED model → branch to the effort step,
        // pre-selecting the current effort (which may be "none"). Otherwise
        // commit immediately. Gating is per-model so a non-effort grok in an
        // otherwise-capable xAI lineup skips the dead step.
        if (modelSupportsEffort(model)) {
          setChosenModel(model)
          setEffortIdx(Math.max(0, efforts.indexOf(currentEffort)))
          setStage('effort')
        } else {
          commit(model)
        }
      } else {
        setStage('provider')
      }

      return
    }

    if (ch.toLowerCase() === 'g') {
      setPersistGlobal(v => !v)

      return
    }

    // Disconnect: only in provider stage, only for authenticated providers
    if (ch.toLowerCase() === 'd' && stage === 'provider' && provider?.authenticated !== false) {
      setStage('disconnect')

      return
    }
  })

  if (loading) {
    return <Text color={t.color.muted}>loading models…</Text>
  }

  if (err) {
    return (
      <Box flexDirection="column">
        <Text color={t.color.label}>error: {err}</Text>
        <OverlayHint t={t}>Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  if (!providers.length) {
    return (
      <Box flexDirection="column">
        <Text color={t.color.muted}>no providers available</Text>
        <OverlayHint t={t}>Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  // ── Key entry stage ──────────────────────────────────────────────────
  if (stage === 'key' && provider) {
    const masked = keyInput ? '•'.repeat(Math.min(keyInput.length, 40)) : ''

    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Configure {provider.name}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          Paste your API key below (saved to the agent .env)
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          {provider.key_env}:
        </Text>

        <Text color={t.color.accent} wrap="truncate-end">
          {'  '}{masked || '(empty)'}{keySaving ? '' : '▎'}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        {keyError ? (
          <Text color={t.color.label} wrap="truncate-end">
            error: {keyError}
          </Text>
        ) : keySaving ? (
          <Text color={t.color.muted} wrap="truncate-end">
            saving…
          </Text>
        ) : (
          <Text color={t.color.muted} wrap="truncate-end"> </Text>
        )}

        <OverlayHint t={t}>Enter save · Ctrl+U clear · Esc back</OverlayHint>
      </Box>
    )
  }

  // ── Disconnect confirmation stage ─────────────────────────────────────
  if (stage === 'disconnect' && provider) {
    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Disconnect {provider.name}?
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          This removes saved credentials for {provider.name}.
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          You can re-authenticate later by selecting it again.
        </Text>

        <Text color={t.color.muted} wrap="truncate-end"> </Text>

        {keySaving ? (
          <Text color={t.color.muted} wrap="truncate-end">disconnecting…</Text>
        ) : (
          <OverlayHint t={t}>y/Enter confirm · n/Esc cancel</OverlayHint>
        )}
      </Box>
    )
  }

  // ── Provider selection stage ─────────────────────────────────────────
  if (stage === 'provider') {
    const rows = providers.map(
      (p, i) => {
        const authMark = p.authenticated === false ? '○' : p.is_current ? '*' : '●'
        const modelCount = p.total_models ?? p.models?.length ?? 0

        const suffix = p.authenticated === false
          ? (p.auth_type === 'api_key' ? '(no key)' : '(⏎ to sign in)')
          : `${modelCount} models`

        return `${authMark} ${names[i]} · ${suffix}`
      }
    )

    const { items, offset } = windowItems(rows, providerIdx, VISIBLE)

    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Select provider (step 1/{supportsEffort ? '3' : '2'})
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          Full model IDs on the next step · Enter to continue
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          Current: {currentModel || '(unknown)'}
        </Text>
        <Text color={t.color.label} wrap="truncate-end">
          {provider?.warning ? `warning: ${provider.warning}` : ' '}
        </Text>
        <Text color={t.color.muted} wrap="truncate-end">
          {offset > 0 ? ` ↑ ${offset} more` : ' '}
        </Text>

        {Array.from({ length: VISIBLE }, (_, i) => {
          const row = items[i]
          const idx = offset + i
          const p = providers[idx]
          const dimmed = p?.authenticated === false

          return row ? (
            <Text
              bold={providerIdx === idx}
              color={providerIdx === idx ? t.color.accent : dimmed ? t.color.label : t.color.muted}
              inverse={providerIdx === idx}
              key={providers[idx]?.slug ?? `row-${idx}`}
              wrap="truncate-end"
            >
              {providerIdx === idx ? '▸ ' : '  '}
              {idx + 1}. {row}
            </Text>
          ) : (
            <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
              {' '}
            </Text>
          )
        })}

        <Text color={t.color.muted} wrap="truncate-end">
          {offset + VISIBLE < rows.length ? ` ↓ ${rows.length - offset - VISIBLE} more` : ' '}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          persist: {persistGlobal ? 'global' : 'session'} · g toggle
        </Text>
        <OverlayHint t={t}>↑/↓ select · Enter choose · d disconnect · Esc/q cancel</OverlayHint>
      </Box>
    )
  }

  // ── Reasoning effort stage ───────────────────────────────────────────
  if (stage === 'effort') {
    const { items, offset } = windowItems(efforts, effortIdx, VISIBLE)

    return (
      <Box flexDirection="column" width={width}>
        <Text bold color={t.color.accent} wrap="truncate-end">
          Select reasoning effort (step 3/3)
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          {chosenModel || '(model)'} · Esc back
        </Text>
        <Text color={t.color.muted} wrap="truncate-end">
          higher = slower + more expensive + more thorough
        </Text>
        <Text color={t.color.muted} wrap="truncate-end">
          {offset > 0 ? ` ↑ ${offset} more` : ' '}
        </Text>

        {Array.from({ length: VISIBLE }, (_, i) => {
          const row = items[i]
          const idx = offset + i

          if (!row) {
            return (
              <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
                {' '}
              </Text>
            )
          }

          const prefix = effortIdx === idx ? '▸ ' : row === currentEffort ? '* ' : '  '
          const hint = EFFORT_HINTS[row] ? ` — ${EFFORT_HINTS[row]}` : ''

          return (
            <Text
              bold={effortIdx === idx}
              color={effortIdx === idx ? t.color.accent : t.color.muted}
              inverse={effortIdx === idx}
              key={`effort:${idx}:${row}`}
              wrap="truncate-end"
            >
              {prefix}
              {idx + 1}. {row}{hint}
            </Text>
          )
        })}

        <Text color={t.color.muted} wrap="truncate-end">
          {offset + VISIBLE < efforts.length ? ` ↓ ${efforts.length - offset - VISIBLE} more` : ' '}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          current: {currentEffort}
        </Text>
        <OverlayHint t={t}>↑/↓ select · Enter apply · Esc back · q close</OverlayHint>
      </Box>
    )
  }

  // ── Model selection stage ────────────────────────────────────────────
  const { items, offset } = windowItems(models, modelIdx, VISIBLE)

  return (
    <Box flexDirection="column" width={width}>
      <Text bold color={t.color.accent} wrap="truncate-end">
        Select model (step 2/{supportsEffort ? '3' : '2'})
      </Text>

      <Text color={t.color.muted} wrap="truncate-end">
        {names[providerIdx] || '(unknown provider)'} · Esc back
      </Text>
      <Text color={t.color.label} wrap="truncate-end">
        {provider?.warning ? `warning: ${provider.warning}` : ' '}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        {offset > 0 ? ` ↑ ${offset} more` : ' '}
      </Text>

      {Array.from({ length: VISIBLE }, (_, i) => {
        const row = items[i]
        const idx = offset + i

        if (!row) {
          return !models.length && i === 0 ? (
            <Text color={t.color.muted} key="empty" wrap="truncate-end">
              no models listed for this provider
            </Text>
          ) : (
            <Text color={t.color.muted} key={`pad-${i}`} wrap="truncate-end">
              {' '}
            </Text>
          )
        }

        const prefix = modelIdx === idx ? '▸ ' : row === currentModel ? '* ' : '  '

        return (
          <Text
            bold={modelIdx === idx}
            color={modelIdx === idx ? t.color.accent : t.color.muted}
            inverse={modelIdx === idx}
            key={`${provider?.slug ?? 'prov'}:${idx}:${row}`}
            wrap="truncate-end"
          >
            {prefix}
            {idx + 1}. {row}
          </Text>
        )
      })}

      <Text color={t.color.muted} wrap="truncate-end">
        {offset + VISIBLE < models.length ? ` ↓ ${models.length - offset - VISIBLE} more` : ' '}
      </Text>

      <Text color={t.color.muted} wrap="truncate-end">
        persist: {persistGlobal ? 'global' : 'session'} · g toggle
      </Text>
      <OverlayHint t={t}>
        {models.length ? '↑/↓ select · Enter switch · Esc back · q close' : 'Enter/Esc back · q close'}
      </OverlayHint>
    </Box>
  )
}

interface ModelPickerProps {
  gw: GatewayClient
  onCancel: () => void
  // Launch the in-TUI device-code sign-in for an OAuth provider (e.g. Codex):
  // closes the picker and runs `/auth <slug>`. Optional so the picker still
  // renders standalone (tests) — selecting an OAuth provider is then a no-op.
  onConnect?: (slug: string) => void
  onSelect: (value: string, effort?: string) => void
  sessionId: string | null
  t: Theme
}
