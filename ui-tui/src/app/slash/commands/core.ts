import { forceRedraw } from '@hermes/ink'

import { NO_CONFIRM_DESTRUCTIVE } from '../../../config/env.js'
import { dailyFortune, randomFortune } from '../../../content/fortunes.js'
import { HOTKEYS } from '../../../content/hotkeys.js'
import { isSectionName, nextDetailsMode, parseDetailsMode, SECTION_NAMES } from '../../../domain/details.js'
import type {
  ConfigGetValueResponse,
  ConfigSetResponse,
  ForecastCommandResponse,
  ForecastDashboardResponse,
  SessionSaveResponse,
  SessionStatusResponse,
  SessionSteerResponse,
  SessionTitleResponse,
  SessionUndoResponse
} from '../../../gatewayTypes.js'
import { writeClipboardText } from '../../../lib/clipboard.js'
import { FORECAST_TUI_VIEW_SHORTCUTS, type ForecastTuiShortcut } from '../../../lib/forecastShortcuts.js'
import { writeOsc52Clipboard } from '../../../lib/osc52.js'
import { configureDetectedTerminalKeybindings, configureTerminalKeybindings } from '../../../lib/terminalSetup.js'
import type { Msg, PanelSection } from '../../../types.js'
import {
  forecastBookSections,
  forecastDashboardSections,
  forecastDeskRailSections,
  forecastDeskStatusLabel,
  forecastLedgerViewSections,
  forecastQuestionSearchSections,
  rankForecastQuestionMatches
} from '../../forecastPanel.js'
import type { StatusBarMode } from '../../interfaces.js'
import { patchOverlayState } from '../../overlayStore.js'
import { patchUiState } from '../../uiStore.js'
import type { SlashCommand, SlashRunCtx } from '../types.js'

const flagFromArg = (arg: string, current: boolean): boolean | null => {
  if (!arg) {
    return !current
  }

  const mode = arg.trim().toLowerCase()

  if (mode === 'on') {
    return true
  }

  if (mode === 'off') {
    return false
  }

  if (mode === 'toggle') {
    return !current
  }

  return null
}

const RESET_WORDS = new Set(['reset', 'clear', 'default'])
const CYCLE_WORDS = new Set(['cycle', 'toggle'])

const DETAILS_USAGE =
  'usage: /details [hidden|collapsed|expanded|cycle]  or  /details <section> [hidden|collapsed|expanded|reset]'

const DETAILS_SECTION_USAGE = 'usage: /details <section> [hidden|collapsed|expanded|reset]'
const INTEGER_ARG = /^-?\d+$/
const FORECAST_ID_ARG = /^fq_[a-z0-9][a-z0-9_:-]*$/i

const refreshForecastDeskStatus = (ctx: SlashRunCtx) => {
  ctx.gateway
    .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit: 8 })
    .then(
      ctx.guarded<ForecastDashboardResponse>(r => {
        if (r.summary) {
          patchUiState({
            forecastDeskRailSections: forecastDeskRailSections(r),
            forecastDeskStatus: forecastDeskStatusLabel(r)
          })
        }
      })
    )
    .catch(() => {})
}

const renderForecastCommandOutput = (response: ForecastCommandResponse, ctx: SlashRunCtx) => {
  const output = response.output || '(no output)'
  const code = response.code ?? 0
  // Exit code 2 is an argparse usage error — usually a natural-language request
  // sent to the deterministic CLI. Point the user at the agentic path instead of
  // a raw "exited with code 2" so the desk feels conversational, not brittle.
  const text =
    code === 0
      ? output
      : code === 2
        ? `forecast needs more detail to run that as a command (exit ${code}).\n${output}\n\nTip: describe it in plain language instead — e.g. "run the CPI forecast update" or /forecast new <question> — and the agent will fill in the details and execute.`
        : `forecast exited with code ${code}\n${output}`
  const long = text.length > 180 || text.split('\n').filter(Boolean).length > 2

  long ? ctx.transcript.page(text, 'Forecast') : ctx.transcript.sys(text)

  if (code === 0) {
    refreshForecastDeskStatus(ctx)
  }
}

const runForecastCommand = (ctx: SlashRunCtx, arg: string) => {
  ctx.gateway
    .rpc<ForecastCommandResponse>('forecast.command', { arg })
    .then(ctx.guarded<ForecastCommandResponse>(r => renderForecastCommandOutput(r, ctx)))
    .catch(ctx.guardedErr)
}

const runForecastCommandArgv = (ctx: SlashRunCtx, argv: string[]) => {
  ctx.gateway
    .rpc<ForecastCommandResponse>('forecast.command', { argv })
    .then(ctx.guarded<ForecastCommandResponse>(r => renderForecastCommandOutput(r, ctx)))
    .catch(ctx.guardedErr)
}

// A bare `forecast new <question>` invocation would hit the deterministic CLI
// argparser, which requires a quoted title plus --resolution-criteria and exits
// with code 2 on a natural-language question. Creating a well-formed forecast
// (resolution criteria, outcome type, close time, domain/topic, sources) is an
// agentic task, so route natural-language creation to the agent and let it use
// the forecast_ledger create_question action. Power users who pass explicit
// --resolution-criteria still get the deterministic CLI path (see callers).
const FORECAST_NEW_CLI_FLAG = /--resolution-criteria\b/

const runForecastNewViaAgent = (request: string, ctx: SlashRunCtx) => {
  const question = request.trim()

  if (!question) {
    return ctx.transcript.sys(
      'usage: /forecast new <question> — the agent drafts resolution criteria, close time, and sources'
    )
  }

  ctx.transcript.send(
    [
      `Create and execute a new forecast for this request: "${question}".`,
      'Use the forecast_ledger tool (create_question) to register a scoreable question.',
      'Infer clear, checkable resolution criteria, the outcome type, a close/resolution time, and a domain/topic from the request;',
      'if a critical detail is genuinely ambiguous, ask one concise clarifying question before creating.',
      'After creating, report the new forecast id and the resolution criteria you set, then plan the initial sources to gather.'
    ].join(' ')
  )
}

const updateForecastDeskState = (response: ForecastDashboardResponse) => {
  patchUiState({
    forecastDeskRailSections: forecastDeskRailSections(response),
    forecastDeskStatus: forecastDeskStatusLabel(response)
  })
}

const renderForecastDashboard = (response: ForecastDashboardResponse, ctx: SlashRunCtx) => {
  if (response.summary) {
    updateForecastDeskState(response)
    ctx.transcript.panel('Forecast Desk', forecastDashboardSections(response))
    return
  }

  ctx.transcript.page(response.output || '(no forecasts)', 'Forecasts')
}

const renderForecastBook = (response: ForecastDashboardResponse, ctx: SlashRunCtx) => {
  if (response.summary) {
    updateForecastDeskState(response)
    ctx.transcript.panel('Forecast Book', forecastBookSections(response))
    return
  }

  ctx.transcript.page(response.output || '(no forecasts)', 'Forecast Book')
}

const renderForecastSearch = (response: ForecastDashboardResponse, query: string, ctx: SlashRunCtx) => {
  if (response.summary) {
    updateForecastDeskState(response)
  }
  ctx.transcript.panel('Forecast Search', forecastQuestionSearchSections(response, query))
}

// Opening a forecast's full detail routes to the Forecasts workspace overlay
// (the `/desk`-style full-screen pane that fetches `forecast.question` itself
// and renders the tail sections in its own bounded ScrollBox) rather than the
// inline transcript panel — the transcript virtualizer can't bound a 30-60 row
// panel, so it overflowed/glitched while scrolling.
const openForecastDetail = (id: string) => {
  patchOverlayState({ forecasts: true, forecastsInitialId: id })
}

const LEDGER_VIEW_WORDS = new Set([
  'alerts',
  'all',
  'backtests',
  'book',
  'calibration',
  'dashboard',
  'desk',
  'evidence',
  'learning',
  'overview',
  'questions',
  'review',
  'schedules',
  'sources',
  'state',
  'store'
])

const searchNormalizeForLimit = (view: string) => {
  const first = view.trim().toLowerCase().split(/\s+/)[0] || 'book'
  return first === 'search' || !LEDGER_VIEW_WORDS.has(first)
}

const renderForecastLedgerView = (response: ForecastDashboardResponse, view: string, ctx: SlashRunCtx) => {
  if (response.summary) {
    updateForecastDeskState(response)
  }
  ctx.transcript.panel('Forecast Ledger', forecastLedgerViewSections(response, view))
}

const runForecastLedgerView = (view: string, ctx: SlashRunCtx) => {
  const limit = searchNormalizeForLimit(view) ? 75 : 20
  ctx.gateway
    .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit })
    .then(ctx.guarded<ForecastDashboardResponse>(r => renderForecastLedgerView(r, view, ctx)))
    .catch(ctx.guardedErr)
}

const runForecastBook = (arg: string, ctx: SlashRunCtx) => {
  const trimmed = arg.trim()
  const listMatch = trimmed.match(/^list(?:\s+(\d+))?$/i)
  const openIndex = INTEGER_ARG.test(trimmed) ? Number.parseInt(trimmed, 10) : null

  if (trimmed && !listMatch && openIndex === null) {
    if (FORECAST_ID_ARG.test(trimmed)) {
      openForecastDetail(trimmed)
      return
    }

    ctx.gateway
      .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit: 50 })
      .then(ctx.guarded<ForecastDashboardResponse>(r => renderForecastSearch(r, trimmed, ctx)))
      .catch(ctx.guardedErr)
    return
  }

  if (openIndex !== null && openIndex <= 0) {
    return ctx.transcript.sys('usage: /questions [list [limit]|row-number|forecast-id]')
  }

  const listLimit = listMatch?.[1] ? Number.parseInt(listMatch[1], 10) : 20
  if (!Number.isFinite(listLimit) || listLimit <= 0) {
    return ctx.transcript.sys('usage: /questions [list [limit]|row-number|forecast-id]')
  }
  const limit = Math.max(openIndex ?? listLimit, listLimit)

  ctx.gateway
    .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit })
    .then(
      ctx.guarded<ForecastDashboardResponse>(r => {
        if (!r.summary || openIndex === null || listMatch) {
          renderForecastBook(r, ctx)
          return
        }

        updateForecastDeskState(r)
        const row = r.summary.questions?.[openIndex - 1]
        if (!row?.id) {
          ctx.transcript.sys(`no forecast row ${openIndex}; run /questions list ${limit} to inspect current forecast questions`)
          return
        }

        openForecastDetail(row.id)
      })
    )
    .catch(ctx.guardedErr)
}

const runForecastViewShortcut = (shortcut: ForecastTuiShortcut, ctx: SlashRunCtx) => {
  if (shortcut.command === '/questions') {
    return runForecastBook('', ctx)
  }

  if (shortcut.command.startsWith('/ledger ')) {
    return runForecastLedgerView(shortcut.command.slice('/ledger '.length), ctx)
  }

  ctx.transcript.sys(`forecast view shortcut unavailable: ${shortcut.label}`)
}

const forecastViewShortcutCommands: SlashCommand[] = FORECAST_TUI_VIEW_SHORTCUTS.map(shortcut => {
  const digit = shortcut.hotkey.match(/([1-9])$/)?.[1] ?? shortcut.id

  return {
    help: `open forecast ${shortcut.label} view`,
    name: digit,
    run: (_arg, ctx) => runForecastViewShortcut(shortcut, ctx)
  }
})

type ForecastRefResolution =
  | { id: string; response: ForecastDashboardResponse; status: 'resolved' }
  | { matches: ReturnType<typeof rankForecastQuestionMatches>; response: ForecastDashboardResponse; status: 'ambiguous' }
  | { response: ForecastDashboardResponse; status: 'missing' }

const resolveForecastRef = (response: ForecastDashboardResponse, ref: string): ForecastRefResolution => {
  const trimmed = ref.trim()
  const summary = response.summary
  if (!summary || !trimmed) {
    return { response, status: 'missing' }
  }

  const questions = summary.questions ?? []
  const reviewQueue = summary.review_queue ?? []

  if (INTEGER_ARG.test(trimmed)) {
    const index = Number.parseInt(trimmed, 10) - 1
    const row = questions[index]
    return row?.id ? { id: row.id, response, status: 'resolved' } : { response, status: 'missing' }
  }

  const lower = trimmed.toLowerCase()
  const exact = [...questions, ...reviewQueue].find(row => {
    const id = row.id || ''
    return id.toLowerCase() === lower || id.replace(/^fq_/, '').toLowerCase().startsWith(lower)
  })
  if (exact?.id) {
    return { id: exact.id, response, status: 'resolved' }
  }

  const matches = rankForecastQuestionMatches(response, trimmed, 8)
  const top = matches[0]
  const next = matches[1]
  if (top?.row.id && (!next || top.score >= next.score + 10)) {
    return { id: top.row.id, response, status: 'resolved' }
  }

  return matches.length ? { matches, response, status: 'ambiguous' } : { response, status: 'missing' }
}

const withForecastRef = (
  ctx: SlashRunCtx,
  ref: string,
  onResolved: (id: string) => void,
  options: { ambiguousTitle?: string; missingUsage: string } = { missingUsage: 'usage: /open <row|id|words>' }
) => {
  const trimmed = ref.trim()
  if (!trimmed) {
    return ctx.transcript.sys(options.missingUsage)
  }

  ctx.gateway
    .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit: 75 })
    .then(
      ctx.guarded<ForecastDashboardResponse>(response => {
        const resolved = resolveForecastRef(response, trimmed)
        if (resolved.status === 'resolved') {
          onResolved(resolved.id)
          return
        }

        if (resolved.status === 'ambiguous') {
          renderForecastSearch(resolved.response, trimmed, ctx)
          return
        }

        ctx.transcript.sys(`no forecast matched "${trimmed}"; try /find ${trimmed}`)
      })
    )
    .catch(ctx.guardedErr)
}

const splitForecastRefAndRest = (arg: string): { ref: string; rest: string } => {
  const trimmed = arg.trim()
  const separator = trimmed.indexOf(' -- ')
  if (separator >= 0) {
    return {
      ref: trimmed.slice(0, separator).trim(),
      rest: trimmed.slice(separator + 4).trim()
    }
  }

  const parts = trimmed.split(/\s+/)
  return {
    ref: parts[0] || '',
    rest: parts.slice(1).join(' ').trim()
  }
}

const runForecastUpdateShortcut = (arg: string, ctx: SlashRunCtx, missingUsage: string) => {
  const trimmed = arg.trim()
  if (!trimmed) {
    return ctx.transcript.sys(missingUsage)
  }

  if (trimmed.startsWith('-')) {
    return runForecastCommand(ctx, `update ${trimmed}`)
  }

  const { ref, rest } = splitForecastRefAndRest(trimmed)
  if (!rest) {
    return runForecastCommand(ctx, `update ${trimmed}`)
  }

  if (FORECAST_ID_ARG.test(ref)) {
    return runForecastCommand(ctx, `update ${ref} ${rest}`)
  }

  return withForecastRef(ctx, ref, id => runForecastCommand(ctx, `update ${id} ${rest}`), {
    missingUsage
  })
}

export const coreCommands: SlashCommand[] = [
  ...forecastViewShortcutCommands,
  {
    help: 'list commands + hotkeys',
    name: 'help',
    run: (_arg, ctx) => {
      const sections: PanelSection[] = (ctx.local.catalog?.categories ?? []).map(cat => ({
        rows: cat.pairs,
        title: cat.name
      }))

      if (ctx.local.catalog?.skillCount) {
        sections.push({ text: `${ctx.local.catalog.skillCount} skill commands available — /skills to browse` })
      }

      sections.push(
        {
          rows: [
            ['/details [hidden|collapsed|expanded|cycle]', 'set global agent detail visibility mode'],
            [
              '/details <section> [hidden|collapsed|expanded|reset]',
              'override one section (thinking/tools/subagents/activity)'
            ],
            ['/heuristic [random|daily]', 'show a random or daily forecasting maxim'],
            ['/questions [row|list N|words]', 'show current forecast questions, search by words, or drill into a row'],
            ['/ledger [view|search words]', 'jump between forecast book, review, alerts, evidence, learning, schedules, or search'],
            ['/1 … /9', 'portable forecast view shortcuts when Alt/Option is reserved by the terminal'],
            ['/find <words>', 'search active forecasts and review queue without needing a forecast id'],
            ['/open <row|id|words>', 'open one matching forecast ledger record'],
            ['/note <row|words> -- <evidence>', 'append evidence after resolving a row/search to an id'],
            ['/revise <row|words> -- <args>', 'append a probability update after resolving a row/search to an id'],
            ['/forecast [limit|subcommand]', 'show active forecasts or run forecast lifecycle commands'],
            ['/sources [--question <id>] [--json]', 'list adapters or plan sources for a forecast'],
            ['/new-forecast [args]', 'create a scoreable forecast question'],
            ['/ingest [args]', 'stage a URL or file as a forecast candidate'],
            ['/evidence [args]', 'add or inspect timestamped forecast evidence'],
            ['/research [args]', 'collect evidence without moving probability'],
            ['/base-rate [args]', 'add or inspect reference-class/base-rate work'],
            ['/model-run [args]', 'inspect or record a quantitative forecast model run'],
            ['/trend-model [args]', 'record a deterministic trend projection'],
            ['/update <row|id|words> -- <args>', 'append a probability update; no-arg /update updates the app'],
            ['/update-forecast [args]', 'inspect or append a probability update'],
            ['/resolve [args]', 'record a forecast resolution'],
            ['/score [args]', 'score a resolved forecast'],
            ['/postmortem [args]', 'diagnose a resolved forecast'],
            ['/review [args]', 'run forecast review workflow'],
            ['/alerts [args]', 'show forecast alerts'],
            ['/calibration [args]', 'show calibration analytics; defaults to --by-origin'],
            ['/performance [args]', 'show recent backtest performance'],
            ['/readiness [args]', 'show forecast evidence claim gaps'],
            ['/doctor [args]', 'run combined pilot/readiness/operator checks'],
            ['/pilot-report [args]', 'check tester pilot artifact coverage'],
            ['/pilot-cohort [manifest...]', 'seed prospective live pilot questions'],
            ['/pilot-bundle [args]', 'bundle tester handoff evidence'],
            ['/export-packet <id|all> [args]', 'export an auditable forecast packet'],
            ['/import-packet <export.json>', 'restore an exported forecast packet'],
            ['/pilot-aggregate [files...]', 'aggregate tester export packets'],
            ['/lessons [args]', 'list calibration lessons'],
            ['/backtest [args]', 'run or inspect historical replay datasets'],
            ['/schedule [args]', 'list or run scheduled self-checks'],
            ['/autopilot [args]', 'manage autonomous forecast maintenance policies and proposals']
          ],
          title: 'TUI'
        },
        { rows: HOTKEYS, title: 'Hotkeys' }
      )

      ctx.transcript.panel(ctx.ui.theme.brand.helpHeader, sections)
    }
  },

  {
    aliases: ['exit', 'q'],
    help: 'exit forecast desk',
    name: 'quit',
    run: (_arg, ctx) => ctx.session.die()
  },

  {
    help: 'update Superforecasting Agent; with args, append a forecast update',
    name: 'update',
    run: (arg, ctx) => {
      if (arg.trim()) {
        return runForecastUpdateShortcut(
          arg,
          ctx,
          'usage: /update <row|id|forecast words> -- --probability <0-1> --rationale <why>'
        )
      }

      ctx.transcript.sys('exiting TUI to run update...')
      // Exit code 42 signals the Python wrapper to exec the update command.
      // Use dieWithCode for proper cleanup (gateway kill + Ink unmount).
      setTimeout(() => ctx.session.dieWithCode(42), 100)
    }
  },

  {
    aliases: ['scroll'],
    help: 'toggle mouse/wheel tracking [on|off|toggle]',
    name: 'mouse',
    run: (arg, ctx) => {
      const current = ctx.ui.mouseTracking
      const next = flagFromArg(arg, current)

      if (next === null) {
        return ctx.transcript.sys('usage: /mouse [on|off|toggle]')
      }

      patchUiState({ mouseTracking: next })
      ctx.gateway.rpc<ConfigSetResponse>('config.set', { key: 'mouse', value: next ? 'on' : 'off' }).catch(() => {})

      queueMicrotask(() => ctx.transcript.sys(`mouse tracking ${next ? 'on' : 'off'}`))
    }
  },

  {
    aliases: ['new'],
    help: 'start a new forecast session',
    name: 'clear',
    run: (arg, ctx, cmd) => {
      if (ctx.session.guardBusySessionSwitch('switch forecast sessions')) {
        return
      }

      const isNew = cmd.startsWith('/new')
      const requestedTitle = isNew ? arg.trim() : ''

      const commit = () => {
        patchUiState({ status: 'starting forecast session…' })
        ctx.session.newSession(isNew ? 'new forecast session started' : undefined, requestedTitle || undefined)
      }

      if (NO_CONFIRM_DESTRUCTIVE) {
        return commit()
      }

      patchOverlayState({
        confirm: {
          cancelLabel: 'No, keep going',
          confirmLabel: isNew ? 'Yes, start a new forecast session' : 'Yes, clear the forecast session',
          danger: true,
          detail: 'This ends the current forecast desk exchange and clears the transcript.',
          onConfirm: commit,
          title: isNew ? 'Start a new forecast session?' : 'Clear the current forecast session?'
        }
      })
    }
  },

  {
    aliases: ['book', 'qbook'],
    help: 'show or search forecast questions; /questions <row> opens details',
    name: 'questions',
    run: (arg, ctx) => runForecastBook(arg, ctx)
  },

  {
    aliases: ['search-forecasts', 'lookup'],
    help: 'search active forecasts and review queue by title, topic, or domain',
    name: 'find',
    run: (arg, ctx) => {
      const query = arg.trim()
      if (!query) {
        return ctx.transcript.sys('usage: /find <forecast words>')
      }

      ctx.gateway
        .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit: 75 })
        .then(ctx.guarded<ForecastDashboardResponse>(r => renderForecastSearch(r, query, ctx)))
        .catch(ctx.guardedErr)
    }
  },

  {
    aliases: ['question', 'show-forecast'],
    help: 'open a forecast by row number, id, short id, or search words',
    name: 'open',
    run: (arg, ctx) =>
      withForecastRef(ctx, arg, id => openForecastDetail(id), {
        missingUsage: 'usage: /open <row|id|forecast words>'
      })
  },

  {
    aliases: ['store', 'state'],
    help: 'browse forecast ledger views without remembering forecast ids',
    name: 'ledger',
    run: (arg, ctx) => {
      const view = arg.trim() || 'book'
      runForecastLedgerView(view, ctx)
    }
  },

  {
    aliases: ['evidence-for', 'note-for'],
    help: 'append an evidence note to a forecast resolved by row or search words',
    name: 'note',
    run: (arg, ctx) => {
      const { ref, rest } = splitForecastRefAndRest(arg)
      if (!ref || !rest) {
        return ctx.transcript.sys('usage: /note <row|id|forecast words> -- <evidence note>')
      }

      withForecastRef(ctx, ref, id => runForecastCommandArgv(ctx, ['research', id, rest]), {
        missingUsage: 'usage: /note <row|id|forecast words> -- <evidence note>'
      })
    }
  },

  {
    aliases: ['update-for', 'updateq'],
    help: 'append a probability update to a forecast resolved by row or search words',
    name: 'revise',
    run: (arg, ctx) => {
      const { ref, rest } = splitForecastRefAndRest(arg)
      if (!ref || !rest) {
        return ctx.transcript.sys(
          'usage: /revise <row|id|forecast words> -- --probability <0-1> --rationale <why>'
        )
      }

      runForecastUpdateShortcut(
        arg,
        ctx,
        'usage: /revise <row|id|forecast words> -- --probability <0-1> --rationale <why>'
      )
    }
  },

  {
    aliases: ['forecasts', 'desk'],
    help: 'open the interactive forecasts workspace (or run forecast lifecycle commands)',
    name: 'forecast',
    run: (arg, ctx) => {
      const trimmed = arg.trim()

      // `/forecast status` (and synonyms) keeps the classic full-text desk
      // report — doctor gate, calibration, evidence status, the lot.
      if (/^(status|dashboard|report|overview)$/i.test(trimmed)) {
        ctx.gateway
          .rpc<ForecastDashboardResponse>('forecast.dashboard', { limit: 20 })
          .then(ctx.guarded<ForecastDashboardResponse>(r => renderForecastDashboard(r, ctx)))
          .catch(ctx.guardedErr)
        return
      }

      if (trimmed && !INTEGER_ARG.test(trimmed)) {
        const newMatch = trimmed.match(/^new\b\s*([\s\S]*)$/i)
        if (newMatch && !FORECAST_NEW_CLI_FLAG.test(trimmed)) {
          return runForecastNewViaAgent(newMatch[1] ?? '', ctx)
        }

        // A forecast id opens the workspace focused on that forecast.
        if (FORECAST_ID_ARG.test(trimmed)) {
          patchOverlayState({ forecasts: true, forecastsInitialId: trimmed })
          return
        }

        ctx.gateway
          .rpc<ForecastCommandResponse>('forecast.command', { arg: trimmed })
          .then(ctx.guarded<ForecastCommandResponse>(r => renderForecastCommandOutput(r, ctx)))
          .catch(ctx.guardedErr)

        return
      }

      // Empty or integer arg → open the navigable workspace.
      patchOverlayState({ forecasts: true, forecastsInitialId: null })
    }
  },

  {
    aliases: ['adapters', 'source-adapters'],
    help: 'list adapters or plan forecast evidence sources',
    name: 'sources',
    run: (arg, ctx) => runForecastCommand(ctx, `sources ${arg.trim()}`.trim())
  },

  {
    aliases: ['reviews'],
    help: 'review stale forecasts and required forecast work',
    name: 'review',
    run: (arg, ctx) => runForecastCommand(ctx, `review ${arg.trim() || '--stale'}`.trim())
  },

  {
    aliases: ['import-candidate'],
    help: 'stage a URL or file as a forecast candidate',
    name: 'ingest',
    run: (arg, ctx) => runForecastCommand(ctx, `ingest ${arg.trim()}`.trim())
  },

  {
    aliases: ['ev'],
    help: 'add or inspect timestamped forecast evidence',
    name: 'evidence',
    run: (arg, ctx) => runForecastCommand(ctx, `evidence ${arg.trim()}`.trim())
  },

  {
    aliases: ['forecast-research'],
    help: 'collect forecast evidence without moving probability',
    name: 'research',
    run: (arg, ctx) => runForecastCommand(ctx, `research ${arg.trim()}`.trim())
  },

  {
    aliases: ['new-question', 'newq'],
    help: 'create a scoreable forecast question (the agent drafts the details)',
    name: 'new-forecast',
    run: (arg, ctx) => {
      const trimmed = arg.trim()
      if (trimmed && FORECAST_NEW_CLI_FLAG.test(trimmed)) {
        return runForecastCommand(ctx, `new ${trimmed}`.trim())
      }
      return runForecastNewViaAgent(trimmed, ctx)
    }
  },

  {
    help: 'add or inspect reference-class/base-rate work',
    name: 'base-rate',
    run: (arg, ctx) => runForecastCommand(ctx, `base-rate ${arg.trim()}`.trim())
  },

  {
    aliases: ['forecast-model'],
    help: 'inspect or record a quantitative forecast model run',
    name: 'model-run',
    run: (arg, ctx) => runForecastCommand(ctx, `model ${arg.trim()}`.trim())
  },

  {
    aliases: ['trend-projection'],
    help: 'record a deterministic trend projection model run',
    name: 'trend-model',
    run: (arg, ctx) => {
      const trimmed = arg.trim()
      return runForecastCommand(ctx, `model ${trimmed}${trimmed ? ' ' : ''}--type trend_projection`)
    }
  },

  {
    aliases: ['forecast-update'],
    help: 'inspect or append a probability update',
    name: 'update-forecast',
    run: (arg, ctx) =>
      runForecastUpdateShortcut(arg, ctx, 'usage: /update-forecast <row|id|forecast words> [-- <args>]')
  },

  {
    help: 'record a forecast resolution',
    name: 'resolve',
    run: (arg, ctx) => runForecastCommand(ctx, `resolve ${arg.trim()}`.trim())
  },

  {
    help: 'score a resolved forecast',
    name: 'score',
    run: (arg, ctx) => runForecastCommand(ctx, `score ${arg.trim()}`.trim())
  },

  {
    help: 'diagnose a resolved forecast',
    name: 'postmortem',
    run: (arg, ctx) => runForecastCommand(ctx, `postmortem ${arg.trim()}`.trim())
  },

  {
    help: 'show forecast alert queue',
    name: 'alerts',
    run: (arg, ctx) => runForecastCommand(ctx, `alerts ${arg.trim()}`.trim())
  },

  {
    help: 'show forecast calibration analytics',
    name: 'calibration',
    run: (arg, ctx) => runForecastCommand(ctx, `calibration ${arg.trim() || '--by-origin'}`.trim())
  },

  {
    help: 'show recent backtest performance',
    name: 'performance',
    run: (arg, ctx) => runForecastCommand(ctx, `performance ${arg.trim()}`.trim())
  },

  {
    help: 'show forecast evidence claim gaps',
    name: 'readiness',
    run: (arg, ctx) => runForecastCommand(ctx, `readiness ${arg.trim()}`.trim())
  },

  {
    help: 'run combined pilot/readiness/operator checks',
    name: 'doctor',
    run: (arg, ctx) => runForecastCommand(ctx, `doctor ${arg.trim()}`.trim())
  },

  {
    // Manage data-provider API keys (FRED, EIA, Firecrawl, Exa, …). Writes the
    // key to ~/.superforecasting-agent/.env and activates it for subsequent
    // forecast invocations — so the next agent run picks up e.g. FRED_API_KEY
    // and stops falling back to the flaky public CSV endpoint. Pasting the key
    // into the composer puts it in this session's transcript; for a fully
    // private add use `forecast api-key set <provider> --from-stdin` in a
    // terminal outside the TUI.
    aliases: ['apikey', 'api-keys', 'keys'],
    help: 'list / set / unset data-provider API keys (FRED, EIA, web search, …)',
    name: 'api-key',
    run: (arg, ctx) => {
      const trimmed = arg.trim()
      // Default to listing so `/api-key` alone shows what's set vs not.
      runForecastCommand(ctx, `api-key ${trimmed || 'list'}`.trim())
    }
  },

  {
    aliases: ['pilot'],
    help: 'check tester pilot artifact coverage',
    name: 'pilot-report',
    run: (arg, ctx) => runForecastCommand(ctx, `pilot-report ${arg.trim()}`.trim())
  },

  {
    help: 'seed prospective live pilot questions',
    name: 'pilot-cohort',
    run: (arg, ctx) => runForecastCommand(ctx, `pilot-cohort ${arg.trim()}`.trim())
  },

  {
    help: 'bundle tester handoff evidence',
    name: 'pilot-bundle',
    run: (arg, ctx) => runForecastCommand(ctx, `pilot-bundle ${arg.trim()}`.trim())
  },

  {
    aliases: ['packet-export', 'export-forecast'],
    help: 'export an auditable forecast packet',
    name: 'export-packet',
    run: (arg, ctx) => runForecastCommand(ctx, `export ${arg.trim()}`.trim())
  },

  {
    aliases: ['packet-import'],
    help: 'restore an exported forecast packet',
    name: 'import-packet',
    run: (arg, ctx) => runForecastCommand(ctx, `import packet ${arg.trim()}`.trim())
  },

  {
    help: 'aggregate tester export packets',
    name: 'pilot-aggregate',
    run: (arg, ctx) => runForecastCommand(ctx, `pilot-aggregate ${arg.trim()}`.trim())
  },

  {
    aliases: ['lesson', 'learning'],
    help: 'list forecast calibration lessons',
    name: 'lessons',
    run: (arg, ctx) => runForecastCommand(ctx, `lesson list ${arg.trim()}`.trim())
  },

  {
    aliases: ['backtests'],
    help: 'run or inspect historical replay datasets',
    name: 'backtest',
    run: (arg, ctx) => runForecastCommand(ctx, `backtest ${arg.trim() || '--benchmarks'}`.trim())
  },

  {
    aliases: ['cron'],
    help: 'manage scheduled forecast self-checks',
    name: 'schedule',
    run: (arg, ctx) => runForecastCommand(ctx, `schedule ${arg.trim() || 'list'}`.trim())
  },

  {
    help: 'manage autonomous forecast maintenance policies',
    name: 'autopilot',
    run: (arg, ctx) => runForecastCommand(ctx, `autopilot ${arg.trim() || 'status'}`.trim())
  },

  {
    help: 'show domain and topic error profiles',
    name: 'errors',
    run: (arg, ctx) => runForecastCommand(ctx, `errors ${arg.trim()}`.trim())
  },

  {
    help: 'run forecast self-check alerts',
    name: 'self-check',
    run: (arg, ctx) => runForecastCommand(ctx, `self-check ${arg.trim()}`.trim())
  },

  {
    help: 'force a full UI repaint',
    name: 'redraw',
    run: (_arg, ctx) => {
      forceRedraw(process.stdout)
      ctx.transcript.sys('ui redrawn')
    }
  },

  {
    help: 'show live forecast session info',
    name: 'status',
    run: (_arg, ctx) => {
      if (!ctx.sid) {
        return ctx.transcript.sys('no active forecast session')
      }

      ctx.gateway
        .rpc<SessionStatusResponse>('session.status', { session_id: ctx.sid })
        .then(ctx.guarded<SessionStatusResponse>(r => ctx.transcript.page(r.output || '(no status)', 'Forecast Desk Status')))
        .catch(ctx.guardedErr)
    }
  },

  {
    help: 'resume a prior forecast session',
    name: 'resume',
    run: (arg, ctx) => {
      if (ctx.session.guardBusySessionSwitch('switch forecast sessions')) {
        return
      }

      arg ? ctx.session.resumeById(arg) : patchOverlayState({ picker: true })
    }
  },

  {
    help: 'set or show current forecast session title',
    name: 'title',
    run: (arg, ctx) => {
      if (!ctx.sid) {
        return ctx.transcript.sys('no active forecast session')
      }

      const title = arg.trim()

      if (!arg) {
        ctx.gateway
          .rpc<SessionTitleResponse>('session.title', { session_id: ctx.sid })
          .then(
            ctx.guarded<SessionTitleResponse>(r => {
              const current = (r?.title ?? '').trim()
              ctx.transcript.sys(current ? `title: ${current}` : 'no title set')
            })
          )
          .catch(ctx.guardedErr)

        return
      }

      if (!title) {
        return ctx.transcript.sys('usage: /title <your forecast session title>')
      }

      ctx.gateway
        .rpc<SessionTitleResponse>('session.title', { session_id: ctx.sid, title })
        .then(
          ctx.guarded<SessionTitleResponse>(r => {
            const next = (r?.title ?? title).trim()
            const suffix = r?.pending ? ' (queued while forecast session initializes)' : ''
            ctx.transcript.sys(`forecast session title set: ${next}${suffix}`)
          })
        )
        .catch(ctx.guardedErr)
    }
  },

  {
    help: 'toggle compact transcript',
    name: 'compact',
    run: (arg, ctx) => {
      const next = flagFromArg(arg, ctx.ui.compact)

      if (next === null) {
        return ctx.transcript.sys('usage: /compact [on|off|toggle]')
      }

      patchUiState({ compact: next })
      ctx.gateway.rpc<ConfigSetResponse>('config.set', { key: 'compact', value: next ? 'on' : 'off' }).catch(() => {})

      queueMicrotask(() => ctx.transcript.sys(`compact ${next ? 'on' : 'off'}`))
    }
  },

  {
    aliases: ['detail'],
    help: 'control agent detail visibility (global or per-section)',
    name: 'details',
    run: (arg, ctx) => {
      const { gateway, transcript, ui } = ctx

      if (!arg) {
        gateway
          .rpc<ConfigGetValueResponse>('config.get', { key: 'details_mode' })
          .then(r => {
            if (ctx.stale()) {
              return
            }

            const mode = parseDetailsMode(r?.value) ?? ui.detailsMode
            patchUiState({ detailsMode: mode, detailsModeCommandOverride: false })

            const overrides = SECTION_NAMES.filter(s => ui.sections[s])
              .map(s => `${s}=${ui.sections[s]}`)
              .join(' ')

            transcript.sys(`details: ${mode}${overrides ? `  (${overrides})` : ''}`)
          })
          .catch(() => !ctx.stale() && transcript.sys(`details: ${ui.detailsMode}`))

        return
      }

      const [first, second] = arg.trim().toLowerCase().split(/\s+/)

      if (second && isSectionName(first)) {
        const reset = RESET_WORDS.has(second)
        const mode = reset ? null : parseDetailsMode(second)

        if (!reset && !mode) {
          return transcript.sys(DETAILS_SECTION_USAGE)
        }

        const { [first]: _drop, ...rest } = ui.sections

        patchUiState({ sections: mode ? { ...rest, [first]: mode } : rest })
        gateway
          .rpc<ConfigSetResponse>('config.set', { key: `details_mode.${first}`, value: mode ?? '' })
          .catch(() => {})
        transcript.sys(`details ${first}: ${mode ?? 'reset'}`)

        return
      }

      const next = CYCLE_WORDS.has(first ?? '') ? nextDetailsMode(ui.detailsMode) : parseDetailsMode(first)

      if (!next) {
        return transcript.sys(DETAILS_USAGE)
      }

      const sections = Object.fromEntries(SECTION_NAMES.map(section => [section, next]))

      patchUiState({ detailsMode: next, detailsModeCommandOverride: true, sections })
      gateway.rpc<ConfigSetResponse>('config.set', { key: 'details_mode', value: next }).catch(() => {})
      transcript.sys(`details: ${next}`)
    }
  },

  {
    aliases: ['fortune'],
    help: 'forecasting maxim',
    name: 'heuristic',
    run: (arg, ctx) => {
      const key = arg.trim().toLowerCase()

      if (!arg || key === 'random') {
        return ctx.transcript.sys(randomFortune())
      }

      if (['daily', 'stable', 'today'].includes(key)) {
        return ctx.transcript.sys(dailyFortune(ctx.sid))
      }

      ctx.transcript.sys('usage: /heuristic [random|daily]')
    }
  },

  {
    help: 'copy selection or forecast desk response',
    name: 'copy',
    run: async (arg, ctx) => {
      const { sys } = ctx.transcript

      if (!arg && ctx.composer.hasSelection) {
        const text = await ctx.composer.selection.copySelection()

        if (text) {
          return sys(`copied ${text.length} characters`)
        } else {
          return sys(
            'clipboard copy failed — try SUPERFORECASTING_AGENT_TUI_FORCE_OSC52=1 to force the escape sequence; SUPERFORECASTING_AGENT_TUI_DEBUG_CLIPBOARD=1 for details'
          )
        }
      }

      if (arg && Number.isNaN(parseInt(arg, 10))) {
        return sys('usage: /copy [number]')
      }

      const all = ctx.local.getHistoryItems().filter(m => m.role === 'assistant')
      const target = all[arg ? Math.min(parseInt(arg, 10), all.length) - 1 : all.length - 1]

      if (!target) {
        return sys('nothing to copy — run a forecast desk turn first')
      }

      void writeClipboardText(target.text)
        .then(nativeOk => {
          if (ctx.stale()) {
            return
          }

          if (nativeOk) {
            sys('copied to clipboard')
          } else {
            writeOsc52Clipboard(target.text)
            sys('sent OSC52 copy sequence (terminal support required)')
          }
        })
        .catch(error => {
          if (!ctx.stale()) {
            sys(`copy failed: ${String(error)}`)
          }
        })
    }
  },

  {
    help: 'attach clipboard image',
    name: 'paste',
    run: (arg, ctx) => (arg ? ctx.transcript.sys('usage: /paste') : ctx.composer.paste())
  },

  {
    help: 'configure IDE terminal keybindings for multiline + undo/redo',
    name: 'terminal-setup',
    run: (arg, ctx) => {
      const target = arg.trim().toLowerCase()

      if (target && !['auto', 'cursor', 'vscode', 'windsurf'].includes(target)) {
        return ctx.transcript.sys('usage: /terminal-setup [auto|vscode|cursor|windsurf]')
      }

      const runner =
        !target || target === 'auto'
          ? configureDetectedTerminalKeybindings()
          : configureTerminalKeybindings(target as 'cursor' | 'vscode' | 'windsurf')

      void runner
        .then(result => {
          if (ctx.stale()) {
            return
          }

          ctx.transcript.sys(result.message)

          if (result.success && result.requiresRestart) {
            ctx.transcript.sys('restart the IDE terminal for the new keybindings to take effect')
          }
        })
        .catch(error => {
          if (!ctx.stale()) {
            ctx.transcript.sys(`terminal setup failed: ${String(error)}`)
          }
        })
    }
  },

  {
    help: 'view gateway logs',
    name: 'logs',
    run: (arg, ctx) => {
      const text = ctx.gateway.gw.getLogTail(Math.min(80, Math.max(1, parseInt(arg, 10) || 20)))

      text ? ctx.transcript.page(text, 'Logs') : ctx.transcript.sys('no gateway logs')
    }
  },

  {
    help: 'view current forecast transcript (user + forecast desk responses)',
    name: 'history',
    run: (arg, ctx) => {
      // The CLI-side `/history` runs in a detached slash-worker subprocess
      // that never sees the TUI's turns — it only surfaces whatever was
      // persisted before this process started.  Render the TUI's own
      // transcript so `/history` actually reflects what the user just did.
      const items = ctx.local.getHistoryItems().filter(m => m.role === 'user' || m.role === 'assistant')

      if (!items.length) {
        return ctx.transcript.sys('no forecast transcript yet')
      }

      const preview = Math.max(80, parseInt(arg, 10) || 400)

      const lines = items.map((m, i) => {
        const tag = m.role === 'user' ? `You #${i + 1}` : `Forecast Desk #${i + 1}`
        const body = m.text.trim() || (m.tools?.length ? `(${m.tools.length} tool calls)` : '(empty)')
        const clipped = body.length > preview ? `${body.slice(0, preview).trimEnd()}…` : body

        return `[${tag}]\n${clipped}`
      })

      ctx.transcript.page(lines.join('\n\n'), 'History')
    }
  },

  {
    help: 'save the current forecast transcript to JSON',
    name: 'save',
    run: (_arg, ctx) => {
      const hasConversation = ctx.local
        .getHistoryItems()
        .some(m => m.role === 'user' || m.role === 'assistant' || m.role === 'tool')

      if (!hasConversation) {
        return ctx.transcript.sys('no forecast transcript yet')
      }

      if (!ctx.sid) {
        return ctx.transcript.sys('no active forecast session — nothing to save')
      }

      ctx.gateway
        .rpc<SessionSaveResponse>('session.save', { session_id: ctx.sid })
        .then(
          ctx.guarded<SessionSaveResponse>(r => {
            const file = r?.file

            if (file) {
              ctx.transcript.sys(`forecast transcript saved to: ${file}`)
            } else {
              ctx.transcript.sys('failed to save')
            }
          })
        )
        .catch(ctx.guardedErr)
    }
  },

  {
    aliases: ['sb'],
    help: 'status bar position (on|off|top|bottom)',
    name: 'statusbar',
    run: (arg, ctx) => {
      const mode = arg.trim().toLowerCase()
      const toggle: StatusBarMode = ctx.ui.statusBar === 'off' ? 'top' : 'off'

      const next: null | StatusBarMode =
        !mode || mode === 'toggle'
          ? toggle
          : mode === 'on' || mode === 'top'
            ? 'top'
            : mode === 'off' || mode === 'bottom'
              ? mode
              : null

      if (!next) {
        return ctx.transcript.sys('usage: /statusbar [on|off|top|bottom|toggle]')
      }

      patchUiState({ statusBar: next })
      ctx.gateway.rpc<ConfigSetResponse>('config.set', { key: 'statusbar', value: next }).catch(() => {})

      queueMicrotask(() => ctx.transcript.sys(`status bar ${next}`))
    }
  },

  {
    help: 'inspect or enqueue a forecast note',
    name: 'queue',
    run: (arg, ctx) => {
      if (!arg) {
        return ctx.transcript.sys(`${ctx.composer.queueRef.current.length} queued forecast note(s)`)
      }

      ctx.composer.enqueue(arg)
      ctx.transcript.sys(`queued: "${arg.slice(0, 50)}${arg.length > 50 ? '…' : ''}"`)
    }
  },

  {
    help: 'inject a forecast note after the next tool call (no interrupt)',
    name: 'steer',
    run: (arg, ctx) => {
      const payload = arg?.trim() ?? ''

      if (!payload) {
        return ctx.transcript.sys('usage: /steer <forecast note>')
      }

      // If the agent isn't running, fall back to the queue so the user's
      // forecast note isn't lost — identical semantics to the gateway handler.
      if (!ctx.ui.busy || !ctx.sid) {
        ctx.composer.enqueue(payload)
        ctx.transcript.sys(
          `no active turn — queued for next: "${payload.slice(0, 50)}${payload.length > 50 ? '…' : ''}"`
        )

        return
      }

      ctx.gateway
        .rpc<SessionSteerResponse>('session.steer', { session_id: ctx.sid, text: payload })
        .then(
          ctx.guarded<SessionSteerResponse>(r => {
            if (r?.status === 'queued') {
              ctx.transcript.sys(
                `steer queued — arrives after next tool call: "${payload.slice(0, 50)}${payload.length > 50 ? '…' : ''}"`
              )
            } else {
              ctx.transcript.sys('steer rejected')
            }
          })
        )
        .catch(ctx.guardedErr)
    }
  },

  {
    help: 'undo last forecast exchange',
    name: 'undo',
    run: (_arg, ctx) => {
      if (!ctx.sid) {
        return ctx.transcript.sys('nothing to undo')
      }

      ctx.gateway.rpc<SessionUndoResponse>('session.undo', { session_id: ctx.sid }).then(
        ctx.guarded<SessionUndoResponse>(r => {
          if ((r.removed ?? 0) > 0) {
            ctx.transcript.setHistoryItems((prev: Msg[]) => ctx.transcript.trimLastExchange(prev))
            ctx.transcript.sys(`undid ${r.removed} transcript entries`)
          } else {
            ctx.transcript.sys('nothing to undo')
          }
        })
      )
    }
  },

  {
    help: 'retry last forecast note',
    name: 'retry',
    run: (_arg, ctx) => {
      const last = ctx.local.getLastUserMsg()

      if (!last) {
        return ctx.transcript.sys('nothing to retry')
      }

      if (!ctx.sid) {
        return ctx.transcript.send(last)
      }

      ctx.gateway.rpc<SessionUndoResponse>('session.undo', { session_id: ctx.sid }).then(
        ctx.guarded<SessionUndoResponse>(r => {
          if ((r.removed ?? 0) <= 0) {
            return ctx.transcript.sys('nothing to retry')
          }

          ctx.transcript.setHistoryItems((prev: Msg[]) => ctx.transcript.trimLastExchange(prev))
          ctx.transcript.send(last)
        })
      )
    }
  }
]
