// The Market Models Presentation contract (mirrors forecasting/presentation.py).
// The gateway returns untyped JSON; `normalizePresentation` defensively coerces
// it into this shape (parity with asRpcResult's posture). The renderer dispatches
// per block `type` with a tolerant fallback, so unknown/extended types never
// crash the view.

export interface XYPoint {
  label?: string
  x: number
  y: number
}

export interface Band {
  lower: number[]
  p_hi: number
  p_lo: number
  upper: number[]
}

// Optional typed helpers for the @hermes/viz-rendered block types (DX only — the
// renderer reads from the loose PresentationBlock and never requires these).
export interface HeatmapBlock {
  colLabels?: string[]
  diverging?: boolean
  matrix: number[][]
  max?: number
  min?: number
  rowLabels?: string[]
  type: 'heatmap'
}

export interface FanBlock {
  bands?: { lower: number[]; p_hi?: number; p_lo?: number; upper: number[] }[]
  median: number[]
  paths?: number[][]
  type: 'fan'
  x?: number[]
}

// Blocks are intentionally loose: `type` is a string and fields are optional, so
// the renderer degrades gracefully on partial/extended payloads.
export interface PresentationBlock {
  [key: string]: unknown
  id?: string
  note?: string
  title?: string
  type: string
}

export interface Presentation {
  as_of_analysis?: null | string
  as_of_data?: null | string
  blocks: PresentationBlock[]
  diagnostics?: Record<string, unknown>
  model_id?: string
  question?: string
  schema_version?: string
  status?: string
  summary?: string
  title: string
  version?: number
}

export interface MarketModelListItem {
  current_version?: number
  depth?: string
  id: string
  // The latest presentation's build status (complete | partial | failed).
  last_status?: string
  question?: string
  status?: string
  tags?: string[]
  title: string
  updated_at?: string
}

const asString = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback)

/** Coerce a raw gateway value into a Presentation, or null if unusable. */
export const normalizePresentation = (raw: unknown): null | Presentation => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const obj = raw as Record<string, unknown>
  const rawBlocks = Array.isArray(obj.blocks) ? obj.blocks : []

  const blocks: PresentationBlock[] = rawBlocks
    .filter((b): b is Record<string, unknown> => Boolean(b) && typeof b === 'object' && typeof (b as Record<string, unknown>).type === 'string')
    .map((b, i) => ({ ...(b as PresentationBlock), id: asString((b as PresentationBlock).id, `block-${i}`) }))

  return {
    as_of_analysis: typeof obj.as_of_analysis === 'string' ? obj.as_of_analysis : null,
    as_of_data: typeof obj.as_of_data === 'string' ? obj.as_of_data : null,
    blocks,
    diagnostics: obj.diagnostics && typeof obj.diagnostics === 'object' ? (obj.diagnostics as Record<string, unknown>) : {},
    model_id: asString(obj.model_id),
    question: asString(obj.question),
    schema_version: asString(obj.schema_version),
    status: asString(obj.status, 'complete'),
    summary: asString(obj.summary),
    title: asString(obj.title, 'Untitled model'),
    version: typeof obj.version === 'number' ? obj.version : undefined
  }
}

/** Coerce a raw list payload into model list items. */
export const normalizeModelList = (raw: unknown): MarketModelListItem[] => {
  const rows = raw && typeof raw === 'object' && Array.isArray((raw as Record<string, unknown>).models)
    ? ((raw as Record<string, unknown>).models as unknown[])
    : Array.isArray(raw)
      ? (raw as unknown[])
      : []

  return rows
    .filter((m): m is Record<string, unknown> => Boolean(m) && typeof m === 'object' && typeof (m as Record<string, unknown>).id === 'string')
    .map(m => ({
      current_version: typeof m.current_version === 'number' ? m.current_version : 0,
      depth: asString(m.depth),
      id: asString(m.id),
      last_status: asString(m.last_status),
      question: asString(m.question),
      status: asString(m.status, 'active'),
      tags: Array.isArray(m.tags) ? (m.tags as string[]).filter(t => typeof t === 'string') : [],
      title: asString(m.title, 'Untitled model'),
      updated_at: asString(m.updated_at)
    }))
}
