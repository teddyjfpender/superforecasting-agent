// ── protocol-generated wire shapes (single source of truth, Arc A4) ──────────
// SessionInfo / Usage / McpServerStatus / SlashCategory are GENERATED from the
// `protocol/` pydantic models. Imported here for local use (Msg.info,
// SlashCatalog.categories) AND re-exported so the whole app's historical
// `import { SessionInfo } from './types.js'` sites keep one stable import.
import type {
  McpServerStatus,
  SessionInfo,
  SlashCategory,
  Usage,
} from './protocol/generated.js'

export type { McpServerStatus, SessionInfo, SlashCategory, Usage }

// ── forecast-desk value enums (TS-only; the generated interfaces widen these to
// `string`, so the precise unions live here for consumers that switch on them).
export type ForecastTriageLabel =
  | 'irrelevant'
  | 'relevant_interesting'
  | 'relevant_uninteresting'

export type ForecastTailClassification =
  | 'edge_case'
  | 'live'
  | 'live_ish'
  | 'remote_tail'
  | 'residual'
  | 'unpriced'

export interface ActiveTool {
  context?: string
  id: string
  name: string
  startedAt?: number
}

export interface TodoItem {
  content: string
  id: string
  status: 'cancelled' | 'completed' | 'in_progress' | 'pending'
}

export interface ActivityItem {
  id: number
  text: string
  tone: 'error' | 'info' | 'warn'
}

export type SubagentStatus = 'completed' | 'error' | 'failed' | 'interrupted' | 'queued' | 'running' | 'timeout'

export interface SubagentProgress {
  apiCalls?: number
  costUsd?: number
  depth: number
  durationSeconds?: number
  filesRead?: string[]
  filesWritten?: string[]
  goal: string
  id: string
  index: number
  inputTokens?: number
  iteration?: number
  model?: string
  notes: string[]
  outputTail?: SubagentOutputEntry[]
  outputTokens?: number
  parentId: null | string
  reasoningTokens?: number
  startedAt?: number
  status: SubagentStatus
  summary?: string
  taskCount: number
  thinking: string[]
  toolCount: number
  tools: string[]
  toolsets?: string[]
}

export interface SubagentOutputEntry {
  isError: boolean
  preview: string
  tool: string
}

export interface SubagentNode {
  aggregate: SubagentAggregate
  children: SubagentNode[]
  item: SubagentProgress
}

export interface SubagentAggregate {
  activeCount: number
  costUsd: number
  descendantCount: number
  filesTouched: number
  hotness: number
  inputTokens: number
  maxDepthFromHere: number
  outputTokens: number
  totalDuration: number
  totalTools: number
}

export interface DelegationStatus {
  active: {
    depth?: number
    goal?: string
    model?: null | string
    parent_id?: null | string
    started_at?: number
    status?: string
    subagent_id?: string
    tool_count?: number
  }[]
  max_concurrent_children?: number
  max_spawn_depth?: number
  paused: boolean
}

export interface ApprovalReq {
  command: string
  description: string
}

export interface ConfirmReq {
  cancelLabel?: string
  confirmLabel?: string
  danger?: boolean
  detail?: string
  onConfirm: () => void
  title: string
}

export interface ClarifyReq {
  choices: string[] | null
  question: string
  requestId: string
}

export interface Msg {
  info?: SessionInfo
  kind?: 'diff' | 'intro' | 'panel' | 'session' | 'slash' | 'trail'
  panelData?: PanelData
  role: Role
  text: string
  thinking?: string
  thinkingTokens?: number
  toolTokens?: number
  tools?: string[]
  todos?: TodoItem[]
  todoIncomplete?: boolean
  todoCollapsedByDefault?: boolean
}

export type Role = 'assistant' | 'system' | 'tool' | 'user'
export type DetailsMode = 'hidden' | 'collapsed' | 'expanded'
export type ThinkingMode = 'collapsed' | 'truncated' | 'full'

// Per-section overrides for the agent details accordion.  Resolution order
// at lookup time is: explicit `display.sections.<name>` → built-in
// SECTION_DEFAULTS → global `details_mode`.  Today the built-in defaults
// expand `thinking`/`tools` and hide `activity`; `subagents` falls through
// to the global mode.  Any explicit value still wins for that one section.
export type SectionName = 'thinking' | 'tools' | 'subagents' | 'activity'
export type SectionVisibility = Partial<Record<SectionName, DetailsMode>>

export interface SudoReq {
  requestId: string
}

export interface SecretReq {
  envVar: string
  prompt: string
  requestId: string
}

export interface PanelData {
  sections: PanelSection[]
  title: string
}

export type PanelRow = [string, string] | [string, string, string]

export interface PanelSection {
  items?: string[]
  rows?: PanelRow[]
  text?: string
  title?: string
}

export interface SlashCatalog {
  canon: Record<string, string>
  categories: SlashCategory[]
  pairs: [string, string][]
  skillCount: number
  sub: Record<string, string[]>
}
