import { useCallback, useEffect, useRef } from 'react'

import { asRpcResult } from '../lib/rpc.js'
import { WireEvent } from '../protocol/generated.js'

// The ONE detached-job attach hook (Arc B4). Every Desk background job — the A/T
// agent run and the U/mass-U deterministic refresh — is a TYPE on one runtime, so
// its lifecycle is one shape: discover the newest live job of the given types on
// mount (jobs.active), poll its record every ~5s (jobs.status), tighten that
// latency with the jobs.* progress/complete/error events, and clean up on unmount.
// The Desk's two near-identical poll+re-attach effects collapse onto this.
//
// The hook is a THIN lifecycle: the caller supplies `onProgress(record)` /
// `onComplete(record)` and maps the generic JobRecord into its own view state, so
// nothing here is job-type-specific.

// A partial JobRecord as jobs.status / jobs.active return it (record.to_dict). Only
// the envelope fields the loop reads are typed; the caller owns the rest.
export interface JobRecordShape {
  job_id?: string
  type?: string
  status?: string
  total?: null | number
  done_count?: number
  current?: unknown
  spec?: { question_id?: string; question_ids?: string[] } | null
  progress?: unknown[]
  result?: unknown
  error?: null | string
  annotations?: Record<string, unknown> | null
}

// The terminal states — a record in one of these fires onComplete and releases the
// attachment (the poll interval is torn down; the work stays done server-side).
const TERMINAL = new Set(['cancelled', 'done', 'error'])

// The jobs.* events whose arrival for OUR job triggers an immediate re-poll.
const JOB_EVENTS = new Set<string>([WireEvent.JOBS_COMPLETE, WireEvent.JOBS_ERROR, WireEvent.JOBS_PROGRESS])

export const JOB_POLL_MS = 5000

// The minimal gateway surface the loop needs: request(), plus the OPTIONAL
// EventEmitter on/off (the real GatewayClient has them; the Desk test fakes are
// plain { request } — the 5s poll alone drives them, the events are a bonus).
// `any[]` args intentionally mirror Node EventEmitter's on/off listener signature.
type EventListener = (...args: any[]) => void

export interface AttachGateway {
  request: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
  off?: (event: string, listener: EventListener) => unknown
  on?: (event: string, listener: EventListener) => unknown
}

export interface JobAttachCallbacks {
  onComplete?: (record: JobRecordShape) => void
  onProgress?: (record: JobRecordShape) => void
}

export interface JobAttachController {
  // Attach to a job the caller just STARTED (jobs.start / an alias returned its id).
  attach: (jobId: string) => void
  // Tear down: stop the interval, unsubscribe the event bridge, guard late resolves.
  stop: () => void
}

// Imperative, renderer-free core (mirrors pollAgentsActive) so the whole lifecycle
// — mount discovery, poll, event refresh, cleanup — is unit-testable without a
// React tree. Returns a controller: attach() points it at a started job; stop()
// tears it down.
export function attachJobLoop(
  gw: AttachGateway,
  types: string[],
  cbs: JobAttachCallbacks,
  intervalMs: number = JOB_POLL_MS
): JobAttachController {
  let cancelled = false
  let jobId: null | string = null
  let timer: null | ReturnType<typeof setInterval> = null

  const clearTimer = () => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  // A record reached a terminal state (or the run vanished): stop polling and
  // release the attachment so a fresh job can be attached later.
  const release = () => {
    jobId = null
    clearTimer()
  }

  const pollOnce = () => {
    const id = jobId

    if (cancelled || !id) {
      return
    }

    gw.request<unknown>('jobs.status', { job_id: id })
      .then(raw => {
        // Guard a late resolve after stop() OR after we moved off this job.
        if (cancelled || jobId !== id) {
          return
        }

        const envelope = asRpcResult<{ found?: boolean; job?: JobRecordShape }>(raw)
        const rec = envelope?.job

        if (!rec) {
          return
        }

        if (TERMINAL.has(String(rec.status))) {
          release()
          cbs.onComplete?.(rec)

          return
        }

        cbs.onProgress?.(rec)
      })
      .catch(() => {})
  }

  const startPolling = () => {
    clearTimer()
    pollOnce()
    timer = setInterval(pollOnce, intervalMs)
  }

  const attach = (id: string) => {
    if (cancelled || !id) {
      return
    }

    jobId = id
    startPolling()
  }

  // Mount discovery: the newest live job of `types` (jobs.active returns newest
  // first). An explicit attach() that already fired wins the race (jobId set), so
  // discovery never clobbers a just-started job.
  gw.request<unknown>('jobs.active', types.length ? { types } : {})
    .then(raw => {
      if (cancelled || jobId) {
        return
      }

      const r = asRpcResult<{ jobs?: JobRecordShape[] }>(raw)
      const live = r?.jobs?.[0]

      if (!live?.job_id) {
        return
      }

      jobId = live.job_id
      // Paint the first frame off the discovered active record (targetIds, current,
      // done) before the poll refines it.
      cbs.onProgress?.(live)
      startPolling()
    })
    .catch(() => {})

  // Event-driven refresh: a jobs.progress/complete/error for OUR job re-polls at
  // once (the 5s interval is the floor). Uses the proven gw.on('event') channel —
  // the same one createGatewayEventHandler consumes — so it needs no per-type
  // typed-emit bridge; guarded for the plain { request } test fakes.
  const onEvent: EventListener = (ev?: { payload?: { job_id?: string }; type?: string }) => {
    if (cancelled || !jobId || !ev || !ev.type || !JOB_EVENTS.has(ev.type)) {
      return
    }

    const evJob = ev.payload?.job_id

    if (evJob && evJob !== jobId) {
      return
    }

    pollOnce()
  }

  gw.on?.('event', onEvent)

  return {
    attach,
    stop: () => {
      cancelled = true
      clearTimer()
      gw.off?.('event', onEvent)
    }
  }
}

// React wrapper: run one attach loop per (gw, types) while mounted, torn down on
// unmount. Callbacks are read through a ref so an inline closure never re-arms the
// loop (the effect keys only on gw + the types identity). Returns attach() for the
// caller to point the loop at a job it just started.
export function useJobAttach(
  gw: AttachGateway,
  types: string[],
  cbs: JobAttachCallbacks
): { attach: (jobId: string) => void } {
  const cbsRef = useRef(cbs)
  cbsRef.current = cbs
  const controllerRef = useRef<JobAttachController | null>(null)
  const typesKey = types.join(',')

  useEffect(() => {
    const controller = attachJobLoop(gw, typesKey ? typesKey.split(',') : [], {
      onComplete: r => cbsRef.current.onComplete?.(r),
      onProgress: r => cbsRef.current.onProgress?.(r)
    })

    controllerRef.current = controller

    return () => {
      controller.stop()
      controllerRef.current = null
    }
  }, [gw, typesKey])

  const attach = useCallback((jobId: string) => {
    controllerRef.current?.attach(jobId)
  }, [])

  return { attach }
}
