import { AlternateScreen, Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { Fragment, memo, type RefObject, useCallback, useEffect, useMemo, useRef } from 'react'

import { $agentsActive } from '../app/agentsActiveStore.js'
import { $chordPending } from '../app/chordStore.js'
import { useGateway } from '../app/gatewayContext.js'
import { $homeFocus, setHomePane } from '../app/homeFocusStore.js'
import type { AppLayoutProps } from '../app/interfaces.js'
import { activeNavKey, canOpenGlobalOverlay, selectNavView } from '../app/navRoutes.js'
import { $globalModal, $isBlocked, $overlayState, patchOverlayState } from '../app/overlayStore.js'
import { $uiSessionId, $uiState, $uiTheme } from '../app/uiStore.js'
import { useAgentsActivePoll } from '../app/useAgentsActivePoll.js'
import { INLINE_MODE, SHOW_FPS } from '../config/env.js'
import { VIEW_CHORDS } from '../content/keymaps.js'
import { PLACEHOLDER } from '../content/placeholders.js'
import { useHideCursorWhileFullscreen } from '../lib/cursorVisibility.js'
import { RAIL_WIDTH, showRailFor } from '../lib/homeLayout.js'
import {
  COMPOSER_PROMPT_GAP_WIDTH,
  composerPromptWidth,
  inputVisualHeight,
  stableComposerColumns
} from '../lib/inputMetrics.js'
import { PerfPane } from '../lib/perfPane.js'
import { composerPromptText } from '../lib/prompt.js'
import { startSignalReceiver } from '../lib/signalLive.js'
import { resolveSignalConfig } from '../lib/signalStore.js'

import { AgentsOverlay } from './agentsOverlay.js'
import { AlertsView } from './alertsView.js'
import { ForecastPulse, StickyPromptTracker, TranscriptScrollbar } from './appChrome.js'
import { FloatingOverlays, PromptZone } from './appOverlays.js'
import { HomeHero, Panel, SessionPanel } from './branding.js'
import { CalendarView } from './calendarView.js'
import { CalibrationView } from './calibrationView.js'
import { CheatSheetOverlay } from './cheatSheetOverlay.js'
import { ConversationsRail } from './conversationsRail.js'
import { DemoVizView } from './demoVizView.js'
import { DeskView } from './deskView.js'
import { DocsView } from './docsView.js'
import { FpsOverlay } from './fpsOverlay.js'
import { HelpHint } from './helpHint.js'
import { HelpView } from './helpView.js'
import { HomeStatusBar, HomeTip } from './homeLanding.js'
import { HooksView } from './hooksView.js'
import { MarketsView } from './marketsView.js'
import { MessageLine } from './messageLine.js'
import { MessagingView } from './messagingView.js'
import { NavBar } from './navBar.js'
import { NewsView } from './newsView.js'
import { PaletteOverlay } from './paletteOverlay.js'
import { QuestionOnboardModal } from './questionOnboardModal.js'
import { QueuedMessages } from './queuedMessages.js'
import { ScheduleStrip } from './scheduleStrip.js'
import { LiveTodoPanel, StreamingAssistant } from './streamingAssistant.js'
import { TextInput, type TextInputMouseApi } from './textInput.js'
import { TodayPanel } from './todayPanel.js'
import { type CrashReport, ViewErrorBoundary } from './viewErrorBoundary.js'

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
  decstbm = true,
  progress,
  transcript
}: Pick<AppLayoutProps, 'actions' | 'composer' | 'progress' | 'transcript'> & { decstbm?: boolean }) {
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
        // decstbm={false} only in the two-pane Home, where the conversation sits
        // beside the rail and its full-width hardware scroll would move the rail's
        // rows. Single-pane keeps the fast path (decstbm defaults true). The box
        // stays a DIRECT child of the flex-grow row so it gets a clean bounded
        // height — burying it deeper collapses the measured viewport and makes
        // scroll stick to the top/bottom.
        decstbm={decstbm}
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
                <HomeHero info={row.msg.info} maxCols={composer.cols} t={ui.theme} />
              ) : row.msg.kind === 'session' && row.msg.info ? (
                <SessionPanel info={row.msg.info} sid={ui.sid} t={ui.theme} />
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
  confined = false,
  landing = false,
  status
}: Pick<AppLayoutProps, 'actions' | 'composer' | 'status'> & { confined?: boolean; landing?: boolean }) {
  const ui = useStore($uiState)
  const isBlocked = useStore($isBlocked)
  const chordPending = useStore($chordPending)

  // Guided OAuth connect from the model picker: close it and launch the in-TUI
  // device-code sign-in (`/auth <slug>`), so connecting Codex never dead-ends.
  const onModelConnect = useCallback(
    (slug: string) => {
      patchOverlayState({ modelPicker: false })
      actions.runCommand(`/auth ${slug}`)
    },
    [actions]
  )

  // The composer only owns the keyboard while the 'conversation' pane holds focus;
  // when the conversations rail OR the landing "Today" panel holds it, the composer
  // goes inactive so its keystrokes/cursor don't compete with that pane's navigation.
  const composerActive = useStore($homeFocus).pane === 'conversation'
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
      // fromLeftEdge spans the whole terminal width; off when the composer is
      // confined to the Home right pane so it stays inside that column.
      fromLeftEdge={!confined}
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

      {chordPending ? (
        <Text color={ui.theme.color.accent}>
          {`Ctrl+${chordPending.toUpperCase()}`} …{' '}
          <Text color={ui.theme.color.muted}>{VIEW_CHORDS.map(c => `${c.key} ${c.label}`).join(' · ')}</Text>
        </Text>
      ) : null}

      {status.showStickyPrompt ? (
        <Text color={ui.theme.color.muted} wrap="truncate-end">
          <Text color={ui.theme.color.label}>↳ </Text>

          {status.stickyPrompt}
        </Text>
      ) : (
        <Box height={1} onMouseDown={captureInputDrag} onMouseDrag={dragFromSpacer} onMouseUp={endInputDrag} />
      )}

      {/* On the landing the composer yields its own status rule — a deliberately
          sparse 3-item bar renders at the very bottom of the Home column instead. */}
      {landing ? null : <StatusRulePane at="top" composer={composer} status={status} />}

      <Box
        flexDirection="column"
        marginTop={landing || ui.statusBar === 'top' ? 0 : 1}
        position="relative"
      >
        <FloatingOverlays
          cols={composer.cols}
          compIdx={composer.compIdx}
          completions={composer.completions}
          onModelConnect={onModelConnect}
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
                  focus={composerActive}
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

      {landing ? null : <StatusRulePane at="bottom" composer={composer} status={status} />}
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
    <DeskView
      gw={gw}
      initialId={overlay.forecastsInitialId}
      onClose={() => patchOverlayState({ forecasts: false, forecastsInitialId: null })}
      t={ui.theme}
    />
  )
})

const CalibrationViewPane = memo(function CalibrationViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <CalibrationView gw={gw} onClose={() => patchOverlayState({ calibration: false })} t={ui.theme} />
})

const AlertsViewPane = memo(function AlertsViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)
  const overlay = useStore($overlayState)

  return (
    <AlertsView
      gw={gw}
      initialFocus={overlay.alertsInitialFocus ?? undefined}
      onClose={() => patchOverlayState({ alerts: false, alertsInitialFocus: null })}
      sessionId={ui.sid ?? ''}
      t={ui.theme}
    />
  )
})

const HelpViewPane = memo(function HelpViewPane() {
  const ui = useStore($uiState)

  return <HelpView onClose={() => patchOverlayState({ help: false })} t={ui.theme} />
})

// The Home schedule-health strip — self-fetches forecast.schedule.status and
// renders nothing until the desk actually has something scheduled.
const ScheduleStripPane = memo(function ScheduleStripPane({ width }: { width: number }) {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <ScheduleStrip gw={gw} t={ui.theme} width={width} />
})

const DemoVizViewPane = memo(function DemoVizViewPane() {
  const ui = useStore($uiState)

  return <DemoVizView onClose={() => patchOverlayState({ demoViz: false })} t={ui.theme} />
})

// The global interaction chrome (Ctrl+K palette / `?` cheat-sheet). Both paint
// through the shared ModalOverlay (absolute box, opaque, centred). It STACKS
// above the still-mounted body EVERYWHERE now — the HOME landing OR any
// fullscreen VIEW (Desk, Markets, …) — rendered LAST so the body stays visible
// around it. Every fullscreen view gates its own useInput (`isActive:
// !globalModal`) + its mouse handlers on the $globalModal flag, so nothing
// beneath the overlay double-handles keys/clicks. The modal's own useInput is
// the active keyboard handler; the global seam early-returns while $isBlocked
// (which includes palette/cheatSheet) is set. Reads the live overlay flags to
// pick the palette vs the cheat-sheet + the active view.
const GlobalChromePane = memo(function GlobalChromePane({
  cols,
  onRun,
  rows
}: {
  cols: number
  onRun: (command: string) => void
  rows: number
}) {
  const ui = useStore($uiState)
  const overlay = useStore($overlayState)

  if (overlay.palette) {
    return (
      <PaletteOverlay
        cols={cols}
        onClose={() => patchOverlayState({ palette: false })}
        onRun={onRun}
        rows={rows}
        t={ui.theme}
      />
    )
  }

  return (
    <CheatSheetOverlay
      activeView={activeNavKey(overlay)}
      cols={cols}
      onClose={() => patchOverlayState({ cheatSheet: false })}
      rows={rows}
      t={ui.theme}
    />
  )
})

const HooksViewPane = memo(function HooksViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <HooksView gw={gw} onClose={() => patchOverlayState({ hooks: false })} t={ui.theme} />
})

const MarketsViewPane = memo(function MarketsViewPane({ onAsk }: { onAsk: (question: string) => void }) {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <MarketsView gw={gw} onAsk={onAsk} onClose={() => patchOverlayState({ markets: false })} sessionId={ui.sid ?? ''} t={ui.theme} />
})

const NewsViewPane = memo(function NewsViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)
  const overlay = useStore($overlayState)

  return (
    <NewsView
      gw={gw}
      initialQuery={overlay.newsInitialQuery}
      onClose={() => patchOverlayState({ news: false, newsInitialQuery: null })}
      t={ui.theme}
    />
  )
})

const MessagingViewPane = memo(function MessagingViewPane() {
  const ui = useStore($uiState)

  return <MessagingView onClose={() => patchOverlayState({ messaging: false })} t={ui.theme} />
})

const CalendarViewPane = memo(function CalendarViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <CalendarView gw={gw} onClose={() => patchOverlayState({ calendar: false })} t={ui.theme} />
})

const QuestionOnboardPane = memo(function QuestionOnboardPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <QuestionOnboardModal gw={gw} onClose={() => patchOverlayState({ onboard: false })} t={ui.theme} />
})

const ConversationsRailPane = memo(function ConversationsRailPane({
  onNewChat,
  onSelect,
  scrollRef
}: {
  onNewChat: () => void
  onSelect: (id: string) => void
  scrollRef: RefObject<null | ScrollBoxHandle>
}) {
  const { gw } = useGateway()
  // Subscribe ONLY to the sid + theme this rail actually uses — NOT the whole
  // $uiState. Typing in the composer re-renders the app (composer text lives in
  // useMainApp), and a broad $uiState subscription dragged the Recents rail (and
  // its ScrollBox) into every keystroke, making it drift. These computed atoms
  // only notify on a real sid/theme change, so the rail stays put while you type.
  const sid = useStore($uiSessionId)
  const t = useStore($uiTheme)
  const homeFocus = useStore($homeFocus)
  const overlay = useStore($overlayState)
  const onExitFocus = useCallback(() => setHomePane('conversation'), [])

  // While the palette / cheat-sheet overlay paints above the still-mounted home
  // body, the rail must yield BOTH its keyboard (drop `focused`) and its row
  // clicks (`interactive={false}`) so nothing leaks past the overlay's trap.
  const globalModal = overlay.palette || overlay.cheatSheet

  return (
    <ConversationsRail
      currentSid={sid}
      focused={homeFocus.pane === 'rail' && !globalModal}
      gw={gw}
      interactive={!globalModal}
      onExitFocus={onExitFocus}
      onNewChat={onNewChat}
      onSelect={onSelect}
      refreshKey={sid ?? ''}
      scrollRef={scrollRef}
      t={t}
    />
  )
})

const DocsViewPane = memo(function DocsViewPane({ onDraft }: { onDraft: (command: string) => void }) {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return (
    <DocsView
      gw={gw}
      onClose={() => patchOverlayState({ obsidian: false })}
      onDraft={onDraft}
      sid={ui.sid}
      t={ui.theme}
    />
  )
})

// The active-conversation status rule is now the SAME slim three-item bar the Home
// landing pins (HomeStatusBar) — one source of truth, no second bespoke bar. The
// dense desk inventory (forecasts · theses · factors · entities · alerts · closing)
// is dropped from the chat surface entirely — that detail lives in the Desk — so
// the operator sees only ready-state · the single actionable "N to review" count ·
// model, plus the "✦ N agents running" chip (this is exactly where the operator
// launches batches, so the heuristic matters most here) and the dim path far right.
const StatusRulePane = memo(function StatusRulePane({
  at,
  composer,
  status
}: Pick<AppLayoutProps, 'composer' | 'status'> & { at: 'bottom' | 'top' }) {
  const ui = useStore($uiState)
  const agents = useStore($agentsActive)
  const globalModal = useStore($globalModal)

  if (ui.statusBar !== at) {
    return null
  }

  return (
    <Box marginTop={at === 'top' ? 1 : 0}>
      <HomeStatusBar
        agents={agents}
        agentsGated={globalModal}
        cols={composer.cols}
        cwdLabel={status.cwdLabel}
        deskStatus={ui.forecastDeskStatus}
        model={ui.info?.model ?? ''}
        modelFast={ui.info?.fast || ui.info?.service_tier === 'priority'}
        modelReasoningEffort={ui.info?.reasoning_effort}
        onOpenAgents={() => selectNavView('agents')}
        status={ui.status}
        statusColor={status.statusColor}
        t={ui.theme}
      />
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
  const homeFocus = useStore($homeFocus)
  const agentsActive = useStore($agentsActive)
  const { gw } = useGateway()
  const { stdout } = useStdout()
  const rows = stdout?.rows ?? 24

  // The global chrome (Ctrl+K palette / `?` cheat-sheet) STACKS above the body
  // while open — see GlobalChromePane. It is NOT part of `fullscreen`, so it can
  // open over Home OR over a view; rendered LAST as an absolute ModalOverlay, it
  // leaves the body mounted beneath and floats on top. Every fullscreen view
  // gates its own useInput + mouse handlers on this flag so nothing double-fires.
  const globalModal = overlay.palette || overlay.cheatSheet

  // Keep the Signal receiver running app-wide — not just while the Messaging
  // view is open — so inbound messages are captured and cached even when you're
  // on another screen (signal-cli delivers each message once, then ACKs it).
  useEffect(() => {
    startSignalReceiver(resolveSignalConfig())
  }, [])

  // A full-screen overlay (spawn tree, forecasts workspace, or calibration
  // view) takes over the viewport — hide the transcript while one is open.
  // The forecast desk surfaces live entirely in those overlays now (opened by
  // command); the main screen is just transcript + prompt + status.
  const fullscreen =
    overlay.agents ||
    overlay.forecasts ||
    overlay.calibration ||
    overlay.alerts ||
    overlay.help ||
    overlay.calendar ||
    overlay.demoViz ||
    overlay.hooks ||
    overlay.markets ||
    overlay.news ||
    overlay.messaging ||
    overlay.obsidian ||
    overlay.onboard

  // Poll the live-agents aggregate (agents.active.summary) while a status bar is
  // visible — i.e. on the landing OR the active-conversation surface, but NOT while
  // a fullscreen overlay hides both bars. Bounded + torn down on unmount / overlay
  // open; the detached jobs keep running server-side regardless. Both bars read the
  // shared $agentsActive store this feeds, so the chip is a single source of truth.
  useAgentsActivePoll(gw, !fullscreen)

  // Single owner of the hardware cursor: hide it while any fullscreen view is
  // mounted (no view writes ?25l/?25h itself now), restore it on the way back to
  // the landing/composer. The composer's TextInput re-shows it while typing (see
  // useInputCursor) — that runs after this mount-hide, so it wins.
  useHideCursorWhileFullscreen(fullscreen, stdout)

  // Landing = the first-run screen, before any real interaction. We hold it
  // through gateway connect / startup notices and only leave once a turn or a
  // command panel lands — so startup `sys` warnings (which make `composer.empty`
  // false) don't collapse the layout or cause a starting→ready flip. On the
  // landing the hero floats centred in the space above the prompt; the prompt
  // itself stays pinned to the bottom exactly as in the active transcript.
  const hasInteraction = transcript.historyItems.some(
    msg => msg.role === 'user' || msg.role === 'assistant' || msg.kind === 'panel'
  )

  const landing = !hasInteraction && !fullscreen
  // Startup notices (credential/config warnings, update tips) still surface on
  // the landing — rendered under the prompt rather than lost behind it.
  const landingNotices = landing ? transcript.historyItems.filter(msg => msg.kind !== 'intro') : []

  // The landing "Today" panel earns a SOFT focus tier: while it's mounted with
  // rows, the composer is empty (no completions / buffer / draft — the exact
  // chromeArmable predicate the keyboard uses), the conversation pane holds
  // focus, and no overlay owns the keys, ↑↓/⏎ drive the panel WITHOUT taking the
  // keyboard from typing. `globalModal` additionally hard-gates the panel while
  // the palette / cheat-sheet paints above the still-mounted landing.
  const composerArmable = !composer.completions.length && !composer.inputBuf.length && !composer.input

  const todaySoftFocus =
    landing && homeFocus.pane === 'conversation' && composerArmable && canOpenGlobalOverlay(overlay)

  // Home is a persistent two-pane layout on wide terminals: a recent-conversations
  // rail on the left (kept whether you're on a new chat or reading one), and the
  // hero or the live transcript + composer on the right. The right pane does hard
  // width math off `cols`, so when the rail is shown it gets a reduced `cols`
  // matching its narrower column.
  const showRail = !fullscreen && showRailFor(composer.cols)

  const contentComposer = useMemo(
    () => (showRail ? { ...composer, cols: Math.max(48, composer.cols - RAIL_WIDTH - 2) } : composer),
    [composer, showRail]
  )

  // Stable so the memo'd rail pane doesn't re-render on every keystroke: an inline
  // arrow here would be a fresh function each render, breaking ConversationsRailPane's
  // memo (`actions` is itself a useMemo, so this stays referentially stable).
  const onRailNewChat = useCallback(() => actions.runCommand('/new'), [actions])

  // Crash recovery: when a fullscreen view throws, close every fullscreen overlay
  // so we drop back to the safe home/chat (the crashed view can't re-throw).
  const recoverFromCrash = useCallback(() => {
    patchOverlayState({
      agents: false,
      alerts: false,
      calendar: false,
      calibration: false,
      demoViz: false,
      forecasts: false,
      help: false,
      hooks: false,
      markets: false,
      messaging: false,
      news: false,
      obsidian: false,
      onboard: false
    })
  }, [])

  // Load a ready-to-send crash report into the composer: the user presses Enter
  // and the agent files the GitHub issue — the flow that already works when a
  // user pastes an error into the chat, now one keypress away from the modal.
  const reportCrash = useCallback(
    (report: CrashReport) => {
      actions.draftCommand(
        'A view in the TUI just crashed and the error boundary caught it. Please open a GitHub issue on the fork ' +
          'with `gh issue create --repo teddyjfpender/superforecasting-agent` — give it a clear, specific title, ' +
          'summarize what I was likely doing, include the error + stack trace below verbatim, and propose a fix. ' +
          'Then reply with the issue URL.\n\nError: ' +
          report.message +
          '\n\nStack:\n' +
          report.stack
      )
    },
    [actions]
  )

  // The rail can only hold focus while it's shown — when it hides (narrow
  // terminal / fullscreen overlay), snap focus back so the composer never stays
  // inert.
  useEffect(() => {
    if (!showRail) {
      setHomePane('conversation')
    }
  }, [showRail])

  // Inline mode skips AlternateScreen so the host terminal's native
  // scrollback captures rows scrolled off the top; composer + progress
  // stay anchored via normal flex-column flow.
  const Shell = INLINE_MODE ? Fragment : AlternateScreen
  const shellProps = INLINE_MODE ? {} : { mouseTracking }

  // The prompt + input + status bar, pinned to the bottom. `confined` narrows it
  // to the Home right pane (two-pane wide layout); otherwise it spans the full
  // terminal width (single-pane / narrow). `bar` carries the matching `cols`.
  const renderPromptBar = (bar: typeof composer, confined: boolean, landing = false) => (
    <>
      <PerfPane id="prompt">
        <PromptZone
          cols={bar.cols}
          onApprovalChoice={actions.answerApproval}
          onClarifyAnswer={actions.answerClarify}
          onSecretSubmit={actions.answerSecret}
          onSudoSubmit={actions.answerSudo}
        />
      </PerfPane>

      <PerfPane id="composer">
        <ComposerPane actions={actions} composer={bar} confined={confined} landing={landing} status={status} />
      </PerfPane>

      {SHOW_FPS && (
        <Box flexShrink={0} justifyContent="flex-end" paddingRight={1}>
          <FpsOverlay t={ui.theme} />
        </Box>
      )}
    </>
  )

  // The centred Home landing column, OpenCode-style top-to-bottom: breathing
  // room → the Outrider hero → the composer (the focal point, directly beneath
  // the hero) → the compact TODAY block → the SCHEDULE one-liner → more room →
  // ONE accent tip → a deliberately sparse 3-item status bar. `heroCols` sizes
  // the column (the right-pane width when the rail shows, else full width); `bar`
  // + `confined` carry the composer's matching columns.
  const renderLanding = (heroCols: number, bar: typeof composer, confined: boolean) => (
    <Box flexDirection="column" flexGrow={1} minHeight={0} minWidth={0}>
      {/* Top breathing room — whitespace as structure. */}
      <Box flexGrow={1} />

      <HomeHero info={ui.info ?? undefined} maxCols={heroCols} t={ui.theme} />

      {/* The composer sits directly under the hero as the obvious focal point.
          It keeps its landing soft-focus (not focused until typing) — only its
          own status rule is suppressed here (`landing`), replaced by the slim
          bar pinned at the bottom of this column. */}
      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        {renderPromptBar(bar, confined, true)}
      </Box>

      {/* The landing "Today" attention panel: the desk-rail sections the status
          strip already carries, rendered as an interactive feed of what needs a
          human. It keeps its Ctrl+T focus + click-to-Desk behaviour untouched —
          only capped to a compact 5 rows here. */}
      <Box flexShrink={0} marginTop={1} paddingX={1}>
        <TodayPanel
          contestedCount={ui.forecastContestedCount}
          focused={homeFocus.pane === 'today'}
          maxRows={5}
          onBlur={() => setHomePane('conversation')}
          onNewQuestion={() => {
            setHomePane('conversation')
            patchOverlayState({ onboard: true })
          }}
          onOpenAlerts={focus => {
            setHomePane('conversation')
            patchOverlayState({ alerts: true, alertsInitialFocus: focus ?? null })
          }}
          onOpenQuestion={id => {
            setHomePane('conversation')
            patchOverlayState({ forecasts: true, forecastsInitialId: id })
          }}
          onRunCommand={command => {
            setHomePane('conversation')
            actions.runCommand(command)
          }}
          overlayOpen={globalModal}
          sections={ui.forecastDeskRailSections}
          softFocus={todaySoftFocus}
          t={ui.theme}
          width={Math.max(20, heroCols - 2)}
        />
      </Box>

      {/* Schedule-health one-liner: sits just under Today, hidden unless the desk
          has something scheduled (self-fetches forecast.schedule.status). */}
      <Box flexShrink={0} paddingX={1}>
        <ScheduleStripPane width={Math.max(20, heroCols - 2)} />
      </Box>

      {landingNotices.length > 0 && (
        <NoSelect flexDirection="column" flexShrink={0} marginTop={1} paddingX={1}>
          {landingNotices.map((msg, index) => (
            <MessageLine
              cols={heroCols}
              compact={ui.compact}
              detailsMode={ui.detailsMode}
              detailsModeCommandOverride={ui.detailsModeCommandOverride}
              key={index}
              msg={msg}
              sections={ui.sections}
              t={ui.theme}
            />
          ))}
        </NoSelect>
      )}

      {/* Bottom breathing room, then the one accent tip + the slim status bar. */}
      <Box flexGrow={1} />

      <Box flexShrink={0} paddingX={1}>
        <HomeTip t={ui.theme} />
      </Box>

      <Box flexShrink={0} paddingX={1}>
        <HomeStatusBar
          agents={agentsActive}
          agentsGated={globalModal}
          cols={Math.max(20, heroCols - 2)}
          cwdLabel={status.cwdLabel}
          deskStatus={ui.forecastDeskStatus}
          model={ui.info?.model ?? ''}
          modelFast={ui.info?.fast || ui.info?.service_tier === 'priority'}
          modelReasoningEffort={ui.info?.reasoning_effort}
          onOpenAgents={() => selectNavView('agents')}
          status={ui.status}
          statusColor={status.statusColor}
          t={ui.theme}
        />
      </Box>
    </Box>
  )

  return (
    <Shell {...shellProps}>
      <Box flexDirection="column" flexGrow={1}>
        <PerfPane id="navbar">
          <NavBar />
        </PerfPane>

        {fullscreen ? (
          // Over a fullscreen VIEW the palette / cheat-sheet now STACKS above the
          // still-mounted body (same recipe as Home below): every view gates its
          // own useInput (`isActive: !globalModal`) + its mouse handlers on the
          // $globalModal flag, so leaving them mounted beneath the overlay can no
          // longer double-handle keys/clicks. The overlay renders LAST as an
          // absolute ModalOverlay and floats on top.
          <>
          <ViewErrorBoundary onRecover={recoverFromCrash} onReport={reportCrash} t={ui.theme}>
          <Box flexDirection="row" flexGrow={1}>
            {overlay.forecasts ? (
              <PerfPane id="forecasts">
                <ForecastsWorkspacePane />
              </PerfPane>
            ) : overlay.calibration ? (
              <PerfPane id="calibration">
                <CalibrationViewPane />
              </PerfPane>
            ) : overlay.alerts ? (
              <PerfPane id="alerts">
                <AlertsViewPane />
              </PerfPane>
            ) : overlay.help ? (
              <PerfPane id="help">
                <HelpViewPane />
              </PerfPane>
            ) : overlay.demoViz ? (
              <PerfPane id="demoViz">
                <DemoVizViewPane />
              </PerfPane>
            ) : overlay.hooks ? (
              <PerfPane id="hooks">
                <HooksViewPane />
              </PerfPane>
            ) : overlay.markets ? (
              <PerfPane id="markets">
                <MarketsViewPane
                  onAsk={question => {
                    patchOverlayState({ markets: false })
                    actions.draftCommand(question)
                  }}
                />
              </PerfPane>
            ) : overlay.news ? (
              <PerfPane id="news">
                <NewsViewPane />
              </PerfPane>
            ) : overlay.messaging ? (
              <PerfPane id="messaging">
                <MessagingViewPane />
              </PerfPane>
            ) : overlay.calendar ? (
              <PerfPane id="calendar">
                <CalendarViewPane />
              </PerfPane>
            ) : overlay.obsidian ? (
              <PerfPane id="docs">
                <DocsViewPane onDraft={actions.draftCommand} />
              </PerfPane>
            ) : overlay.onboard ? (
              <PerfPane id="onboard">
                <QuestionOnboardPane />
              </PerfPane>
            ) : (
              <PerfPane id="agents">
                <AgentsOverlayPane />
              </PerfPane>
            )}
          </Box>
          </ViewErrorBoundary>
          {/* The palette / cheat-sheet stacks LAST as an absolute overlay above
              the still-mounted view body (ModalOverlay recipe), so the view stays
              visible around it — identical to the Home paths below. */}
          {globalModal ? (
            <PerfPane id="globalChrome">
              <GlobalChromePane cols={composer.cols} onRun={actions.runCommand} rows={rows} />
            </PerfPane>
          ) : null}
          </>
        ) : showRail ? (
          // Home two-pane (wide terminals): a fixed conversations rail on the
          // left + the conversation on the right. The transcript ScrollBox stays
          // a DIRECT child of this flex-grow row — the proven structure that
          // scrolls cleanly. On an ACTIVE conversation the composer rides a
          // footer row below, indented past the rail (whose border continues full
          // height) so it sits under the conversation WITHOUT burying the
          // ScrollBox in an extra column. On the LANDING the composer lives INSIDE
          // the hero column (renderLanding), so no footer row renders there.
          <>
            <Box flexDirection="row" flexGrow={1} minHeight={0}>
              <ConversationsRailPane
                onNewChat={onRailNewChat}
                onSelect={actions.resumeById}
                scrollRef={transcript.railScrollRef}
              />
              {landing ? (
                renderLanding(contentComposer.cols, contentComposer, true)
              ) : (
                <PerfPane id="transcript">
                  <TranscriptPane
                    actions={actions}
                    composer={contentComposer}
                    decstbm={false}
                    progress={progress}
                    transcript={transcript}
                  />
                </PerfPane>
              )}
            </Box>
            {landing ? null : (
              <Box flexDirection="row" flexShrink={0}>
                <Box
                  borderBottom={false}
                  borderColor={ui.theme.color.border}
                  borderLeft={false}
                  borderRight
                  borderStyle="single"
                  borderTop={false}
                  flexShrink={0}
                  width={RAIL_WIDTH}
                />
                <Box flexDirection="column" flexGrow={1} minWidth={0}>
                  {renderPromptBar(contentComposer, true)}
                </Box>
              </Box>
            )}
            {/* The palette / cheat-sheet stacks LAST as an absolute overlay above
                the still-mounted home body (ModalOverlay recipe), so the landing
                Today panel + hints stay visible around it. */}
            {globalModal ? (
              <PerfPane id="globalChrome">
                <GlobalChromePane cols={composer.cols} onRun={actions.runCommand} rows={rows} />
              </PerfPane>
            ) : null}
          </>
        ) : (
          // Single-pane (rail hidden on narrow terminals): the proven full-width
          // layout — on an active conversation the transcript fills the row and
          // the prompt spans the bottom; on the LANDING the whole column
          // (hero → composer → Today → Schedule → tip → status) is renderLanding.
          <>
            <Box flexDirection="row" flexGrow={1} minHeight={0}>
              {landing ? (
                renderLanding(composer.cols, composer, false)
              ) : (
                <PerfPane id="transcript">
                  <TranscriptPane actions={actions} composer={composer} progress={progress} transcript={transcript} />
                </PerfPane>
              )}
            </Box>
            {landing ? null : renderPromptBar(composer, false)}
            {/* Palette / cheat-sheet stacks LAST above the still-mounted single-
                pane home body (ModalOverlay recipe). */}
            {globalModal ? (
              <PerfPane id="globalChrome">
                <GlobalChromePane cols={composer.cols} onRun={actions.runCommand} rows={rows} />
              </PerfPane>
            ) : null}
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
