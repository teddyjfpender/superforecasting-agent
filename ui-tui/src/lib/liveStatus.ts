import type { TurnState } from '../app/turnStore.js'
import type { Usage } from '../types.js'

import { estimateTokensRough } from './text.js'

// ── Running-status grammar ────────────────────────────────────────────────────
// The pure, honest core of the live status line: what verb describes what the
// turn is ACTUALLY doing, how many tokens it has spent, and how to abbreviate a
// count. Kept apart from the React component so each rule is unit-testable and
// the component stays a thin projection of the turn/usage state onto one row.

type ActivitySignal = Pick<
  TurnState,
  'reasoningActive' | 'reasoningStreaming' | 'streaming' | 'subagents' | 'tools'
>

// Map a live tool name to the gerund the operator reads as "what it's doing now".
// Unknown tools fall back to "Running" — a tool IS running, we just don't have a
// more specific verb, which is honest.
function toolVerb(name: string | undefined): string {
  const n = (name ?? '').toLowerCase()

  if (/search|web|exa|brave|google|tavily|serp|browse|lookup/.test(n)) {
    return 'Searching'
  }

  if (/read|cat|open|fetch|view|grep|find|glob|\bls\b|list|get_/.test(n)) {
    return 'Reading'
  }

  if (/write|edit|apply|create|patch|update|save|append/.test(n)) {
    return 'Writing'
  }

  return 'Running'
}

// The gerund adjective for the running status line, derived STRICTLY from live
// turn state so it never claims an activity that isn't happening. Precedence is
// "most concrete current action first": a running tool, then streamed prose,
// then reasoning, then a fanned-out panel of agents, else a plain wait.
export function activityAdjective(turn: ActivitySignal): string {
  if (turn.tools.length > 0) {
    return toolVerb(turn.tools[0]?.name)
  }

  if (turn.streaming) {
    return 'Writing'
  }

  if (turn.reasoningActive || turn.reasoningStreaming) {
    return 'Reasoning'
  }

  if (turn.subagents.some(s => s.status === 'running' || s.status === 'queued')) {
    return 'Deliberating'
  }

  return 'Working'
}

// Abbreviate a token count: <1000 verbatim, then k / M to one decimal place.
//   999 → "999" · 1000 → "1.0k" · 999949 → "999.9k" · 1_000_000 → "1.0M"
export function abbrevTokens(n: number): string {
  const v = Math.max(0, Math.floor(n))

  if (v < 1000) {
    return String(v)
  }

  if (v < 1_000_000) {
    return `${(v / 1000).toFixed(1)}k`
  }

  return `${(v / 1_000_000).toFixed(1)}M`
}

// Cumulative tokens for the CURRENT turn. Two honest signals, whichever is larger
// (so the counter never regresses and always reflects live progress):
//   • reported — the authoritative session `usage.total` delta since turn start
//     (lands on message-complete / session-info events);
//   • live — the in-flight rough estimate the turn store already tracks
//     (reasoning + tool output + streamed prose), which ticks up during the turn.
export function turnTokenCount(
  turn: Pick<TurnState, 'reasoningTokens' | 'streaming' | 'toolTokens'>,
  usage: Pick<Usage, 'total'>,
  baseTotal: number
): number {
  const reported = Math.max(0, (usage.total ?? 0) - baseTotal)

  const live =
    (turn.reasoningTokens ?? 0) + (turn.toolTokens ?? 0) + estimateTokensRough(turn.streaming ?? '')

  return Math.max(reported, live)
}
