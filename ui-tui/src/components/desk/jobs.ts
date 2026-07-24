import type { JobRecordShape } from '../../app/useJobAttach.js'
import type { ForecastReforecastResultRow, ForecastReforecastStatusResponse } from '../../protocol/generated.js'
import { truncate } from '../forecastsWorkspace.js'

// ── Mass forced re-run ("run en masse") ──────────────────────────────────────
// The operator can mark a set of rows (Space toggles, Shift+↑/↓ extends) and fan
// the REAL update / re-arm over every one. Each outcome is classified HONESTLY so
// the completion summary never claims success for a row that had nothing to do.
export type MassOutcome = 'error' | 'noSources' | 'refreshed' | 'unchanged'
export type MassTally = Record<MassOutcome, number>

// Read the honest tally the REFRESH job computed server-side into the desk's
// MassTally shape. The per-question status classification (committed → refreshed,
// no_change → unchanged, no_watched_sources → no_sources, exception → error) now
// lives in `forecasting/jobs/types/refresh.py::classify_refresh_status` — the desk
// renders the tally the job produced instead of classifying each response itself
// (the old client-side classifyRefresh moved server-side). None-safe: a missing or
// malformed tally reads as all zeros so a summary never invents counts.
export const refreshTally = (result: unknown): MassTally => {
  const t = (result as { tally?: Record<string, unknown> } | null | undefined)?.tally ?? {}
  const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

  return {
    error: n(t.error),
    noSources: n(t.no_sources),
    refreshed: n(t.refreshed),
    unchanged: n(t.unchanged)
  }
}

// The honest completion summaries — "✓ 7 updated · 3 unchanged · 7 no sources".
// The updated count is always shown (even 0, so a run that refreshed nothing says
// so); the rest only when non-zero.
export const summarizeUpdate = (t: MassTally): string => {
  const parts = [`${t.refreshed} updated`]

  if (t.unchanged) {
    parts.push(`${t.unchanged} unchanged`)
  }

  if (t.noSources) {
    parts.push(`${t.noSources} no sources`)
  }

  if (t.error) {
    parts.push(`${t.error} failed`)
  }

  return `✓ ${parts.join(' · ')}`
}

export const summarizeRearm = (t: MassTally): string => {
  const parts = [`${t.refreshed} re-armed`]

  if (t.error) {
    parts.push(`${t.error} failed`)
  }

  return `✓ ${parts.join(' · ')}`
}

// ── Detached Desk agent job (A agent-run / T task) ───────────────────────────
// A single detached background job — the FULL formal reforecast flow (A) or a
// free-text task session (T) over an explicit batch — polled by run_id every ~5s.
// `targetIds` is the fixed set the job was launched over; `doneIds` accrues from
// the status `results[]`, so the remaining set (targetIds − doneIds) is the rows
// that still show the in-flight ⋯ gutter marker.
export interface AgentJob {
  runId: string
  mode: 'agent' | 'task'
  total: number
  done: number
  status: string
  current: { question_id?: string; stage?: string; title?: string } | null
  // Task mode: the latest progress[] note (the running commentary of the single
  // agent session). Agent mode drives the line from `current` instead.
  note?: string
  targetIds: Set<string>
  doneIds: Set<string>
}

// ── Detached Desk REFRESH job (U / mass-U "Update now") ──────────────────────
// The deterministic mass re-pool, now ONE durable job on the shared runtime (Arc
// B) instead of a client-side loop in component state. It survives navigating away
// from the Desk: the mount re-attach (jobs.active {types:['refresh']}) rediscovers a
// live job and resumes the ⋯ markers + spinner exactly where the job is. `current`
// is the in-flight question id (a JobRecord.current string, not the agent's nested
// object); `doneIds` accrues from the job record's annotated partial results so a
// finished row drops its ⋯ marker mid-run.
export interface RefreshJob {
  jobId: string
  total: number
  done: number
  status: string
  current: null | string
  targetIds: Set<string>
  doneIds: Set<string>
}

// The registered job TYPES each attach hook discovers. The A/T agent run enqueues
// as `reforecast` (bare `A`) or `task` (`T`); `U`/mass-`U` enqueue as `refresh`.
export const AGENT_JOB_TYPES = ['reforecast', 'task']
export const REFRESH_JOB_TYPES = ['refresh']

// Map a generic JobRecord (jobs.status / jobs.active) into the Desk's AgentJob view
// state — the A/T poll/re-attach mapping, now off the runtime's own record instead
// of the forecast.reforecast.* legacy projection. `current` is the per-question
// pointer object the reforecast type annotates; `doneIds` accrues from the record's
// annotated partial results; task-mode `note` is the latest progress detail.
export const agentJobFromRecord = (rec: JobRecordShape): AgentJob => {
  const spec = rec.spec ?? {}

  const ann = (rec.annotations ?? {}) as {
    current?: { question_id?: string; stage?: string; title?: string } | null
    progress?: { detail?: string }[]
    results?: { question_id?: string }[]
  }

  const results = ann.results ?? (rec.result as { results?: { question_id?: string }[] } | null)?.results ?? []
  const doneIds = new Set(results.map(row => row.question_id).filter(Boolean) as string[])
  const progress = ann.progress ?? []
  const lastNote = progress.length ? progress[progress.length - 1]?.detail : undefined

  return {
    current: ann.current ?? null,
    done: rec.done_count ?? results.length,
    doneIds,
    mode: rec.type === 'task' ? 'task' : 'agent',
    note: typeof lastNote === 'string' ? lastNote : undefined,
    runId: rec.job_id ?? '',
    status: rec.status ?? 'running',
    targetIds: new Set((spec.question_ids ?? []).map(String)),
    total: rec.total ?? spec.question_ids?.length ?? 0
  }
}

// Map a generic JobRecord into the Desk's RefreshJob view state — the U/mass-U
// deterministic re-pool. `current` is the in-flight question id (a plain string on
// the record); `doneIds` accrues from the record's annotated partial results.
export const refreshJobFromRecord = (rec: JobRecordShape): RefreshJob => {
  const spec = rec.spec ?? {}
  const targetIds = new Set<string>((spec.question_ids ?? []).map(String))
  const partial = (rec.annotations?.results as { question_id?: string }[] | undefined) ?? []
  const doneIds = new Set<string>(partial.map(x => x.question_id).filter(Boolean) as string[])

  return {
    current: typeof rec.current === 'string' ? rec.current : null,
    done: rec.done_count ?? doneIds.size,
    doneIds,
    jobId: rec.job_id ?? '',
    status: rec.status ?? 'running',
    targetIds,
    total: rec.total ?? targetIds.size
  }
}

// Project a TERMINAL JobRecord onto the ForecastReforecastStatusResponse shape
// summarizeAgentJob reads — the per-question `results` + `task_summary` the type's
// execute() returns (with the running annotations as the fallback), so the honest
// completion toast is built off the record the runtime persisted. `quorums_started`
// is left unset so the summary derives it from the results' quorum_autorun rows.
export const reforecastStatusFromRecord = (rec: JobRecordShape): ForecastReforecastStatusResponse => {
  const ann = (rec.annotations ?? {}) as { results?: ForecastReforecastResultRow[]; task_summary?: string }
  const result = (rec.result ?? {}) as { results?: ForecastReforecastResultRow[]; task_summary?: string }

  return {
    error: rec.error ?? null,
    results: result.results ?? ann.results ?? [],
    run_id: rec.job_id,
    status: (rec.status as ForecastReforecastStatusResponse['status']) ?? 'done',
    task_summary: result.task_summary ?? ann.task_summary
  }
}

// The HONEST completion toast for a detached job. Agent mode reports the gated
// outcome split parsed from results[] — committed (the commit landed), blocked
// (ran but the gate/saturation refused the commit), errors, and quorums started —
// so a run never claims a commit it didn't earn. Task mode leads with the agent's
// own task_summary (falling back to the same split when it withheld one).
export const summarizeAgentJob = (r: ForecastReforecastStatusResponse, mode: 'agent' | 'task'): string => {
  const results = r.results ?? []
  const committed = results.filter(x => x.committed).length
  const errors = results.filter(x => x.error).length
  const blocked = results.filter(x => !x.committed && !x.error).length
  const quorums = r.quorums_started ?? results.filter(x => x.quorum_autorun).length
  const parts = [`${committed} committed`]

  if (blocked) {
    parts.push(`${blocked} blocked`)
  }

  if (errors) {
    parts.push(`${errors} errors`)
  }

  if (quorums) {
    parts.push(`${quorums} quorum${quorums === 1 ? '' : 's'} started`)
  }

  const tally = `✓ ${parts.join(' · ')}`

  if (mode === 'task') {
    const summary = (r.task_summary ?? '').trim()

    return summary ? `✓ ${truncate(summary, 96)}` : tally
  }

  return tally
}
