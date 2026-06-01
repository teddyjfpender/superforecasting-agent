import { AlternateScreen, Box, NoSelect, ScrollBox, Text } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { Fragment, memo, useMemo, useRef } from 'react'

import { forecastDeskActionStripItems, forecastDeskCompactItems, forecastDeskPrimaryActionItem } from '../app/forecastPanel.js'
import { useGateway } from '../app/gatewayContext.js'
import type { AppLayoutProps } from '../app/interfaces.js'
import { $isBlocked, $overlayState, patchOverlayState } from '../app/overlayStore.js'
import { $uiState } from '../app/uiStore.js'
import { INLINE_MODE, SHOW_FPS } from '../config/env.js'
import { PLACEHOLDER } from '../content/placeholders.js'
import {
  FORECAST_TUI_FIND_SHORTCUT,
  FORECAST_TUI_VIEW_SHORTCUTS,
  forecastShortcutDisplayHotkey
} from '../lib/forecastShortcuts.js'
import {
  COMPOSER_PROMPT_GAP_WIDTH,
  composerPromptWidth,
  inputVisualHeight,
  stableComposerColumns
} from '../lib/inputMetrics.js'
import { PerfPane } from '../lib/perfPane.js'
import { composerPromptText } from '../lib/prompt.js'
import type { PanelSection } from '../types.js'

import { AgentsOverlay } from './agentsOverlay.js'
import { ForecastPulse, StatusRule, StickyPromptTracker, TranscriptScrollbar } from './appChrome.js'
import { ForecastsWorkspace } from './forecastsWorkspace.js'
import { FloatingOverlays, PromptZone } from './appOverlays.js'
import { Banner, Panel, panelCommandTarget, panelDraftTarget, SessionPanel } from './branding.js'
import { FpsOverlay } from './fpsOverlay.js'
import { HelpHint } from './helpHint.js'
import { MessageLine } from './messageLine.js'
import { QueuedMessages } from './queuedMessages.js'
import { LiveTodoPanel, StreamingAssistant } from './streamingAssistant.js'
import { TextInput, type TextInputMouseApi } from './textInput.js'

const FORECAST_RAIL_MIN_COLS = 132
// Rail only renders at >= FORECAST_RAIL_MIN_COLS, so a wider rail still leaves
// ~76 cols for the transcript. Widened from 44 -> 56 to cut the heavy value
// truncation (value budget is FORECAST_RAIL_WIDTH - 19, so 25 -> 37 chars).
const FORECAST_RAIL_WIDTH = 56
type CommandClickEvent = {
  cellIsBlank?: boolean
  stopPropagation?: () => void
}

const truncateRail = (value: string, max: number) =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

const runTargetFromClick = (
  target: string | null | undefined,
  draftCommand: (command: string) => void,
  runCommand: (command: string) => void,
  event?: CommandClickEvent
) => {
  const command = panelCommandTarget(target)
  const draft = panelDraftTarget(target)

  if ((!command && !draft) || event?.cellIsBlank) {
    return
  }

  event?.stopPropagation?.()
  if (command) {
    runCommand(command)
  } else if (draft) {
    draftCommand(draft)
  }
}

const PromptPrefix = memo(function PromptPrefix({
  bold = false,
  color,
  promptText,
  width
}: {
  bold?: boolean
  color: string
  promptText: string
  width: number
}) {
  const glyphWidth = Math.max(1, width - COMPOSER_PROMPT_GAP_WIDTH)

  return (
    <Box width={width}>
      <Box width={glyphWidth}>
        <Text bold={bold} color={color}>
          {promptText}
        </Text>
      </Box>
      <Box width={COMPOSER_PROMPT_GAP_WIDTH} />
    </Box>
  )
})

const TranscriptPane = memo(function TranscriptPane({
  actions,
  composer,
  progress,
  transcript
}: Pick<AppLayoutProps, 'actions' | 'composer' | 'progress' | 'transcript'>) {
  const ui = useStore($uiState)

  // LiveTodoPanel rides as a child of the latest user-message row so it
  // visually belongs to the prompt and follows it during scroll. -1 when
  // empty → row.index === -1 is always false → no render.
  const lastUserIdx = useMemo(() => {
    const items = transcript.historyItems

    for (let i = items.length - 1; i >= 0; i--) {
      if (items[i].role === 'user') {
        return i
      }
    }

    return -1
  }, [transcript.historyItems])

  // Index of the first user-role message; every later user message gets a
  // small dash above it so multi-turn transcripts visually segment by
  // turn. -1 when no user message has been sent yet → no separator ever
  // renders.
  const firstUserIdx = useMemo(
    () => transcript.historyItems.findIndex(m => m.role === 'user'),
    [transcript.historyItems]
  )

  return (
    <>
      <ScrollBox
        flexDirection="column"
        flexGrow={1}
        flexShrink={1}
        onClick={(e: { cellIsBlank?: boolean }) => {
          if (e.cellIsBlank) {
            actions.clearSelection()
          }
        }}
        ref={transcript.scrollRef}
        stickyScroll
      >
        <Box flexDirection="column" paddingBottom={1} paddingX={1}>
          {transcript.virtualHistory.topSpacer > 0 ? <Box height={transcript.virtualHistory.topSpacer} /> : null}

          {transcript.virtualRows.slice(transcript.virtualHistory.start, transcript.virtualHistory.end).map(row => (
            <Box flexDirection="column" key={row.key} ref={transcript.virtualHistory.measureRef(row.key)}>
              {row.msg.role === 'user' && firstUserIdx >= 0 && row.index > firstUserIdx && (
                <Box marginTop={1}>
                  <Text color={ui.theme.color.border}>───</Text>
                </Box>
              )}

              {row.msg.kind === 'intro' ? (
                <Box flexDirection="column" paddingTop={1}>
                  <Banner t={ui.theme} />

                  {row.msg.info && <SessionPanel info={row.msg.info} sid={ui.sid} t={ui.theme} />}
                </Box>
              ) : row.msg.kind === 'panel' && row.msg.panelData ? (
                <Panel
                  onCommandClick={actions.runCommand}
                  onCommandDraft={actions.draftCommand}
                  sections={row.msg.panelData.sections}
                  t={ui.theme}
                  title={row.msg.panelData.title}
                />
              ) : (
                <MessageLine
                  cols={composer.cols}
                  compact={ui.compact}
                  detailsMode={ui.detailsMode}
                  detailsModeCommandOverride={ui.detailsModeCommandOverride}
                  msg={row.msg}
                  sections={ui.sections}
                  t={ui.theme}
                />
              )}

              {row.index === lastUserIdx && <LiveTodoPanel />}
            </Box>
          ))}

          {transcript.virtualHistory.bottomSpacer > 0 ? <Box height={transcript.virtualHistory.bottomSpacer} /> : null}

          <StreamingAssistant
            cols={composer.cols}
            compact={ui.compact}
            detailsMode={ui.detailsMode}
            detailsModeCommandOverride={ui.detailsModeCommandOverride}
            progress={progress}
            sections={ui.sections}
          />
        </Box>
      </ScrollBox>

      <NoSelect flexShrink={0} marginLeft={1}>
        <TranscriptScrollbar scrollRef={transcript.scrollRef} t={ui.theme} />
      </NoSelect>

      <StickyPromptTracker
        messages={transcript.historyItems}
        offsets={transcript.virtualHistory.offsets}
        onChange={actions.setStickyPrompt}
        scrollRef={transcript.scrollRef}
      />
    </>
  )
})

const ComposerPane = memo(function ComposerPane({
  actions,
  composer,
  status
}: Pick<AppLayoutProps, 'actions' | 'composer' | 'status'>) {
  const ui = useStore($uiState)
  const isBlocked = useStore($isBlocked)
  const sh = (composer.inputBuf[0] ?? composer.input).startsWith('!')
  const promptText = composerPromptText(ui.theme.brand.prompt, ui.info?.profile_name, sh)
  const promptWidth = composerPromptWidth(promptText)
  const promptBlank = ' '.repeat(promptWidth)
  const inputColumns = stableComposerColumns(composer.cols, promptWidth)
  const inputHeight = inputVisualHeight(composer.input, inputColumns)
  const inputMouseRef = useRef<null | TextInputMouseApi>(null)

  const captureInputDrag = (e: GutterMouseEvent) => {
    if (e.button !== 0) {
      return
    }

    e.stopImmediatePropagation?.()
    inputMouseRef.current?.startAtBeginning()
  }

  // Drag origin matches the input box's top-left, so localRow / localCol
  // map directly into TextInput coords (after backing out the prompt cell).
  const dragFromPromptRow = (e: GutterMouseEvent) => {
    if (e.button !== 0) {
      return
    }

    e.stopImmediatePropagation?.()
    inputMouseRef.current?.dragAt(e.localRow ?? 0, (e.localCol ?? 0) - promptWidth)
  }

  // Spacer rows live on a different vertical origin; only the column is
  // parent-aligned with the input. Force row=0 so vertical drags can't
  // jump the cursor to the wrong wrapped line.
  const dragFromSpacer = (e: GutterMouseEvent) => {
    if (e.button !== 0) {
      return
    }

    e.stopImmediatePropagation?.()
    inputMouseRef.current?.dragAt(0, (e.localCol ?? 0) - promptWidth)
  }

  const endInputDrag = () => inputMouseRef.current?.end()

  return (
    <NoSelect
      flexDirection="column"
      flexShrink={0}
      fromLeftEdge
      onClick={(e: { cellIsBlank?: boolean }) => {
        if (e.cellIsBlank) {
          actions.clearSelection()
        }
      }}
      paddingX={1}
    >
      <QueuedMessages
        cols={composer.cols}
        queued={composer.queuedDisplay}
        queueEditIdx={composer.queueEditIdx}
        t={ui.theme}
      />

      {ui.bgTasks.size > 0 && (
        <Text color={ui.theme.color.muted}>
          {ui.bgTasks.size} background {ui.bgTasks.size === 1 ? 'task' : 'tasks'} running
        </Text>
      )}

      {status.showStickyPrompt ? (
        <Text color={ui.theme.color.muted} wrap="truncate-end">
          <Text color={ui.theme.color.label}>↳ </Text>

          {status.stickyPrompt}
        </Text>
      ) : (
        <Box height={1} onMouseDown={captureInputDrag} onMouseDrag={dragFromSpacer} onMouseUp={endInputDrag} />
      )}

      <StatusRulePane at="top" composer={composer} status={status} />

      <Box flexDirection="column" marginTop={ui.statusBar === 'top' ? 0 : 1} position="relative">
        <FloatingOverlays
          cols={composer.cols}
          compIdx={composer.compIdx}
          completions={composer.completions}
          onModelSelect={actions.onModelSelect}
          onPickerSelect={actions.resumeById}
          pagerPageSize={composer.pagerPageSize}
        />

        {composer.input === '?' && !composer.inputBuf.length && <HelpHint t={ui.theme} />}

        {!isBlocked && (
          <>
            {composer.inputBuf.map((line, i) => (
              <Box key={i}>
                <Box width={promptWidth}>
                  {i === 0 ? (
                    <PromptPrefix color={ui.theme.color.muted} promptText={promptText} width={promptWidth} />
                  ) : (
                    <Text color={ui.theme.color.muted}>{promptBlank}</Text>
                  )}
                </Box>

                <Text color={ui.theme.color.text}>{line || ' '}</Text>
              </Box>
            ))}

            <Box
              onMouseDown={captureInputDrag}
              onMouseDrag={dragFromPromptRow}
              onMouseUp={endInputDrag}
              position="relative"
              width={Math.max(1, composer.cols - 2)}
            >
              <Box width={promptWidth}>
                {sh ? (
                  <PromptPrefix color={ui.theme.color.shellDollar} promptText={promptText} width={promptWidth} />
                ) : composer.inputBuf.length ? (
                  <Text color={ui.theme.color.prompt}>{promptBlank}</Text>
                ) : (
                  <PromptPrefix bold color={ui.theme.color.prompt} promptText={promptText} width={promptWidth} />
                )}
              </Box>

              <Box flexGrow={0} flexShrink={0} height={inputHeight} width={inputColumns}>
                {/* Reserve the transcript scrollbar gutter too so typing never rewraps when the scrollbar column repaints. */}
                <TextInput
                  columns={inputColumns}
                  mouseApiRef={inputMouseRef}
                  onChange={composer.updateInput}
                  onPaste={composer.handleTextPaste}
                  onSubmit={composer.submit}
                  placeholder={composer.empty ? PLACEHOLDER : ui.busy ? 'Ctrl+C to interrupt…' : ''}
                  value={composer.input}
                  voiceRecordKey={composer.voiceRecordKey}
                />
              </Box>

              <Box position="absolute" right={0}>
                <ForecastPulse t={ui.theme} tick={status.forecastPulseTick} />
              </Box>
            </Box>
          </>
        )}
      </Box>

      {!composer.empty && !ui.sid && <Text color={ui.theme.color.muted}>P {ui.status}</Text>}

      <StatusRulePane at="bottom" composer={composer} status={status} />
    </NoSelect>
  )
})

const AgentsOverlayPane = memo(function AgentsOverlayPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)
  const overlay = useStore($overlayState)

  return (
    <AgentsOverlay
      gw={gw}
      initialHistoryIndex={overlay.agentsInitialHistoryIndex}
      onClose={() => patchOverlayState({ agents: false, agentsInitialHistoryIndex: 0 })}
      t={ui.theme}
    />
  )
})

const ForecastsWorkspacePane = memo(function ForecastsWorkspacePane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)
  const overlay = useStore($overlayState)

  return (
    <ForecastsWorkspace
      gw={gw}
      initialId={overlay.forecastsInitialId}
      onClose={() => patchOverlayState({ forecasts: false, forecastsInitialId: null })}
      t={ui.theme}
    />
  )
})

const StatusRulePane = memo(function StatusRulePane({
  at,
  composer,
  status
}: Pick<AppLayoutProps, 'composer' | 'status'> & { at: 'bottom' | 'top' }) {
  const ui = useStore($uiState)

  if (ui.statusBar !== at) {
    return null
  }

  return (
    <Box marginTop={at === 'top' ? 1 : 0}>
      <StatusRule
        bgCount={ui.bgTasks.size}
        busy={ui.busy}
        cols={composer.cols}
        cwdLabel={status.cwdLabel}
        deskStatus={ui.forecastDeskStatus}
        model={ui.info?.model ?? ''}
        modelFast={ui.info?.fast || ui.info?.service_tier === 'priority'}
        modelReasoningEffort={ui.info?.reasoning_effort}
        sessionStartedAt={status.sessionStartedAt}
        showCost={ui.showCost}
        status={ui.status}
        statusColor={status.statusColor}
        t={ui.theme}
        turnStartedAt={status.turnStartedAt}
        usage={ui.usage}
        voiceLabel={status.voiceLabel}
      />
    </Box>
  )
})

const ForecastDeskActionStrip = memo(function ForecastDeskActionStrip({
  cols,
  draftCommand,
  railVisible,
  runCommand
}: {
  cols: number
  draftCommand: (command: string) => void
  railVisible: boolean
  runCommand: (command: string) => void
}) {
  const ui = useStore($uiState)
  const actions = useMemo(
    () => forecastDeskActionStripItems(ui.forecastDeskRailSections, railVisible ? 3 : 4),
    [railVisible, ui.forecastDeskRailSections]
  )

  if (!actions.length || ui.compact) {
    return null
  }

  const maxDetail = Math.max(18, Math.min(46, Math.floor(cols / actions.length) - 14))

  return (
    <NoSelect flexDirection="column" flexShrink={0} paddingX={1}>
      <Box flexDirection="row" width={Math.max(1, cols - 2)}>
        <Box flexShrink={0} width={13}>
          <Text bold color={ui.theme.color.primary}>
            desk actions
          </Text>
        </Box>

        {actions.map((action, index) => (
          <Box
            flexShrink={0}
            key={action.command}
            onClick={(event: CommandClickEvent) =>
              runTargetFromClick(action.target ?? action.command, draftCommand, runCommand, event)
            }
          >
            <Text wrap="truncate">
              <Text color={ui.theme.color.muted}>{index === 0 ? '  ' : '  |  '}</Text>
              <Text color={ui.theme.color.accent}>{action.command}</Text>
              {action.detail ? (
                <Text color={ui.theme.color.muted}> {truncateRail(action.detail, maxDetail)}</Text>
              ) : null}
            </Text>
          </Box>
        ))}
      </Box>
    </NoSelect>
  )
})

const ForecastDeskCompactBrief = memo(function ForecastDeskCompactBrief({
  cols,
  railVisible
}: {
  cols: number
  railVisible: boolean
}) {
  const ui = useStore($uiState)
  const items = useMemo(() => forecastDeskCompactItems(ui.forecastDeskRailSections, railVisible ? 0 : 3), [
    railVisible,
    ui.forecastDeskRailSections
  ])

  if (!items.length || ui.compact || railVisible) {
    return null
  }

  const maxDetail = Math.max(18, Math.min(58, Math.floor(cols / Math.max(1, items.length)) - 12))

  return (
    <NoSelect flexDirection="column" flexShrink={0} paddingX={1}>
      <Text wrap="truncate">
        <Text bold color={ui.theme.color.primary}>
          desk brief
        </Text>

        {items.map((item, index) => (
          <Fragment key={`${item.label}:${item.detail}`}>
            <Text color={ui.theme.color.muted}>{index === 0 ? '  ' : '  |  '}</Text>
            <Text color={ui.theme.color.accent}>{item.label}</Text>
            <Text color={ui.theme.color.muted}> {truncateRail(item.detail, maxDetail)}</Text>
          </Fragment>
        ))}
      </Text>
    </NoSelect>
  )
})

const ForecastDeskViewStrip = memo(function ForecastDeskViewStrip({
  cols,
  draftCommand,
  runCommand
}: {
  cols: number
  draftCommand: (command: string) => void
  runCommand: (command: string) => void
}) {
  const ui = useStore($uiState)

  if (!ui.forecastDeskRailSections.length || ui.compact || cols < 88) {
    return null
  }

  const viewLimit = cols >= 170 ? 9 : cols >= 146 ? 7 : cols >= 120 ? 5 : 3
  const views = FORECAST_TUI_VIEW_SHORTCUTS.slice(0, viewLimit)

  return (
    <NoSelect flexShrink={0} paddingX={1}>
      <Box flexDirection="row" width={Math.max(1, cols - 2)}>
        <Box flexShrink={0} width={7}>
          <Text bold color={ui.theme.color.primary}>
            views
          </Text>
        </Box>

        {views.map((shortcut, index) => (
          <Box
            flexShrink={0}
            key={shortcut.id}
            onClick={(event: CommandClickEvent) =>
              runTargetFromClick(shortcut.command, draftCommand, runCommand, event)
            }
          >
            <Text wrap="truncate">
              <Text color={ui.theme.color.muted}>{index === 0 ? '' : '  |  '}</Text>
              <Text color={ui.theme.color.muted}>{forecastShortcutDisplayHotkey(shortcut)}</Text>
              <Text color={ui.theme.color.accent}> {shortcut.label}</Text>
            </Text>
          </Box>
        ))}

        <Text color={ui.theme.color.muted}>  |  {FORECAST_TUI_FIND_SHORTCUT.hotkey}</Text>
        <Text color={ui.theme.color.accent}> {FORECAST_TUI_FIND_SHORTCUT.label}</Text>
      </Box>
    </NoSelect>
  )
})

const ForecastDeskHeader = memo(function ForecastDeskHeader({
  cols,
  draftCommand,
  runCommand
}: {
  cols: number
  draftCommand: (command: string) => void
  runCommand: (command: string) => void
}) {
  const ui = useStore($uiState)
  const primaryAction = useMemo(() => forecastDeskPrimaryActionItem(ui.forecastDeskRailSections), [
    ui.forecastDeskRailSections
  ])

  if (!ui.forecastDeskRailSections.length || ui.compact) {
    return null
  }

  const statusWidth = primaryAction ? Math.max(12, Math.floor(cols * 0.32)) : Math.max(18, cols - 18)
  const actionWidth = Math.max(18, cols - statusWidth - 34)

  return (
    <NoSelect flexShrink={0} paddingX={1}>
      <Box flexDirection="row" width={Math.max(1, cols - 2)}>
        <Text bold color={ui.theme.color.primary}>
          Forecast Desk
        </Text>

        {ui.forecastDeskStatus ? (
          <>
            <Text color={ui.theme.color.muted}>  </Text>
            <Text color={ui.theme.color.muted}>{truncateRail(ui.forecastDeskStatus, statusWidth)}</Text>
          </>
        ) : null}

        {primaryAction ? (
          <Box
            onClick={(event: CommandClickEvent) =>
              runTargetFromClick(primaryAction.target ?? primaryAction.command, draftCommand, runCommand, event)
            }
          >
            <Text wrap="truncate">
              <Text color={ui.theme.color.muted}>  next </Text>
              <Text color={ui.theme.color.accent}>{primaryAction.command}</Text>
              {primaryAction.detail ? (
                <Text color={ui.theme.color.muted}> {truncateRail(primaryAction.detail, actionWidth)}</Text>
              ) : null}
            </Text>
          </Box>
        ) : null}
      </Box>
    </NoSelect>
  )
})

const ForecastDeskRail = memo(function ForecastDeskRail({
  draftCommand,
  runCommand,
  sections,
  status
}: {
  draftCommand: (command: string) => void
  runCommand: (command: string) => void
  sections: PanelSection[]
  status: string
}) {
  const ui = useStore($uiState)
  const visibleSections = sections.filter(sec => sec.rows?.length || sec.items?.length || sec.text).slice(0, 5)

  if (!visibleSections.length) {
    return null
  }

  return (
    <Box
      borderColor={ui.theme.color.border}
      borderStyle="single"
      flexDirection="column"
      flexShrink={0}
      height="100%"
      paddingX={1}
      paddingY={1}
      width={FORECAST_RAIL_WIDTH}
    >
      <Text bold color={ui.theme.color.primary} wrap="truncate">
        Forecast Desk
      </Text>

      {status && (
        <Text color={ui.theme.color.muted} wrap="truncate">
          {truncateRail(status, FORECAST_RAIL_WIDTH - 4)}
        </Text>
      )}

      {visibleSections.map((sec, si) => (
        <Box flexDirection="column" key={si} marginTop={si > 0 || status ? 1 : 0}>
          {sec.title && (
            <Text bold color={ui.theme.color.accent} wrap="truncate">
              {truncateRail(sec.title, FORECAST_RAIL_WIDTH - 4)}
            </Text>
          )}

          {sec.rows?.slice(0, 4).map((row, rowIndex) => {
            const [key, value, commandCandidate] = row
            return (
              <Box
                key={rowIndex}
                onClick={(event: CommandClickEvent) =>
                  runTargetFromClick(commandCandidate ?? key, draftCommand, runCommand, event)
                }
              >
                <Text color={ui.theme.color.muted}>{truncateRail(key, 13).padEnd(13)}</Text>
                <Text color={ui.theme.color.text}>{truncateRail(value, FORECAST_RAIL_WIDTH - 19)}</Text>
              </Box>
            )
          })}

          {sec.items?.slice(0, 4).map((item, itemIndex) => (
            <Box
              key={itemIndex}
              onClick={(event: CommandClickEvent) => runTargetFromClick(item, draftCommand, runCommand, event)}
            >
              <Text color={ui.theme.color.text} wrap="truncate">
                {truncateRail(item, FORECAST_RAIL_WIDTH - 4)}
              </Text>
            </Box>
          ))}

          {sec.text && (
            <Text color={ui.theme.color.muted} wrap="truncate">
              {truncateRail(sec.text, FORECAST_RAIL_WIDTH - 4)}
            </Text>
          )}
        </Box>
      ))}
    </Box>
  )
})

export const AppLayout = memo(function AppLayout({
  actions,
  composer,
  mouseTracking,
  progress,
  status,
  transcript
}: AppLayoutProps) {
  const overlay = useStore($overlayState)
  const ui = useStore($uiState)
  // A full-screen overlay (spawn tree or forecasts workspace) takes over the
  // viewport — hide the desk chrome and transcript while one is open.
  const fullscreen = overlay.agents || overlay.forecasts
  const showForecastRail =
    !fullscreen && !ui.compact && composer.cols >= FORECAST_RAIL_MIN_COLS && ui.forecastDeskRailSections.length > 0

  // Inline mode skips AlternateScreen so the host terminal's native
  // scrollback captures rows scrolled off the top; composer + progress
  // stay anchored via normal flex-column flow.
  const Shell = INLINE_MODE ? Fragment : AlternateScreen
  const shellProps = INLINE_MODE ? {} : { mouseTracking }

  return (
    <Shell {...shellProps}>
      <Box flexDirection="column" flexGrow={1}>
        {!fullscreen && (
          <PerfPane id="forecast-header">
            <ForecastDeskHeader
              cols={composer.cols}
              draftCommand={actions.draftCommand}
              runCommand={actions.runCommand}
            />
          </PerfPane>
        )}

        {!fullscreen && (
          <PerfPane id="forecast-views">
            <ForecastDeskViewStrip
              cols={composer.cols}
              draftCommand={actions.draftCommand}
              runCommand={actions.runCommand}
            />
          </PerfPane>
        )}

        <Box flexDirection="row" flexGrow={1}>
          {overlay.forecasts ? (
            <PerfPane id="forecasts">
              <ForecastsWorkspacePane />
            </PerfPane>
          ) : overlay.agents ? (
            <PerfPane id="agents">
              <AgentsOverlayPane />
            </PerfPane>
          ) : (
            <>
              <PerfPane id="transcript">
                <TranscriptPane actions={actions} composer={composer} progress={progress} transcript={transcript} />
              </PerfPane>

              {showForecastRail && (
                <NoSelect flexShrink={0} marginLeft={1}>
                  <PerfPane id="forecast-rail">
                    <ForecastDeskRail
                      draftCommand={actions.draftCommand}
                      runCommand={actions.runCommand}
                      sections={ui.forecastDeskRailSections}
                      status={ui.forecastDeskStatus}
                    />
                  </PerfPane>
                </NoSelect>
              )}
            </>
          )}
        </Box>

        {!fullscreen && (
          <>
            <PerfPane id="prompt">
              <PromptZone
                cols={composer.cols}
                onApprovalChoice={actions.answerApproval}
                onClarifyAnswer={actions.answerClarify}
                onSecretSubmit={actions.answerSecret}
                onSudoSubmit={actions.answerSudo}
              />
            </PerfPane>

            <PerfPane id="forecast-brief">
              <ForecastDeskCompactBrief cols={composer.cols} railVisible={showForecastRail} />
            </PerfPane>

            <PerfPane id="forecast-actions">
              <ForecastDeskActionStrip
                cols={composer.cols}
                draftCommand={actions.draftCommand}
                railVisible={showForecastRail}
                runCommand={actions.runCommand}
              />
            </PerfPane>

            <PerfPane id="composer">
              <ComposerPane actions={actions} composer={composer} status={status} />
            </PerfPane>

            {SHOW_FPS && (
              <Box flexShrink={0} justifyContent="flex-end" paddingRight={1}>
                <FpsOverlay t={ui.theme} />
              </Box>
            )}
          </>
        )}
      </Box>
    </Shell>
  )
})

type GutterMouseEvent = {
  button: number
  localCol?: number
  localRow?: number
  stopImmediatePropagation?: () => void
}
