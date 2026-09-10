import { withInkSuspended } from '@superforecasting/ink'

import { forecastCommandDisplayName, launchForecastCommand } from '../../../lib/externalCli.js'
import { patchOverlayState } from '../../overlayStore.js'
import { runExternalSetup } from '../../setupHandoff.js'
import type { SlashCommand, SlashRunCtx } from '../types.js'

interface AuthStartResponse {
  interval?: number
  provider?: string
  url?: string
  user_code?: string
}

interface AuthPollResponse {
  credentials_applied?: boolean
  message?: string
  status?: string
  url?: string
  user_code?: string
}

// Keep polling the gateway until the device-code sign-in lands somewhere
// terminal. The gateway's background thread does the real waiting; this just
// narrates the outcome into the transcript.
const watchAuthFlow = (ctx: SlashRunCtx, intervalMs: number) => {
  const startedAt = Date.now()

  const tick = () => {
    if (Date.now() - startedAt > 16 * 60 * 1000) {
      return
    }

    ctx.gateway
      .rpc<AuthPollResponse>('auth.poll', {})
      .then(r => {
        if (!r || r.status === 'pending') {
          setTimeout(tick, intervalMs)

          return
        }

        if (r.status === 'success') {
          ctx.transcript.sys(
            r.credentials_applied
              ? 'signed in to OpenAI Codex — this session is ready, keep going'
              : 'signed in to OpenAI Codex — run /model to start using it'
          )

          return
        }

        if (r.status === 'failed' || r.status === 'cancelled') {
          ctx.transcript.sys(`sign-in ${r.status}: ${r.message || 'try /auth again'}`)
        }
      })
      .catch(() => setTimeout(tick, intervalMs))
  }

  setTimeout(tick, intervalMs)
}

export const setupCommands: SlashCommand[] = [
  {
    aliases: ['login', 'signin', 'reauth'],
    help: 'sign in to an AI provider without leaving the TUI (default: OpenAI Codex)',
    name: 'auth',
    run: (arg, ctx) => {
      const provider = arg.trim() || 'openai-codex'

      ctx.gateway
        .rpc<AuthStartResponse>('auth.start', { provider, session_id: ctx.sid })
        .then(
          ctx.guarded<AuthStartResponse>(r => {
            const intervalMs = Math.max(3, r.interval ?? 5) * 1000

            ctx.transcript.panel('Sign in', [
              {
                rows: [
                  ['1. open', r.url || 'https://auth.openai.com/codex/device'],
                  ['2. enter code', r.user_code || '(no code returned)'],
                  ['then', 'come back here — this session reconnects automatically']
                ],
                title: `${r.provider || provider} sign-in`
              }
            ])
            watchAuthFlow(ctx, intervalMs)
          })
        )
        .catch(ctx.guardedErr)
    }
  },

  {
    aliases: ['themes', 'color', 'colors'],
    help: 'pick a color theme — interactive picker (live preview, light/dark toggle)',
    name: 'theme',
    run: (arg, ctx) => {
      const value = arg.trim().toLowerCase()

      // `/theme light|dark|auto` sets the appearance mode directly.
      if (value === 'light' || value === 'dark' || value === 'auto') {
        ctx.gateway
          .rpc('config.set', { key: 'appearance', value })
          .then(ctx.guarded(() => ctx.transcript.sys(`appearance → ${value}`)))
          .catch(ctx.guardedErr)

        return
      }

      // `/theme <name>` sets a skin directly (fires skin.changed); bare
      // `/theme` opens the live picker.
      if (value) {
        ctx.gateway
          .rpc('config.set', { key: 'skin', value: arg.trim() })
          .then(ctx.guarded(() => ctx.transcript.sys(`theme → ${arg.trim()}`)))
          .catch(ctx.guardedErr)

        return
      }

      patchOverlayState({ themePicker: true })
    }
  },

  {
    help: 'run full setup wizard (launches `superforecasting-agent setup`)',
    name: 'setup',
    run: (arg, ctx) =>
      void runExternalSetup({
        args: ['setup', ...arg.split(/\s+/).filter(Boolean)],
        commandName: forecastCommandDisplayName(),
        ctx,
        done: 'setup complete — starting session…',
        launcher: launchForecastCommand,
        suspend: withInkSuspended
      })
  }
]
