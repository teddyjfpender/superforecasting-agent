import { AlternateScreen, Box, NoSelect, ScrollBox, type ScrollBoxHandle, Text } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { Fragment, memo, type RefObject, useEffect, useMemo, useRef } from 'react'

import { useGateway } from '../app/gatewayContext.js'
import { $homeFocus, setHomePane } from '../app/homeFocusStore.js'
import type { AppLayoutProps } from '../app/interfaces.js'
import { $isBlocked, $overlayState, patchOverlayState } from '../app/overlayStore.js'
import { $uiState } from '../app/uiStore.js'
import { INLINE_MODE, SHOW_FPS } from '../config/env.js'
import { PLACEHOLDER } from '../content/placeholders.js'
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
import { ForecastPulse, StatusRule, StickyPromptTracker, TranscriptScrollbar } from './appChrome.js'
import { FloatingOverlays, PromptZone } from './appOverlays.js'
import { HomeHero, Panel, SessionPanel } from './branding.js'
import { CalendarView } from './calendarView.js'
import { CalibrationView } from './calibrationView.js'
import { ConversationsRail } from './conversationsRail.js'
import { DemoVizView } from './demoVizView.js'
import { DocsView } from './docsView.js'
import { ForecastsWorkspace } from './forecastsWorkspace.js'
import { FpsOverlay } from './fpsOverlay.js'
import { HelpHint } from './helpHint.js'
import { HelpView } from './helpView.js'
import { HooksView } from './hooksView.js'
import { MarketsView } from './marketsView.js'
import { MessageLine } from './messageLine.js'
import { MessagingView } from './messagingView.js'
import { NavBar } from './navBar.js'
import { NewsView } from './newsView.js'
import { QuestionOnboardModal } from './questionOnboardModal.js'
import { QueuedMessages } from './queuedMessages.js'
import { LiveTodoPanel, StreamingAssistant } from './streamingAssistant.js'
import { TextInput, type TextInputMouseApi } from './textInput.js'

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
  status
}: Pick<AppLayoutProps, 'actions' | 'composer' | 'status'> & { confined?: boolean }) {
  const ui = useStore($uiState)
  const isBlocked = useStore($isBlocked)
  // When the conversations rail holds focus, the composer goes inactive so its
  // keystrokes/cursor don't compete with rail navigation.
  const railFocused = useStore($homeFocus).pane === 'rail'
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
                  focus={!railFocused}
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

const CalibrationViewPane = memo(function CalibrationViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <CalibrationView gw={gw} onClose={() => patchOverlayState({ calibration: false })} t={ui.theme} />
})

const AlertsViewPane = memo(function AlertsViewPane() {
  const { gw } = useGateway()
  const ui = useStore($uiState)

  return <AlertsView gw={gw} onClose={() => patchOverlayState({ alerts: false })} t={ui.theme} />
})

const HelpViewPane = memo(function HelpViewPane() {
  const ui = useStore($uiState)

  return <HelpView onClose={() => patchOverlayState({ help: false })} t={ui.theme} />
})

const DemoVizViewPane = memo(function DemoVizViewPane() {
  const ui = useStore($uiState)

  return <DemoVizView onClose={() => patchOverlayState({ demoViz: false })} t={ui.theme} />
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
  const ui = useStore($uiState)
  const homeFocus = useStore($homeFocus)

  return (
    <ConversationsRail
      currentSid={ui.sid}
      focused={homeFocus.pane === 'rail'}
      gw={gw}
      onExitFocus={() => setHomePane('conversation')}
      onNewChat={onNewChat}
      onSelect={onSelect}
      refreshKey={ui.sid ?? ''}
      scrollRef={scrollRef}
      t={ui.theme}
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
  const renderPromptBar = (bar: typeof composer, confined: boolean) => (
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
        <ComposerPane actions={actions} composer={bar} confined={confined} status={status} />
      </PerfPane>

      {SHOW_FPS && (
        <Box flexShrink={0} justifyContent="flex-end" paddingRight={1}>
          <FpsOverlay t={ui.theme} />
        </Box>
      )}
    </>
  )

  // The centred Outrider hero (new-chat screen) plus any startup notices, sized
  // to `heroCols` (the right-pane width when the rail is shown, else full width).
  const renderHero = (heroCols: number) => (
    <Box flexDirection="column" flexGrow={1} minHeight={0} minWidth={0}>
      <Box flexGrow={1} />
      <HomeHero info={ui.info ?? undefined} maxCols={heroCols} t={ui.theme} />
      {landingNotices.length > 0 && (
        <NoSelect flexDirection="column" marginTop={1} paddingX={1}>
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
      <Box flexGrow={1} />
    </Box>
  )

  return (
    <Shell {...shellProps}>
      <Box flexDirection="column" flexGrow={1}>
        <PerfPane id="navbar">
          <NavBar />
        </PerfPane>

        {fullscreen ? (
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
        ) : showRail ? (
          // Home two-pane (wide terminals): a fixed conversations rail on the
          // left + the conversation on the right. The transcript ScrollBox stays
          // a DIRECT child of this flex-grow row — the proven structure that
          // scrolls cleanly. The composer rides a footer row below, indented past
          // the rail (whose border continues full height) so it sits under the
          // conversation WITHOUT burying the ScrollBox in an extra column (which
          // collapses its measured viewport and sticks scroll to the top/bottom).
          <>
            <Box flexDirection="row" flexGrow={1} minHeight={0}>
              <ConversationsRailPane
                onNewChat={() => actions.runCommand('/new')}
                onSelect={actions.resumeById}
                scrollRef={transcript.railScrollRef}
              />
              {landing ? (
                renderHero(contentComposer.cols)
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
          </>
        ) : (
          // Single-pane (rail hidden on narrow terminals): the proven full-width
          // layout — transcript (or hero) fills the row, prompt spans the bottom.
          <>
            <Box flexDirection="row" flexGrow={1} minHeight={0}>
              {landing ? (
                renderHero(composer.cols)
              ) : (
                <PerfPane id="transcript">
                  <TranscriptPane actions={actions} composer={composer} progress={progress} transcript={transcript} />
                </PerfPane>
              )}
            </Box>
            {renderPromptBar(composer, false)}
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
