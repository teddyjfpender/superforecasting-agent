import { Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useInput, useStdout } from '@hermes/ink'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { patchOverlayState } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import type {
  ForecastDashboardResponse,
  ForecastDashboardReview,
  ForecastTriageContestedResponse,
  ForecastTriageContestedRow,
  ForecastTriageLabel,
  ForecastTriageRelabelResponse,
  ForecastWarningGroup,
  ForecastWarningsAggregateResponse,
  ForecastWarningsAutomodeComplete,
  ForecastWarningsAutomodeError,
  ForecastWarningsAutomodeProgress,
  ForecastWarningsAutomodeRunResponse,
  ForecastWarningsDismissResponse
} from '../gatewayTypes.js'
import { getOverlayCache, setOverlayCache } from '../lib/overlayCache.js'
import { asRpcResult } from '../lib/rpc.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { OverlayScrollbar } from './agentsOverlay.js'

export const openAlertsView = () => patchOverlayState({ alerts: true })
export const closeAlertsView = () => patchOverlayState({ alerts: false })

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// ── Aggregate tier model ────────────────────────────────────────────────────
// The aggregate RPC folds the whole open backlog into three action tiers (free /
// agent / manual) plus the agent-tier `stale` sub-bucket. We surface all four as
// sibling TIER nodes in the tree; `stale` is a VIEW over the agent tier (its
// reasons are also counted in agent.total), kept visible so an operator can see
// how much of the reforecast backlog is "just getting old".
type TierKey = 'agent' | 'free' | 'manual' | 'stale'

interface TierNode {
  // One-word operator affordance: who/what has to act (auto / needs-agent / manual).
  affordance: string
  key: TierKey
  label: string
  reasons: ForecastWarningGroup[]
  // A sub-view tier (STALE) folds a SUBSET of another tier's reasons — its kinds are
  // NOT its own, so a header dismiss must narrow by its specific reasons, never by
  // kind (dismissing by kind would silence the whole parent tier).
  subView: boolean
  total: number
}

// The flattened, currently-visible node list the cursor walks: a tier header,
// then (when the tier is expanded) each of its reason-group rows, then — at the
// tail — the CONTESTED triage rows awaiting an operator hand-label (their own
// cursor space, so j/k walks straight from the backlog tree into them).
type FlatNode =
  | { kind: 'contested'; row: ForecastTriageContestedRow; rowKey: string }
  | { kind: 'reason'; group: ForecastWarningGroup; rowKey: string; tierKey: TierKey }
  | { kind: 'tier'; rowKey: string; tier: TierNode }

// The contested-triage hand-label loop. Each auto-labeler call the
// contested-routing subsystem disputed (near the decision boundary, or a
// verifier disagreed) is adjudicated with a single keystroke: 1/2/3 assign the
// three-way relevance label, which routes through forecast.triage.relabel (the
// SAME relabel_route the CLI + agent use — it records the expert label AND acks
// the linked contested_label alert through real work, never a bare ack).
const CONTESTED_LABELS: Record<string, ForecastTriageLabel> = {
  '1': 'relevant_interesting',
  '2': 'relevant_uninteresting',
  '3': 'irrelevant'
}

const LABEL_SHORT: Record<ForecastTriageLabel, string> = {
  irrelevant: 'irrelevant',
  relevant_interesting: 'interesting',
  relevant_uninteresting: 'uninteresting'
}

const buildTiers = (agg: ForecastWarningsAggregateResponse | null): TierNode[] => {
  const free = agg?.free
  const agent = agg?.agent
  const manual = agg?.manual
  const stale = agent?.stale

  return [
    { affordance: 'auto', key: 'free', label: 'FREE', reasons: free?.reasons ?? [], subView: false, total: free?.total ?? 0 },
    { affordance: 'needs-agent', key: 'agent', label: 'AGENT', reasons: agent?.reasons ?? [], subView: false, total: agent?.total ?? 0 },
    { affordance: 'manual', key: 'manual', label: 'MANUAL', reasons: manual?.reasons ?? [], subView: false, total: manual?.total ?? 0 },
    // STALE is a VIEW over the AGENT tier (its reforecast reasons are a subset).
    { affordance: 'needs-agent', key: 'stale', label: 'STALE', reasons: stale?.reasons ?? [], subView: true, total: stale?.total ?? 0 }
  ]
}

// Flatten the tiers into the visible cursor list, skipping the reason rows of any
// collapsed tier (so the cursor never lands on a hidden node).
const flattenTiers = (tiers: TierNode[], collapsed: Set<TierKey>): FlatNode[] => {
  const flat: FlatNode[] = []

  for (const tier of tiers) {
    flat.push({ kind: 'tier', rowKey: `tier:${tier.key}`, tier })

    if (!collapsed.has(tier.key)) {
      tier.reasons.forEach((group, idx) => {
        flat.push({ group, kind: 'reason', rowKey: `reason:${tier.key}:${idx}`, tierKey: tier.key })
      })
    }
  }

  return flat
}

const tierColor = (t: Theme, key: TierKey): string => {
  if (key === 'free') {
    return t.color.ok
  }

  if (key === 'manual') {
    return t.color.error
  }

  return t.color.warn
}

// One open-line text-capture target for the dismiss modal: the selection params
// the dismiss RPC will receive (a single reason for a reason row, the distinct
// kinds of a normal tier header, or the specific reasons folded by a sub-view tier
// like STALE) plus a human label for the prompt.
interface DismissTarget {
  label: string
  params: { kind?: string[]; reason?: string | string[] }
}

interface AutomodeState {
  done: number
  id: string
  phase: string
  reason?: string
  total: number
}

interface AlertsViewProps {
  gw: GatewayClient
  // Deep-link hint: when 'contested', park the cursor on the first contested
  // triage row once it loads (the Today feed's contested badge routes here).
  initialFocus?: 'contested'
  onClose: () => void
  sessionId?: string
  t: Theme
}

export function AlertsView({ gw, initialFocus, onClose, sessionId = '', t }: AlertsViewProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const termRows = stdout?.rows ?? 24
  const sem = semantics(t)

  const [data, setData] = useState<ForecastDashboardResponse | null>(
    () => getOverlayCache<ForecastDashboardResponse>('forecast.dashboard:alerts') ?? null
  )
  const [aggregate, setAggregate] = useState<ForecastWarningsAggregateResponse | null>(
    () => getOverlayCache<ForecastWarningsAggregateResponse>('forecast.warnings.aggregate:alerts') ?? null
  )
  const [contested, setContested] = useState<ForecastTriageContestedRow[]>(
    () => getOverlayCache<ForecastTriageContestedRow[]>('forecast.triage.contested:alerts') ?? []
  )

  const [loading, setLoading] = useState(!aggregate)
  const [error, setError] = useState<null | string>(null)
  const [flash, setFlash] = useState('')
  const [now, setNow] = useState(0)
  const [sel, setSel] = useState(0)
  // Collapse state lives over tier KEYS; a collapsed tier's reason rows are hidden
  // from the flattened cursor list (so the cursor never lands on a hidden node).
  const [collapsed, setCollapsed] = useState<Set<TierKey>>(() => new Set())
  const [automode, setAutomode] = useState<AutomodeState | null>(null)
  // When set, the dismiss modal owns ALL keyboard input: keystrokes accumulate
  // into noteBuffer until ⏎ confirms (rejecting an empty note) or Esc cancels.
  const [dismissTarget, setDismissTarget] = useState<DismissTarget | null>(null)
  const [noteBuffer, setNoteBuffer] = useState('')
  const scrollRef = useRef<null | ScrollBoxHandle>(null)
  // Mirror the live automode job id into a ref so the (stable) gateway-event
  // handlers can filter their own job's events without re-subscribing.
  const automodeIdRef = useRef<null | string>(null)
  // The contested deep-link (initialFocus) parks the cursor on the first
  // contested row exactly ONCE, the first time it loads — after that the
  // operator owns the cursor (labeling a row must not yank it back).
  const focusAppliedRef = useRef(false)

  const load = (announce = false) => {
    setLoading(!aggregate)
    // The tier tree comes from forecast.warnings.aggregate (the WHOLE backlog,
    // untruncated); the dashboard is still loaded for the review-queue / readiness
    // / stale-assumption sections kept below (out of scope to fold into the tree).
    Promise.all([
      gw.request<unknown>('forecast.warnings.aggregate', {}),
      // fast: skip the full-build cost (backtests, live/pilot reports, stale-review
      // walk) — at 120q/1250 alerts the full build measured ~1s vs ~0.2s fast. This
      // view only reads review_queue + stale-{assumption,ref} counts (all carried in
      // fast mode); evidence_status.gaps is full-only, so the "Readiness gaps"
      // section below simply doesn't render under fast (it degrades to empty).
      gw.request<unknown>('forecast.dashboard', { fast: true, limit: 50 }),
      // The contested list is supplementary — a failure here must NOT nuke the
      // whole warnings view, so it resolves to null rather than rejecting the all.
      gw.request<unknown>('forecast.triage.contested', { limit: 200 }).catch(() => null)
    ])
      .then(([aggRaw, dashRaw, contestedRaw]) => {
        const agg = asRpcResult<ForecastWarningsAggregateResponse>(aggRaw)
        const dash = asRpcResult<ForecastDashboardResponse>(dashRaw)
        const contestedRes = asRpcResult<ForecastTriageContestedResponse>(contestedRaw)

        if (!agg && !dash) {
          setError('forecast.warnings.aggregate returned no data')
          setLoading(false)

          return
        }

        if (agg) {
          setOverlayCache('forecast.warnings.aggregate:alerts', agg)
          setAggregate(agg)
        }

        if (dash) {
          setOverlayCache('forecast.dashboard:alerts', dash)
          setData(dash)
        }

        if (contestedRes) {
          const rows = contestedRes.contested ?? []
          setOverlayCache('forecast.triage.contested:alerts', rows)
          setContested(rows)
        }

        setError(null)
        setLoading(false)

        if (announce) {
          setFlash('refreshed')
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  useEffect(() => {
    scrollRef.current?.scrollTo(0)
  }, [aggregate])

  useEffect(() => {
    const id = setInterval(() => setNow(value => value + 1), 500)

    return () => clearInterval(id)
  }, [])

  const summary = data?.summary
  const reviews: ForecastDashboardReview[] = summary?.review_queue ?? []
  const gaps = summary?.evidence_status?.gaps ?? []
  const staleAssumptions = summary?.stale_assumption_count ?? 0
  const staleRefs = summary?.stale_reference_class_count ?? 0

  const headline = aggregate?.headline
  const openTotal = headline?.total ?? 0

  // The 4 tier nodes + the flattened, currently-visible cursor list (tier headers
  // plus the reason rows of any EXPANDED tier), with the contested triage rows
  // appended at the tail so one cursor walks the whole surface.
  const tiers = useMemo(() => buildTiers(aggregate), [aggregate])
  const tierFlat = useMemo(() => flattenTiers(tiers, collapsed), [tiers, collapsed])
  const contestedNodes = useMemo<FlatNode[]>(
    () => contested.map((row, idx) => ({ kind: 'contested', row, rowKey: `contested:${row.id ?? idx}` })),
    [contested]
  )
  const flat = useMemo(() => [...tierFlat, ...contestedNodes], [tierFlat, contestedNodes])

  // Render off a derived clamp so a shrunk list never indexes past the end (the
  // desk-fix pattern). We ALSO pull the stored `sel` back into range whenever the
  // flat list shrinks (below): keeping the raw index valid is what makes navigation
  // move relative to the VISIBLE position, so one keypress is always one move.
  const clampedSel = Math.min(sel, Math.max(0, flat.length - 1))
  const selectedNode = flat[clampedSel] ?? null
  const selectedKey =
    selectedNode && selectedNode.kind !== 'contested'
      ? selectedNode.kind === 'tier'
        ? selectedNode.tier.key
        : selectedNode.tierKey
      : null

  // Re-clamp the stored cursor when collapse/expand changes the visible node count
  // so a stale past-the-end `sel` can never leave a keypress visibly stuck (the
  // first press would otherwise just pull the index back into range without moving).
  useEffect(() => {
    setSel(i => Math.min(Math.max(0, i), Math.max(0, flat.length - 1)))
  }, [flat.length])

  // Honour the contested deep-link once the rows are in: jump to the first
  // contested node (which sits right after the backlog tree).
  useEffect(() => {
    if (initialFocus === 'contested' && !focusAppliedRef.current && contestedNodes.length > 0) {
      focusAppliedRef.current = true
      setSel(tierFlat.length)
    }
  }, [initialFocus, contestedNodes.length, tierFlat.length])

  // Best-effort follow: keep the selected row roughly centred as the cursor moves
  // over the flattened tree (each node renders as ~2 rows; +1 for the headline).
  useEffect(() => {
    const pageSize = Math.max(4, termRows - 10)
    const rowsBefore = 1 + clampedSel * 2
    scrollRef.current?.scrollTo(Math.max(0, rowsBefore - Math.floor(pageSize / 2)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clampedSel])

  // ── Automode lifecycle (streamed gateway events) ──────────────────────────
  useEffect(() => {
    const onProgress = (p: ForecastWarningsAutomodeProgress) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      setAutomode(prev =>
        prev
          ? { ...prev, done: p.done ?? prev.done, total: p.total ?? prev.total, phase: p.phase ?? prev.phase, reason: p.reason ?? prev.reason }
          : prev
      )
    }

    const onComplete = (p: ForecastWarningsAutomodeComplete) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      automodeIdRef.current = null
      setAutomode(null)
      setFlash(
        `automode ${p.cancelled ? 'cancelled' : 'done'} — ${p.processed ?? 0}/${p.total ?? 0} processed`
      )
      load()
    }

    const onError = (p: ForecastWarningsAutomodeError) => {
      if (!p || p.job_id !== automodeIdRef.current) {
        return
      }

      automodeIdRef.current = null
      setAutomode(null)
      setFlash(`automode error: ${p.message ?? 'failed'}`)
    }

    gw.on('forecast.warnings.automode.progress', onProgress)
    gw.on('forecast.warnings.automode.complete', onComplete)
    gw.on('forecast.warnings.automode.error', onError)

    return () => {
      gw.off?.('forecast.warnings.automode.progress', onProgress)
      gw.off?.('forecast.warnings.automode.complete', onComplete)
      gw.off?.('forecast.warnings.automode.error', onError)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gw])

  // Spawn one bulk automode pass scoped by `extra` (a `tier` and/or `reason`); the
  // streamed progress/complete/error events drive the shared heartbeat line. A pass
  // never starts while one is live (the caller decides whether that means cancel).
  const startAutomode = (extra: Record<string, unknown>, label: string) => {
    if (automode) {
      // A pass is already live. Shift-A routes to cancel before reaching here; any
      // other trigger (R) flashes rather than silently no-op'ing, for symmetry.
      setFlash('a pass is already running')

      return
    }

    setFlash(`${label} starting…`)
    gw.request<unknown>('forecast.warnings.automode.run', { session_id: sessionId, ...extra })
      .then(raw => {
        const res = asRpcResult<ForecastWarningsAutomodeRunResponse>(raw)

        if (!res?.job_id) {
          setFlash(`${label} failed to start`)

          return
        }

        automodeIdRef.current = res.job_id
        setAutomode({ done: 0, id: res.job_id, phase: 'start', total: 0 })
      })
      .catch((err: unknown) => {
        setFlash(`${label} error: ${err instanceof Error ? err.message : String(err)}`)
      })
  }

  const cancelAutomode = () => {
    if (!automode) {
      return
    }

    setFlash('cancelling automode…')
    gw.request('forecast.warnings.automode.cancel', { job_id: automode.id }).catch(() => undefined)
  }

  // The focused reason row (if the cursor is on one) can narrow a bulk pass to a
  // single reason group — but ONLY when that row lives under the pressed action's
  // OWN tier. A reason carries the tier of its parent runner, so narrowing R (FREE)
  // to a reforecast reason — or Shift-A (AGENT) to a free reason — would emit a
  // contradictory {tier, reason} pair; in that cross-tier case we run the whole tier.
  const focusedReasonRow = selectedNode?.kind === 'reason' ? selectedNode : null

  // R — the FREE (non-LLM, gated) pass; Shift-A — the AGENT (reforecast/LLM) pass.
  // Each always carries its backend tier name (the tier picks the runner); the reason
  // only narrows when the focused row belongs to that same tier.
  const runFreePass = () => {
    const reason = focusedReasonRow?.tierKey === 'free' ? focusedReasonRow.group.reason : undefined
    startAutomode(reason ? { reason, tier: 'free' } : { tier: 'free' }, 'free pass')
  }

  // STALE is a view over the AGENT tier, so a stale reason row narrows the agent pass too.
  const runAgentPass = () => {
    const onAgentRow = focusedReasonRow?.tierKey === 'agent' || focusedReasonRow?.tierKey === 'stale'
    const reason = onAgentRow ? focusedReasonRow?.group.reason : undefined
    startAutomode(reason ? { reason, tier: 'reforecast' } : { tier: 'reforecast' }, 'agent pass')
  }

  // Shift-A is the agent pass; while a pass is live it doubles as the cancel.
  const agentPassOrCancel = () => (automode ? cancelAutomode() : runAgentPass())

  // 1/2/3 on a focused contested row — record the operator's three-way relevance
  // label. Optimistically drop the row (immediate-apply with a flash), fire the
  // relabel_route RPC, then reload so the count settles (a failure re-surfaces the
  // row on the reload, since the backend still holds it as contested).
  const relabelContested = (label: ForecastTriageLabel) => {
    if (selectedNode?.kind !== 'contested') {
      return
    }

    const labelId = selectedNode.row.id

    if (!labelId) {
      setFlash('no label id to relabel')

      return
    }

    setContested(prev => prev.filter(row => row.id !== labelId))
    setFlash(`labeled ${LABEL_SHORT[label]} — alert closed`)
    gw.request<unknown>('forecast.triage.relabel', { label, label_id: labelId })
      .then(raw => {
        const res = asRpcResult<ForecastTriageRelabelResponse>(raw)

        if (res?.success === false) {
          setFlash('relabel failed')
        }

        load()
      })
      .catch((err: unknown) => {
        setFlash(`relabel error: ${err instanceof Error ? err.message : String(err)}`)
        load()
      })
  }

  // x — open the dismiss modal for the focused group: a reason row dismisses that
  // exact reason; a tier header dismisses the distinct kinds it folds (so we never
  // re-derive the tier→kind map client-side — we read it off the aggregate).
  const openDismiss = () => {
    if (!selectedNode || selectedNode.kind === 'contested') {
      return
    }

    if (selectedNode.kind === 'reason') {
      const reason = selectedNode.group.reason

      if (!reason) {
        setFlash('no reason to dismiss')

        return
      }

      setDismissTarget({ label: reason, params: { reason } })
    } else if (selectedNode.tier.subView) {
      // A sub-view tier (STALE) folds a SUBSET of its parent's reasons and does NOT
      // own its kinds — dismiss by the exact reasons it shows so we silence only
      // those, never the whole parent (reforecast) tier.
      const reasons = [...new Set(selectedNode.tier.reasons.map(g => g.reason).filter((r): r is string => !!r))]

      if (!reasons.length) {
        setFlash('nothing to dismiss')

        return
      }

      setDismissTarget({ label: selectedNode.tier.label, params: { reason: reasons } })
    } else {
      const kinds = [...new Set(selectedNode.tier.reasons.map(g => g.kind).filter((k): k is string => !!k))]

      if (!kinds.length) {
        setFlash('nothing to dismiss')

        return
      }

      setDismissTarget({ label: selectedNode.tier.label, params: { kind: kinds } })
    }

    setNoteBuffer('')
  }

  const closeDismiss = () => {
    setDismissTarget(null)
    setNoteBuffer('')
  }

  // Confirm the dismiss: a non-empty note is REQUIRED (the backend rejects empty
  // notes too — we guard here so a stray ⏎ never fires a no-op RPC). actor=tui.
  const submitDismiss = () => {
    const note = noteBuffer.trim()

    if (!note) {
      setFlash('a note is required to dismiss')

      return
    }

    const target = dismissTarget

    if (!target) {
      return
    }

    closeDismiss()
    setFlash('dismissing…')
    gw.request<unknown>('forecast.warnings.dismiss', { ...target.params, actor: 'tui', note })
      .then(raw => {
        const res = asRpcResult<ForecastWarningsDismissResponse>(raw)
        setFlash(`dismissed ${res?.count ?? 0}/${res?.matched ?? 0} — ${truncate(target.label, 24)}`)
        load()
      })
      .catch((err: unknown) => {
        setFlash(`dismiss error: ${err instanceof Error ? err.message : String(err)}`)
      })
  }

  // Tab / ] / [ — jump the cursor to the next / previous TIER header (wrapping).
  const jumpTier = (dir: -1 | 1) => {
    const tierIdxs = flat.map((n, i) => (n.kind === 'tier' ? i : -1)).filter(i => i >= 0)

    if (!tierIdxs.length) {
      return
    }

    if (dir === 1) {
      const next = tierIdxs.find(i => i > clampedSel)
      setSel(next ?? tierIdxs[0])
    } else {
      const prevs = tierIdxs.filter(i => i < clampedSel)
      setSel(prevs.length ? prevs[prevs.length - 1] : tierIdxs[tierIdxs.length - 1])
    }
  }

  const collapseAll = () => setCollapsed(new Set(tiers.map(tier => tier.key)))
  const expandAll = () => setCollapsed(new Set())

  const setCollapse = (key: TierKey, value: boolean) => {
    setCollapsed(prev => {
      if (prev.has(key) === value) {
        return prev
      }

      const next = new Set(prev)

      if (value) {
        next.add(key)
      } else {
        next.delete(key)
      }

      return next
    })
  }

  // Enter / Space on a node toggles its OWNING tier's collapse state (a reason row
  // folds its parent away); the cursor then re-clamps via the derived clamp.
  const toggleSelected = () => {
    if (!selectedKey) {
      return
    }

    setCollapse(selectedKey, !collapsed.has(selectedKey))
  }

  // Move the cursor by `delta` VISIBLE nodes. We clamp the current index into range
  // INSIDE the functional update before applying the delta, so a move is always
  // relative to where the cursor is actually drawn (clampedSel) — never to a stale
  // past-the-end `sel`. That guarantees one keypress is one visible move under any
  // collapse state.
  const move = (delta: number) =>
    setSel(i => {
      const max = Math.max(0, flat.length - 1)
      const cur = Math.min(Math.max(0, i), max)

      return Math.min(max, Math.max(0, cur + delta))
    })

  const pageSize = Math.max(4, termRows - 10)

  useInput((ch, key) => {
    // ── Dismiss modal: it owns ALL input while open (the sheet-open guard). ──
    if (dismissTarget) {
      if (key.escape) {
        return closeDismiss()
      }

      if (key.return) {
        return submitDismiss()
      }

      if (key.backspace || key.delete) {
        return setNoteBuffer(buf => buf.slice(0, -1))
      }

      // Accumulate printable input (spaces allowed; a multi-char paste lands as one
      // `ch`, so strip control bytes rather than gating on length === 1).
      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ' && c !== '\x7f').join('')

        if (printable) {
          return setNoteBuffer(buf => buf + printable)
        }
      }

      return
    }

    if (ch === 'q' || key.escape) {
      return onClose()
    }

    if (ch === '?') {
      return patchOverlayState({ cheatSheet: true })
    }

    // Bulk passes on the focused tier/reason. Shift-A = AGENT (reforecast) pass /
    // cancel-while-running; R = FREE (non-LLM gated) pass.
    if (ch === 'A') {
      return agentPassOrCancel()
    }

    if (ch === 'R') {
      return runFreePass()
    }

    // x — dismiss (silence) the focused group behind a required one-line note.
    if (ch === 'x') {
      return openDismiss()
    }

    // 1/2/3 — assign the three-way relevance label to the focused contested row
    // (interesting / uninteresting / irrelevant). No-op unless the cursor is on a
    // contested node, so the digits never steal input over the backlog tree.
    if ((ch === '1' || ch === '2' || ch === '3') && selectedNode?.kind === 'contested') {
      return relabelContested(CONTESTED_LABELS[ch])
    }

    if (ch === 'r') {
      return load(true)
    }

    // Collapse-all / expand-all the whole tree.
    if (ch === 'c') {
      return collapseAll()
    }

    if (ch === 'e') {
      return expandAll()
    }

    // Tab / ] / [ — jump to the next / previous tier header.
    if (key.tab || ch === ']') {
      return jumpTier(1)
    }

    if (ch === '[') {
      return jumpTier(-1)
    }

    // Selection over the flattened tier/reason node list. Move relative to the
    // VISIBLE position (one keypress = one move) even after a collapse shrank the list.
    if (key.upArrow || ch === 'k') {
      return move(-1)
    }

    if (key.downArrow || ch === 'j') {
      return move(1)
    }

    // Tree collapse/expand. Enter/Space toggles; ←/h collapses (and homes the
    // cursor on the tier header), →/l expands.
    if (key.return || ch === ' ') {
      return toggleSelected()
    }

    if (key.leftArrow || ch === 'h') {
      if (selectedKey) {
        setCollapse(selectedKey, true)

        if (selectedNode?.kind === 'reason') {
          const headerIdx = flat.findIndex(n => n.kind === 'tier' && n.tier.key === selectedKey)

          if (headerIdx >= 0) {
            setSel(headerIdx)
          }
        }
      }

      return
    }

    if (key.rightArrow || ch === 'l') {
      if (selectedKey) {
        setCollapse(selectedKey, false)
      }

      return
    }

    // Scrolling (the page is taller than the cursor's tree section).
    if (key.wheelUp) {
      return scrollRef.current?.scrollBy(-2)
    }

    if (key.wheelDown) {
      return scrollRef.current?.scrollBy(2)
    }

    if (key.pageUp || (key.ctrl && ch === 'u')) {
      return scrollRef.current?.scrollBy(-pageSize)
    }

    if (key.pageDown || (key.ctrl && ch === 'd')) {
      return scrollRef.current?.scrollBy(pageSize)
    }

    if (ch === 'g') {
      return scrollRef.current?.scrollTo(0)
    }

    if (ch === 'G') {
      return scrollRef.current?.scrollToBottom?.()
    }
  })

  const width = Math.max(40, cols - 4)

  const nothing =
    !loading &&
    !error &&
    openTotal === 0 &&
    reviews.length === 0 &&
    gaps.length === 0 &&
    staleAssumptions === 0 &&
    staleRefs === 0 &&
    contested.length === 0

  // Headline summary line: the whole open backlog folded into action tiers.
  const headlineLine = (
    <Text wrap="truncate-end">
      <Text bold color={openTotal ? t.color.text : t.color.muted}>{openTotal}</Text>
      <Text color={t.color.muted}> open · </Text>
      <Text color={headline?.free ? t.color.ok : t.color.muted}>{headline?.free ?? 0}</Text>
      <Text color={t.color.muted}> free · </Text>
      <Text color={headline?.agent ? t.color.warn : t.color.muted}>{headline?.agent ?? 0}</Text>
      <Text color={t.color.muted}> agent · </Text>
      <Text color={headline?.manual ? t.color.error : t.color.muted}>{headline?.manual ?? 0}</Text>
      <Text color={t.color.muted}> manual</Text>
    </Text>
  )

  let body

  if (loading && !aggregate) {
    body = <Text color={t.color.muted}>Loading warnings…</Text>
  } else if (error) {
    body = (
      <Box flexDirection="column">
        <Text color={t.color.error}>Failed to load warnings: {error}</Text>
        <Text color={t.color.muted}>Press r to retry · q to close</Text>
      </Box>
    )
  } else if (nothing) {
    body = (
      <Text color={t.color.ok} wrap="wrap">
        All clear — no open alerts, nothing queued for review, no stale assumptions or evidence gaps.
      </Text>
    )
  } else {
    body = (
      <Box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
        <ScrollBox decstbm={false} flexDirection="column" flexGrow={1} flexShrink={1} ref={scrollRef}>
          <Box flexDirection="column" paddingBottom={3} paddingRight={1}>
            {headlineLine}

            <Section t={t} title="Backlog">
              {tierFlat.map((node, i) => {
                const active = i === clampedSel

                if (node.kind === 'contested') {
                  return null
                }

                if (node.kind === 'tier') {
                  const tier = node.tier
                  const isCollapsed = collapsed.has(tier.key)

                  return (
                    <Text
                      backgroundColor={active ? t.color.selectionBg : undefined}
                      key={node.rowKey}
                      wrap="truncate-end"
                    >
                      <Text color={active ? sem.cursor : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                      <Text color={t.color.muted}>{`${isCollapsed ? '▸' : '▾'} `}</Text>
                      <Text bold color={tierColor(t, tier.key)}>{tier.label}</Text>
                      <Text bold color={tier.total ? t.color.text : t.color.muted}>{`  ${tier.total}`}</Text>
                      <Text color={t.color.muted}>{`  ${tier.affordance}`}</Text>
                    </Text>
                  )
                }

                const g = node.group
                const allRefs = g.scope_refs ?? []
                const refs = allRefs.slice(0, 5)
                // The row count is the full untruncated group size; the refs are only
                // a preview, so flag how many scope_refs aren't shown ("+N more").
                const moreRefs = Math.max(0, (g.count ?? refs.length) - refs.length)

                return (
                  <Box flexDirection="column" key={node.rowKey}>
                    <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                      <Text color={active ? sem.cursor : t.color.border}>{active ? '  ▸ ' : '    '}</Text>
                      <Text bold color={t.color.warn}>{`${g.count ?? 0}×`}</Text>
                      <Text color={t.color.text}>{`  ${truncate(g.reason ?? '—', 30)}`}</Text>
                      {g.recommended_action ? (
                        <Text color={t.color.muted}>{`  → ${truncate(g.recommended_action, 40)}`}</Text>
                      ) : null}
                    </Text>
                    {refs.length ? (
                      <Text color={t.color.border} wrap="truncate-end">
                        {`        ${refs.map(r => truncate(r, 18)).join(' · ')}${moreRefs > 0 ? `  +${moreRefs} more` : ''}`}
                      </Text>
                    ) : null}
                  </Box>
                )
              })}
            </Section>

            {contested.length > 0 ? (
              <Section t={t} title={`Contested — hand-label (${contested.length})`}>
                {contestedNodes.map((node, j) => {
                  if (node.kind !== 'contested') {
                    return null
                  }

                  // Contested nodes sit at the tail of the flat list, right after
                  // the backlog tree — so their global cursor index is offset by it.
                  const i = tierFlat.length + j
                  const active = i === clampedSel
                  const row = node.row
                  const head = row.title || row.candidate_ref || row.id || '—'

                  return (
                    <Box flexDirection="column" key={node.rowKey}>
                      <Text backgroundColor={active ? t.color.selectionBg : undefined} wrap="truncate-end">
                        <Text color={active ? sem.cursor : t.color.muted}>{active ? '▸ ' : '  '}</Text>
                        <Text bold color={t.color.text}>{truncate(head, 40)}</Text>
                        {row.auto_label ? (
                          <Text color={t.color.warn}>{`  auto:${truncate(row.auto_label, 24)}`}</Text>
                        ) : null}
                        {row.question_id ? (
                          <Text color={t.color.muted}>{`  ${truncate(row.question_id, 18)}`}</Text>
                        ) : null}
                      </Text>
                      {row.rationale ? (
                        <Text color={t.color.border} wrap="truncate-end">{`    ${truncate(row.rationale, Math.max(20, width - 6))}`}</Text>
                      ) : null}
                    </Box>
                  )
                })}
              </Section>
            ) : null}

            {reviews.length > 0 ? (
              <Section t={t} title={`Review queue (${reviews.length})`}>
                {reviews.map((r, i) => (
                  <Box flexDirection="column" key={r.id ?? i} marginBottom={1}>
                    <Text wrap="truncate-end">
                      <Text bold color={t.color.warn}>{`P${r.priority ?? '-'}`}</Text>
                      <Text color={t.color.text}>{`  ${truncate(r.title || r.id || '—', width - 8)}`}</Text>
                    </Text>
                    {r.reasons?.length ? (
                      <Text color={t.color.muted} wrap="wrap">{`  ${r.reasons.join(', ')}`}</Text>
                    ) : null}
                    {r.next_action ? (
                      <Text color={t.color.label} wrap="truncate-end">{`  → ${truncate(r.next_action, width - 6)}`}</Text>
                    ) : null}
                  </Box>
                ))}
              </Section>
            ) : null}

            {staleAssumptions > 0 || staleRefs > 0 ? (
              <Section t={t} title="Stale">
                {staleAssumptions > 0 ? (
                  <Text color={t.color.warn}>{`  ${staleAssumptions} stale assumption${staleAssumptions === 1 ? '' : 's'}`}</Text>
                ) : null}
                {staleRefs > 0 ? (
                  <Text color={t.color.warn}>{`  ${staleRefs} stale reference class${staleRefs === 1 ? '' : 'es'}`}</Text>
                ) : null}
              </Section>
            ) : null}

            {gaps.length > 0 ? (
              <Section t={t} title="Readiness gaps">
                {gaps.map((g, i) => (
                  <Text color={t.color.warn} key={i} wrap="wrap">{`  ${g.replace(/_/g, ' ')}`}</Text>
                ))}
              </Section>
            ) : null}
          </Box>
        </ScrollBox>
        <NoSelect flexShrink={0} marginLeft={1}>
          <OverlayScrollbar scrollRef={scrollRef} t={t} tick={now} />
        </NoSelect>
      </Box>
    )
  }

  const header = (
    <Box flexShrink={0} marginBottom={1}>
      <Text wrap="truncate-end">
        <Text bold color={t.color.primary}>
          WARNINGS
        </Text>
        <Text color={t.color.muted}>{'   '}</Text>
        <Text color={openTotal ? t.color.error : t.color.muted}>{openTotal}</Text>
        <Text color={t.color.muted}> open · </Text>
        <Text color={headline?.free ? t.color.accent : t.color.muted}>{headline?.free ?? 0}</Text>
        <Text color={t.color.muted}> auto-clearable · </Text>
        <Text color={reviews.length ? t.color.warn : t.color.muted}>{reviews.length}</Text>
        <Text color={t.color.muted}> to review · </Text>
        <Text color={contested.length ? t.color.warn : t.color.muted}>{contested.length}</Text>
        <Text color={t.color.muted}> contested</Text>
      </Text>
    </Box>
  )

  // Live automode heartbeat line (done/total + current alert reason + cancel hint).
  const automodeLine = automode ? (
    <Text color={t.color.accent} wrap="truncate-end">
      {`◇ automode ${automode.phase} ${automode.done}/${automode.total || '…'}${automode.reason ? ` · ${truncate(automode.reason, 28)}` : ''} · Shift-A cancel`}
    </Text>
  ) : null

  // Dismiss modal: a one-line note capture. While open it owns the keyboard and
  // replaces the keymap hint; ⏎ confirms (rejecting an empty note), Esc cancels.
  const dismissModal = dismissTarget ? (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      <Text color={t.color.warn} wrap="truncate-end">
        {`Dismiss ${truncate(dismissTarget.label, 32)} — record a one-line reason (re-surfaces after its TTL)`}
      </Text>
      <Text wrap="truncate-end">
        <Text color={t.color.muted}>note: </Text>
        <Text color={t.color.text}>{noteBuffer}</Text>
        <Text color={t.color.accent}>▏</Text>
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">⏎ confirm · Esc cancel</Text>
    </Box>
  ) : null

  // On a contested row the footer swaps to the hand-label mapping (1/2/3) so the
  // relevance verbs are always in view while adjudicating.
  const onContested = selectedNode?.kind === 'contested'
  const footer = (
    <Box flexDirection="column" flexShrink={0} marginTop={1}>
      {automodeLine}
      {flash ? <Text color={t.color.accent}>{flash}</Text> : null}
      {dismissModal ??
        (onContested ? (
          <Text color={t.color.muted} wrap="truncate-end">
            1 interesting · 2 uninteresting · 3 irrelevant · ↑↓/jk move · r refresh · q close
          </Text>
        ) : (
          <Text color={t.color.muted} wrap="truncate-end">
            ↑↓/jk move · ⏎/space expand · Tab/][ tier · c/e fold-all · R free · Shift-A agent · x dismiss · r refresh · q close
          </Text>
        ))}
    </Box>
  )

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      {header}
      {body}
      {footer}
    </Box>
  )
}

function Section({ children, t, title }: { children: ReactNode; t: Theme; title: string }) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color={t.color.accent}>
        {title}
      </Text>
      {children}
    </Box>
  )
}
