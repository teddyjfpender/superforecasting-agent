import { Box, Text, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'
import unicodeSpinners from 'unicode-animations'

import { artWidth, FORECAST_HERO_WIDTH, forecastHero, logo, LOGO_WIDTH } from '../banner.js'
import { flat } from '../lib/text.js'
import type { Theme } from '../theme.js'
import type { PanelRow, PanelSection, SessionInfo } from '../types.js'

const LOADER_TICK_MS = 120
const PANEL_COMMAND_PLACEHOLDER_RE = /(?:<[^>]+>|\[[^\]]+\]|\.\.\.|;)/
const PANEL_DRAFT_PREFIX = 'draft:'
type PanelClickEvent = { cellIsBlank?: boolean; stopPropagation?: () => void }

export function panelCommandTarget(candidate?: null | string): string | null {
  const command = (candidate ?? '').trim()

  if (!command.startsWith('/') || PANEL_COMMAND_PLACEHOLDER_RE.test(command)) {
    return null
  }

  return command
}

export function panelDraftTarget(candidate?: null | string): string | null {
  const value = candidate ?? ''
  const draftStart = value.trimStart()

  if (!draftStart.startsWith(PANEL_DRAFT_PREFIX)) {
    return null
  }

  const draft = draftStart.slice(PANEL_DRAFT_PREFIX.length)

  return draft.startsWith('/') ? draft : null
}

const rowTarget = (row: PanelRow): string => row[2] ?? row[0]

const runPanelCommand = (
  command: string | null,
  onCommandClick?: (command: string) => void,
  event?: PanelClickEvent
) => {
  if (!command || event?.cellIsBlank) {
    return
  }

  event?.stopPropagation?.()
  onCommandClick?.(command)
}

const runPanelDraft = (
  draft: string | null,
  onCommandDraft?: (command: string) => void,
  event?: PanelClickEvent
) => {
  if (!draft || event?.cellIsBlank) {
    return
  }

  event?.stopPropagation?.()
  onCommandDraft?.(draft)
}

function InlineLoader({ label, t }: { label: string; t: Theme }) {
  const [tick, setTick] = useState(0)
  const spinner = unicodeSpinners.braille
  const frame = spinner.frames[tick % spinner.frames.length] ?? '⠋'

  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), Math.max(LOADER_TICK_MS, spinner.interval))

    return () => clearInterval(id)
  }, [spinner.interval])

  return (
    <Text color={t.color.muted} wrap="truncate">
      <Text color={t.color.accent}>{frame}</Text> {label}
    </Text>
  )
}

export function ArtLines({ lines }: { lines: [string, string][] }) {
  return (
    <>
      {lines.map(([c, text], i) => (
        <Text color={c} key={i} wrap="truncate">
          {text}
        </Text>
      ))}
    </>
  )
}

export function Banner({ t }: { t: Theme }) {
  const cols = useStdout().stdout?.columns ?? 80
  const logoLines = logo(t.color, t.bannerLogo || undefined)

  return (
    <Box flexDirection="column" marginBottom={1}>
      {cols >= (t.bannerLogo ? artWidth(logoLines) : LOGO_WIDTH) ? (
        <ArtLines lines={logoLines} />
      ) : (
        <Text bold color={t.color.primary}>
          {t.brand.icon} FORECAST DESK
        </Text>
      )}

      <Box>
        <Text bold color={t.color.accent}>
          {t.brand.icon} Superforecasting Agent
        </Text>
        <Text color={t.color.muted}> · forecast ledger online</Text>
      </Box>

      <Box marginTop={1}>
        <Text color={t.color.muted}>start  </Text>
        <Text color={t.color.primary}>/forecast</Text>
        <Text color={t.color.muted}> desk · </Text>
        <Text color={t.color.primary}>/forecast-rerun {'<name>'}</Text>
        <Text color={t.color.muted}> re-run · </Text>
        <Text color={t.color.primary}>/help</Text>
        <Text color={t.color.muted}> all commands</Text>
      </Box>
    </Box>
  )
}

// ── Collapsible helpers ──────────────────────────────────────────────

function CollapseToggle({
  count,
  open,
  suffix,
  t,
  title,
  onToggle
}: {
  count?: number
  open: boolean
  suffix?: string
  t: Theme
  title: string
  onToggle: () => void
}) {
  return (
    <Box onClick={onToggle}>
      <Text color={t.color.accent}>{open ? '▾ ' : '▸ '}</Text>
      <Text bold color={t.color.accent}>
        {title}
      </Text>
      {typeof count === 'number' ? (
        <Text color={t.color.muted}> ({count})</Text>
      ) : null}
      {suffix ? (
        <Text color={t.color.muted}> {suffix}</Text>
      ) : null}
    </Box>
  )
}

// ── SessionPanel ─────────────────────────────────────────────────────

const SKILLS_MAX = 8
const TOOLSETS_MAX = 8

export function SessionPanel({ info, sid, t }: SessionPanelProps) {
  const cols = useStdout().stdout?.columns ?? 100
  const heroLines = forecastHero(t.color, t.bannerHero || undefined)
  const heroW = artWidth(heroLines) || FORECAST_HERO_WIDTH
  const leftW = heroW + 4
  const wide = cols >= 90 && leftW + 40 < cols
  // Reserve the round border (2), paddingX (4), the hero column's marginRight
  // (3) and a little breathing room so the right panel can never be sized into
  // the hero column.
  const w = Math.max(20, wide ? cols - leftW - 15 : cols - 12)
  const lineBudget = Math.max(12, w - 2)
  const strip = (s: string) => (s.endsWith('_tools') ? s.slice(0, -6) : s)

  // ── Local collapse state for each section ──
  const [toolsOpen, setToolsOpen] = useState(true)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [systemOpen, setSystemOpen] = useState(false)
  const [mcpOpen, setMcpOpen] = useState(false)

  const truncLine = (pfx: string, items: string[]) => {
    let line = ''
    let shown = 0

    for (const item of [...items].sort()) {
      const next = line ? `${line}, ${item}` : item

      if (pfx.length + next.length > lineBudget) {
        return line ? `${line}, …+${items.length - shown}` : `${item}, …`
      }

      line = next
      shown++
    }

    return line
  }

  // ── Collapsible skills section ──
  const skillEntries = Object.entries(info.skills).sort()
  const skillsTotal = flat(info.skills).length
  const skillsCatCount = skillEntries.length

  const skillsBody = () => {
    if (info.lazy && skillEntries.length === 0) {
      return <InlineLoader label="scanning skills" t={t} />
    }

    const shown = skillEntries.slice(0, SKILLS_MAX)
    const overflow = skillEntries.length - SKILLS_MAX

    return (
      <>
        {shown.map(([k, vs]) => (
          <Text key={k} wrap="truncate">
            <Text color={t.color.muted}>{strip(k)}: </Text>
            <Text color={t.color.text}>{truncLine(strip(k) + ': ', vs)}</Text>
          </Text>
        ))}
        {overflow > 0 && (
          <Text color={t.color.muted}>(and {overflow} more categories…)</Text>
        )}
      </>
    )
  }

  // ── Collapsible tools section ──
  const toolEntries = Object.entries(info.tools).sort()
  const toolsTotal = flat(info.tools).length

  const toolsBody = () => {
    const shown = toolEntries.slice(0, TOOLSETS_MAX)
    const overflow = toolEntries.length - TOOLSETS_MAX

    return (
      <>
        {shown.map(([k, vs]) => (
          <Text key={k} wrap="truncate">
            <Text color={t.color.muted}>{strip(k)}: </Text>
            <Text color={t.color.text}>{truncLine(strip(k) + ': ', vs)}</Text>
          </Text>
        ))}
        {overflow > 0 && (
          <Text color={t.color.muted}>(and {overflow} more toolsets…)</Text>
        )}
      </>
    )
  }

  // ── Collapsible MCP section ──
  const mcpBody = () => (
    <>
      {(info.mcp_servers ?? []).map(s => (
        <Text key={s.name} wrap="truncate">
          <Text color={t.color.muted}>{`  ${s.name} `}</Text>
          <Text color={t.color.muted}>{`[${s.transport}]`}</Text>
          <Text color={t.color.muted}>: </Text>
          {s.connected ? (
            <Text color={t.color.text}>
              {s.tools} tool{s.tools === 1 ? '' : 's'}
            </Text>
          ) : (
            <Text color={t.color.error}>failed</Text>
          )}
        </Text>
      ))}
    </>
  )

  // ── System prompt body ──
  const sysPromptLen = (info.system_prompt ?? '').length

  const systemBody = () => {
    if (sysPromptLen === 0) {
      return <Text color={t.color.muted}>No system prompt loaded.</Text>
    }

    return (
      <Text color={t.color.muted}>
        {info.system_prompt}
      </Text>
    )
  }

  return (
    // width="100%" constrains the box to the transcript column (which is
    // narrower than the terminal once the scrollbar + forecast rail take their
    // columns). Without it the box sized to leftW + w (computed from the FULL
    // terminal width) and overflowed past the right edge — clipping the border
    // and the Available Tools list. The right column already has flexShrink +
    // overflow="hidden", so a constrained parent is all it needs to give way.
    <Box
      borderColor={t.color.border}
      borderStyle="round"
      flexShrink={1}
      marginBottom={1}
      paddingX={2}
      paddingY={1}
      width="100%"
    >
      {wide && (
        // flexShrink={0} pins the hero column at its full width. Without it, a
        // re-render triggered by toggling a collapsible (Available Tools/Skills)
        // let Yoga shrink this column, so the right panel slid left and painted
        // over the hero table. The right panel absorbs any width pressure
        // instead (flexShrink + overflow=hidden below).
        <Box flexDirection="column" flexShrink={0} marginRight={3} width={leftW}>
          <ArtLines lines={heroLines} />
          <Text />

          <Text color={t.color.accent}>
            {info.model.split('/').pop()}
            <Text color={t.color.muted}> · Superforecasting Agent</Text>
          </Text>

          <Text color={t.color.muted} wrap="truncate-end">
            {info.cwd || process.cwd()}
          </Text>

          {sid && (
            <Text>
              <Text color={t.color.sessionLabel}>Session: </Text>
              <Text color={t.color.sessionBorder}>{sid}</Text>
            </Text>
          )}
        </Box>
      )}

      <Box flexDirection="column" flexShrink={1} minWidth={0} overflow="hidden" width={w}>
        <Box justifyContent="center" marginBottom={1}>
          <Text bold color={t.color.primary}>
            {t.brand.name}
            {info.version ? ` v${info.version}` : ''}
            {info.release_date ? ` (${info.release_date})` : ''}
          </Text>
        </Box>

        {/* ── Tools (expanded by default) ── */}
        <Box flexDirection="column" marginTop={1}>
          <CollapseToggle
            onToggle={() => setToolsOpen(v => !v)}
            open={toolsOpen}
            t={t}
            title="Available Tools"
          />
          {toolsOpen && toolsBody()}
        </Box>

        {/* ── Skills (collapsed by default) ── */}
        <Box flexDirection="column" marginTop={1}>
          <CollapseToggle
            count={skillsTotal}
            onToggle={() => setSkillsOpen(v => !v)}
            open={skillsOpen}
            suffix={skillsCatCount > 0 ? `in ${skillsCatCount} categor${skillsCatCount === 1 ? 'y' : 'ies'}` : undefined}
            t={t}
            title="Available Skills"
          />
          {skillsOpen && skillsBody()}
        </Box>

        {/* ── System Prompt (collapsed by default) ── */}
        {sysPromptLen > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <CollapseToggle
              onToggle={() => setSystemOpen(v => !v)}
              open={systemOpen}
              suffix={`— ${sysPromptLen.toLocaleString()} chars`}
              t={t}
              title="System Prompt"
            />
            {systemOpen && systemBody()}
          </Box>
        )}

        {/* ── MCP Servers (collapsed by default) ── */}
        {info.mcp_servers && info.mcp_servers.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <CollapseToggle
              count={info.mcp_servers.length}
              onToggle={() => setMcpOpen(v => !v)}
              open={mcpOpen}
              suffix="connected"
              t={t}
              title="MCP Servers"
            />
            {mcpOpen && mcpBody()}
          </Box>
        )}

        <Text />

        <Text color={t.color.text}>
          {toolsTotal} tools{' · '}
          {skillsTotal} skills
          {info.mcp_servers?.length ? ` · ${info.mcp_servers.length} MCP` : ''}
          {' · '}
          <Text color={t.color.muted}>/help for commands</Text>
        </Text>

        {typeof info.update_behind === 'number' && info.update_behind > 0 && (
          <Text bold color={t.color.warn}>
            ! {info.update_behind} {info.update_behind === 1 ? 'commit' : 'commits'} behind
            <Text bold={false} color={t.color.warn} dimColor>
              {' '}
              - run{' '}
            </Text>
            <Text bold color={t.color.warn}>
              {info.update_command || 'superforecasting-agent update'}
            </Text>
            <Text bold={false} color={t.color.warn} dimColor>
              {' '}
              to update
            </Text>
          </Text>
        )}
      </Box>
    </Box>
  )
}

export function Panel({ onCommandClick, onCommandDraft, sections, t, title }: PanelProps) {
  return (
    // width="100%" constrains the box to the transcript column so long values
    // wrap at the visible edge instead of growing the box past the terminal
    // (which cropped the right border + cut every line). flexShrink lets it
    // give way rather than overflow when space is tight.
    <Box
      borderColor={t.color.border}
      borderStyle="round"
      flexDirection="column"
      flexShrink={1}
      paddingX={2}
      paddingY={1}
      width="100%"
    >
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color={t.color.primary}>
          {title}
        </Text>
      </Box>

      {sections.map((sec, si) => (
        <Box flexDirection="column" key={si} marginTop={si > 0 ? 1 : 0}>
          {sec.title && (
            <Text bold color={t.color.accent}>
              {sec.title}
            </Text>
          )}

          {sec.rows?.map((row, ri) => {
            const [k, v] = row
            const target = rowTarget(row)
            const command = panelCommandTarget(target)
            const draft = panelDraftTarget(target)
            const actionable = command || draft

            return (
              <Box
                key={ri}
                onClick={
                  command
                    ? (event: PanelClickEvent) => runPanelCommand(command, onCommandClick, event)
                    : draft
                      ? (event: PanelClickEvent) => runPanelDraft(draft, onCommandDraft, event)
                    : undefined
                }
              >
                {/* Two-column row: a fixed 20-wide key column + a flexible value
                    column, so long values wrap as a HANGING-INDENT paragraph
                    (continuation lines align under the value, not back at col 0).
                    A leading "› " marks rows you can click. */}
                <Box flexDirection="row">
                  <Box flexShrink={0} width={20}>
                    <Text color={actionable ? t.color.accent : t.color.muted}>{actionable ? '› ' : '  '}</Text>
                    <Text color={actionable ? t.color.accent : t.color.muted}>{k.padEnd(18)}</Text>
                  </Box>
                  {v ? (
                    <Box flexGrow={1}>
                      <Text color={t.color.text} wrap="wrap">
                        {v}
                      </Text>
                    </Box>
                  ) : null}
                </Box>
              </Box>
            )
          })}

          {sec.items?.map((item, ii) => {
            const command = panelCommandTarget(item)

            return (
              <Box
                key={ii}
                onClick={
                  command
                    ? (event: PanelClickEvent) => runPanelCommand(command, onCommandClick, event)
                    : undefined
                }
              >
                <Box flexDirection="row">
                  <Box flexShrink={0} width={2}>
                    <Text color={command ? t.color.accent : t.color.muted}>{command ? '› ' : '  '}</Text>
                  </Box>
                  <Box flexGrow={1}>
                    <Text color={command ? t.color.accent : t.color.text} wrap="wrap">
                      {item}
                    </Text>
                  </Box>
                </Box>
              </Box>
            )
          })}

          {sec.text && <Text color={t.color.muted}>{sec.text}</Text>}
        </Box>
      ))}
    </Box>
  )
}

interface PanelProps {
  onCommandClick?: (command: string) => void
  onCommandDraft?: (command: string) => void
  sections: PanelSection[]
  t: Theme
  title: string
}

interface SessionPanelProps {
  info: SessionInfo
  sid?: string | null
  t: Theme
}
