import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { getOverlayState, resetOverlayState } from '../app/overlayStore.js'
import { turnController } from '../app/turnController.js'
import { getTurnState, resetTurnState } from '../app/turnStore.js'
import { getUiState, patchUiState, resetUiState } from '../app/uiStore.js'
import { estimateTokensRough } from '../lib/text.js'
import type { Msg } from '../types.js'

const ref = <T>(current: T) => ({ current })

const buildCtx = (appended: Msg[]) =>
  ({
    composer: {
      dequeue: () => undefined,
      queueEditRef: ref<null | number>(null),
      sendQueued: vi.fn(),
      setInput: vi.fn()
    },
    gateway: {
      gw: { request: vi.fn() },
      rpc: vi.fn(async () => null)
    },
    session: {
      STARTUP_RESUME_ID: '',
      colsRef: ref(80),
      newSession: vi.fn(),
      resetSession: vi.fn(),
      resumeById: vi.fn(),
      setCatalog: vi.fn()
    },
    submission: {
      submitRef: { current: vi.fn() }
    },
    system: {
      bellOnComplete: false,
      sys: vi.fn()
    },
    transcript: {
      appendMessage: (msg: Msg) => appended.push(msg),
      panel: (title: string, sections: any[]) =>
        appended.push({ kind: 'panel', panelData: { sections, title }, role: 'system', text: '' }),
      setHistoryItems: vi.fn()
    },
    voice: {
      setProcessing: vi.fn(),
      setRecording: vi.fn(),
      setVoiceEnabled: vi.fn()
    }
  }) as any

describe('createGatewayEventHandler', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
    turnController.fullReset()
    patchUiState({ showReasoning: true })
  })

  it('archives incomplete todos into transcript flow at end of turn so they scroll up', () => {
    const appended: Msg[] = []

    const todos = [
      { content: 'Gather ingredients', id: 'prep', status: 'completed' },
      { content: 'Boil water', id: 'boil', status: 'in_progress' },
      { content: 'Make sauce', id: 'sauce', status: 'pending' }
    ]

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: {}, type: 'message.start' } as any)
    onEvent({ payload: { name: 'todo', todos, tool_id: 'todo-1' }, type: 'tool.start' } as any)
    expect(getTurnState().todos).toEqual(todos)

    onEvent({ payload: { text: 'Started a todo list.' }, type: 'message.complete' } as any)

    const trail = appended.find(msg => msg.kind === 'trail' && msg.todos?.length)
    const finalText = appended.find(msg => msg.role === 'assistant' && msg.text === 'Started a todo list.')

    expect(finalText).toBeDefined()
    expect(trail).toMatchObject({ kind: 'trail', role: 'system', todos, todoIncomplete: true })
    // Protocol archive must sit ABOVE the final assistant text so the panel
    // doesn't visibly jump across the final answer at end-of-turn.
    expect(appended.indexOf(trail!)).toBeLessThan(appended.indexOf(finalText!))
    expect(getTurnState().todos).toEqual([])
  })

  it('archives completed todos into transcript flow at end of turn', () => {
    const appended: Msg[] = []
    const todos = [{ content: 'Serve tiny latte', id: 'serve', status: 'completed' }]
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { name: 'todo', todos, tool_id: 'todo-1' }, type: 'tool.start' } as any)
    onEvent({ payload: { text: 'done' }, type: 'message.complete' } as any)

    expect(getTurnState().todos).toEqual([])
    expect(appended).toContainEqual({
      kind: 'trail',
      role: 'system',
      text: '',
      todoCollapsedByDefault: true,
      todos
    })
  })

  it('keeps the current todo list visible when the next message starts', () => {
    const appended: Msg[] = []
    const todos = [{ content: 'Boil water', id: 'boil', status: 'in_progress' }]

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { name: 'todo', todos, tool_id: 'todo-1' }, type: 'tool.start' } as any)
    expect(getTurnState().todos).toEqual(todos)

    onEvent({ payload: {}, type: 'message.start' } as any)

    expect(getTurnState().todos).toEqual(todos)
  })

  it('prints compaction progress status into the transcript', () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    const onEvent = createGatewayEventHandler(ctx)

    onEvent({
      payload: { kind: 'compressing', text: 'compressing 968 messages (~123,400 tok)…' },
      type: 'status.update'
    } as any)

    expect(ctx.system.sys).toHaveBeenCalledWith('compressing 968 messages (~123,400 tok)…')
  })

  it('keeps goal verdict text in transcript but shows a brief idle status (#goal statusbar)', () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    const onEvent = createGatewayEventHandler(ctx)
    const verdict = '✓ Goal achieved: long judge reason goes only in transcript, not merged with cwd label.'

    vi.useFakeTimers()
    try {
      onEvent({
        payload: { kind: 'goal', text: verdict },
        type: 'status.update'
      } as any)

      expect(ctx.system.sys).toHaveBeenCalledWith(verdict)
      expect(getUiState().status).toBe('✓ goal complete')

      vi.advanceTimersByTime(6001)
      expect(getUiState().status).toBe('ready')
    } finally {
      vi.useRealTimers()
    }
  })

  it('maps goal status.update prefixes to short status strings', () => {
    const ctx = buildCtx([])
    const onEvent = createGatewayEventHandler(ctx)

    onEvent({
      payload: { kind: 'goal', text: '↻ Continuing toward goal (1/10): reason' },
      type: 'status.update'
    } as any)
    expect(getUiState().status).toBe('↻ goal continuing')

    onEvent({
      payload: { kind: 'goal', text: '⏸ Goal paused — budget exhausted.' },
      type: 'status.update'
    } as any)
    expect(getUiState().status).toBe('⏸ goal paused')
  })

  it('surfaces self-improvement review summaries as a persistent system line', () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    const onEvent = createGatewayEventHandler(ctx)

    onEvent({
      payload: { text: "💾 Self-improvement review: Skill 'hermes-release' patched" },
      type: 'review.summary'
    } as any)

    expect(ctx.system.sys).toHaveBeenCalledWith(
      "💾 Self-improvement review: Skill 'hermes-release' patched"
    )
  })

  it('ignores review.summary events with empty or missing text', () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    const onEvent = createGatewayEventHandler(ctx)

    onEvent({ payload: { text: '' }, type: 'review.summary' } as any)
    onEvent({ payload: { text: '   ' }, type: 'review.summary' } as any)
    onEvent({ payload: undefined, type: 'review.summary' } as any)

    expect(ctx.system.sys).not.toHaveBeenCalled()
  })

  it('clears the visible todo list when the todo tool returns an empty list', () => {
    const appended: Msg[] = []
    const todos = [{ content: 'Boil water', id: 'boil', status: 'in_progress' }]
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { name: 'todo', todos, tool_id: 'todo-1' }, type: 'tool.start' } as any)
    expect(getTurnState().todos).toEqual(todos)

    onEvent({ payload: { name: 'todo', todos: [], tool_id: 'todo-1' }, type: 'tool.complete' } as any)

    expect(getTurnState().todos).toEqual([])
  })

  it('persists completed tool rows when message.complete lands immediately after tool.complete', () => {
    const appended: Msg[] = []

    turnController.reasoningText = 'mapped the page'
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { context: 'home page', name: 'search', tool_id: 'tool-1' },
      type: 'tool.start'
    } as any)
    onEvent({
      payload: { name: 'search', preview: 'hero cards' },
      type: 'tool.progress'
    } as any)
    onEvent({
      payload: { summary: 'done', tool_id: 'tool-1' },
      type: 'tool.complete'
    } as any)
    onEvent({
      payload: { text: 'final answer' },
      type: 'message.complete'
    } as any)

    expect(appended).toHaveLength(2)
    expect(appended[0]).toMatchObject({ kind: 'trail', role: 'system', text: '', thinking: 'mapped the page' })
    expect(appended[0]?.tools).toHaveLength(1)
    expect(appended[0]?.tools?.[0]).toContain('hero cards')
    expect(appended[0]?.toolTokens).toBeGreaterThan(0)
    expect(appended[1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('groups sequential completed tools into one trail when the turn completes', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { context: 'alpha', name: 'search_files', tool_id: 'tool-1' }, type: 'tool.start' } as any)
    onEvent({
      payload: { name: 'search_files', summary: 'first done', tool_id: 'tool-1' },
      type: 'tool.complete'
    } as any)
    onEvent({ payload: { context: 'beta', name: 'read_file', tool_id: 'tool-2' }, type: 'tool.start' } as any)
    onEvent({ payload: { name: 'read_file', summary: 'second done', tool_id: 'tool-2' }, type: 'tool.complete' } as any)

    expect(getTurnState().streamSegments.filter(msg => msg.kind === 'trail' && msg.tools?.length)).toHaveLength(1)
    expect(getTurnState().streamSegments[0]?.tools).toHaveLength(2)
    expect(getTurnState().streamPendingTools).toEqual([])

    onEvent({ payload: { text: '' }, type: 'message.complete' } as any)

    const toolTrails = appended.filter(msg => msg.kind === 'trail' && msg.tools?.length)
    expect(toolTrails).toHaveLength(1)
    expect(toolTrails[0]?.tools).toHaveLength(2)
    expect(toolTrails[0]?.tools?.[0]).toContain('Search Files')
    expect(toolTrails[0]?.tools?.[1]).toContain('Read File')
  })

  it('keeps tool tokens across handler recreation mid-turn', () => {
    const appended: Msg[] = []

    turnController.reasoningText = 'mapped the page'

    createGatewayEventHandler(buildCtx(appended))({
      payload: { context: 'home page', name: 'search', tool_id: 'tool-1' },
      type: 'tool.start'
    } as any)

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { name: 'search', preview: 'hero cards' },
      type: 'tool.progress'
    } as any)
    onEvent({
      payload: { summary: 'done', tool_id: 'tool-1' },
      type: 'tool.complete'
    } as any)
    onEvent({
      payload: { text: 'final answer' },
      type: 'message.complete'
    } as any)

    expect(appended).toHaveLength(2)
    expect(appended[0]?.tools).toHaveLength(1)
    expect(appended[0]?.toolTokens).toBeGreaterThan(0)
    expect(appended[1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('streams legacy thinking.delta into visible reasoning state', () => {
    vi.useFakeTimers()
    const appended: Msg[] = []
    const streamed = 'short streamed reasoning'

    createGatewayEventHandler(buildCtx(appended))({ payload: { text: streamed }, type: 'thinking.delta' } as any)
    vi.runOnlyPendingTimers()

    expect(getTurnState().reasoning).toBe(streamed)
    expect(getTurnState().reasoningActive).toBe(true)
    expect(getTurnState().reasoningTokens).toBe(estimateTokensRough(streamed))
    vi.useRealTimers()
  })

  it('preserves streamed reasoning as one completed thinking panel after segment flushes', () => {
    const appended: Msg[] = []
    const streamed = 'first reasoning chunk\nsecond reasoning chunk'

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { text: streamed }, type: 'reasoning.delta' } as any)
    onEvent({ payload: { text: 'Before edit.' }, type: 'message.delta' } as any)
    turnController.flushStreamingSegment()
    onEvent({ payload: { text: 'final answer' }, type: 'message.complete' } as any)

    expect(appended.map(msg => msg.thinking).filter(Boolean)).toEqual([streamed])
    expect(appended[appended.length - 1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('filters spinner/status-only reasoning noise from completed thinking', () => {
    const appended: Msg[] = []
    const streamed = 'P= sourcing...\nactual plan\nCAL calibrating...\nnext step'

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { text: streamed }, type: 'reasoning.delta' } as any)
    onEvent({ payload: { text: 'final answer' }, type: 'message.complete' } as any)

    expect(appended[0]?.thinking).toBe(streamed)
    expect(appended[0]?.text).toBe('')
    expect(appended[appended.length - 1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('ignores fallback reasoning.available when streamed reasoning already exists', () => {
    const appended: Msg[] = []
    const streamed = 'short streamed reasoning'
    const fallback = 'x'.repeat(400)

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { text: streamed }, type: 'reasoning.delta' } as any)
    onEvent({ payload: { text: fallback }, type: 'reasoning.available' } as any)
    onEvent({ payload: { text: 'final answer' }, type: 'message.complete' } as any)

    expect(appended).toHaveLength(2)
    expect(appended[0]?.thinking).toBe(streamed)
    expect(appended[0]?.thinkingTokens).toBe(estimateTokensRough(streamed))
    expect(appended[1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('uses message.complete reasoning when no streamed reasoning ref', () => {
    const appended: Msg[] = []
    const fromServer = 'recovered from last_reasoning'

    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { reasoning: fromServer, text: 'final answer' }, type: 'message.complete' } as any)

    expect(appended).toHaveLength(2)
    expect(appended[0]?.thinking).toBe(fromServer)
    expect(appended[0]?.thinkingTokens).toBe(estimateTokensRough(fromServer))
    expect(appended[1]).toMatchObject({ role: 'assistant', text: 'final answer' })
  })

  it('renders browser.progress events as system transcript lines as they stream in', () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    const handler = createGatewayEventHandler(ctx)

    handler({
      payload: { message: 'Chromium-family browser launched and listening on port 9222' },
      type: 'browser.progress'
    } as any)

    expect(ctx.system.sys).toHaveBeenCalledWith('Chromium-family browser launched and listening on port 9222')
  })

  it('annotates gateway.start_timeout with stderr tail lines so users can diagnose without /logs', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: {
        cwd: '/repo',
        python: '/opt/venv/bin/python',
        stderr_tail:
          '[startup] timed out\nModuleNotFoundError: No module named openai\nFileNotFoundError: ~/.hermes/config.yaml'
      },
      type: 'gateway.start_timeout'
    } as any)

    const messages = getTurnState().activity.map(a => a.text)

    expect(messages.some(m => m.includes('gateway startup timed out'))).toBe(true)
    expect(messages.some(m => m.includes('ModuleNotFoundError'))).toBe(true)
    expect(messages.some(m => m.includes('FileNotFoundError'))).toBe(true)
  })

  it('prefers raw text over Rich-rendered ANSI on message.complete (#16391)', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const raw = 'Forecast desk here.\n\nLine two.'
    // Rich-rendered ANSI (`final_response_markdown: render`) used to win,
    // which left visible escape codes in Ink output. Raw text must win.
    const rendered = '\u001b[33mForecast desk here.\u001b[0m\n\n\u001b[2mLine two.\u001b[0m'

    onEvent({ payload: { rendered, text: raw }, type: 'message.complete' } as any)

    const assistant = appended.find(msg => msg.role === 'assistant')
    expect(assistant?.text).toBe(raw)
    expect(assistant?.text).not.toContain('\u001b[')
  })

  it('falls back to payload.rendered when text is missing on message.complete', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const rendered = 'fallback when gateway omitted text'

    onEvent({ payload: { rendered }, type: 'message.complete' } as any)

    const assistant = appended.find(msg => msg.role === 'assistant')
    expect(assistant?.text).toBe(rendered)
  })

  it('always accumulates raw text in message.delta and ignores `rendered` (#16391)', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    // Stream of partial text deltas; each delta carries an incremental
    // Rich-ANSI fragment.  Pre-fix code would replace the whole bufRef
    // with the latest fragment, dropping prior text.
    onEvent({ payload: { rendered: '\u001b[33mFi\u001b[0m', text: 'Fi' }, type: 'message.delta' } as any)
    onEvent({ payload: { rendered: '\u001b[33mrst.\u001b[0m', text: 'rst.' }, type: 'message.delta' } as any)
    onEvent({ payload: { text: ' second.' }, type: 'message.delta' } as any)
    onEvent({ payload: {}, type: 'message.complete' } as any)

    const assistant = appended.find(msg => msg.role === 'assistant')
    expect(assistant?.text).toBe('First. second.')
  })

  it('anchors inline_diff as its own segment where the edit happened', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const diff = '\u001b[31m--- a/foo.ts\u001b[0m\n\u001b[32m+++ b/foo.ts\u001b[0m\n@@\n-old\n+new'
    const cleaned = '--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'
    const block = `\`\`\`diff\n${cleaned}\n\`\`\``

    // Narration → tool → tool-complete → more narration → message-complete.
    // The diff MUST land between the two narration segments, not tacked
    // onto the final one.
    onEvent({ payload: { text: 'Editing the file' }, type: 'message.delta' } as any)
    onEvent({ payload: { context: 'foo.ts', name: 'patch', tool_id: 'tool-1' }, type: 'tool.start' } as any)
    onEvent({ payload: { inline_diff: diff, summary: 'patched', tool_id: 'tool-1' }, type: 'tool.complete' } as any)

    // Diff is already committed to segmentMessages as its own segment.
    expect(appended).toHaveLength(0)
    expect(turnController.segmentMessages).toEqual([
      { role: 'assistant', text: 'Editing the file' },
      {
        kind: 'diff',
        role: 'assistant',
        text: block,
        tools: [expect.stringMatching(/^Patch\("foo\.ts"\)(?: \([^)]+\))? ✓$/)]
      }
    ])

    onEvent({ payload: { text: 'patch applied' }, type: 'message.complete' } as any)

    expect(appended).toHaveLength(4)
    expect(appended[0]?.text).toBe('Editing the file')
    expect(appended[1]).toMatchObject({ kind: 'diff', text: block })
    expect(appended[1]?.tools?.[0]).toContain('Patch')
    expect(appended[3]?.text).toBe('patch applied')
    expect(appended[3]?.text).not.toContain('```diff')
  })

  it('keeps full final responses from duplicating flushed pre-diff narration', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const diff = '--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'
    const block = `\`\`\`diff\n${diff}\n\`\`\``

    onEvent({ payload: { text: 'Before edit. ' }, type: 'message.delta' } as any)
    onEvent({ payload: { context: 'foo.ts', name: 'patch', tool_id: 'tool-1' }, type: 'tool.start' } as any)
    onEvent({ payload: { inline_diff: diff, summary: 'patched', tool_id: 'tool-1' }, type: 'tool.complete' } as any)
    onEvent({ payload: { text: 'After edit.' }, type: 'message.delta' } as any)
    onEvent({ payload: { text: 'Before edit. After edit.' }, type: 'message.complete' } as any)

    expect(appended.map(msg => msg.text.trim()).filter(Boolean)).toEqual(['Before edit.', block, 'After edit.'])
    expect(appended[1]?.tools?.[0]).toContain('Patch')
  })

  it('drops the diff segment when the final assistant text narrates the same diff', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const cleaned = '--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'
    const assistantText = `Done. Here's the inline diff:\n\n\`\`\`diff\n${cleaned}\n\`\`\``

    onEvent({ payload: { inline_diff: cleaned, summary: 'patched', tool_id: 'tool-1' }, type: 'tool.complete' } as any)
    onEvent({ payload: { text: assistantText }, type: 'message.complete' } as any)

    // Only the final message — diff-only segment dropped so we don't
    // render two stacked copies of the same patch.
    expect(appended).toHaveLength(1)
    expect(appended[0]?.text).toBe(assistantText)
    expect((appended[0]?.text.match(/```diff/g) ?? []).length).toBe(1)
  })

  it('strips the CLI "┊ review diff" header from inline diff segments', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const raw = '  \u001b[33m┊ review diff\u001b[0m\n--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'

    onEvent({ payload: { inline_diff: raw, summary: 'patched', tool_id: 'tool-1' }, type: 'tool.complete' } as any)
    onEvent({ payload: { text: 'done' }, type: 'message.complete' } as any)

    // Tool trail first, then diff segment (kind='diff'), then final narration.
    expect(appended).toHaveLength(2)
    expect(appended[0]?.kind).toBe('diff')
    expect(appended[0]?.text).not.toContain('┊ review diff')
    expect(appended[0]?.text).toContain('--- a/foo.ts')
    expect(appended[0]?.tools?.[0]).toContain('Tool')
    expect(appended[1]?.text).toBe('done')
  })

  it('drops the diff segment when assistant writes its own ```diff fence', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const inlineDiff = '--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'
    const assistantText = 'Done. Clean swap:\n\n```diff\n-old\n+new\n```'

    onEvent({
      payload: { inline_diff: inlineDiff, summary: 'patched', tool_id: 'tool-1' },
      type: 'tool.complete'
    } as any)
    onEvent({ payload: { text: assistantText }, type: 'message.complete' } as any)

    expect(appended).toHaveLength(1)
    expect(appended[0]?.text).toBe(assistantText)
    expect((appended[0]?.text.match(/```diff/g) ?? []).length).toBe(1)
  })

  it('keeps tool trail terse when inline_diff is present', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))
    const diff = '--- a/foo.ts\n+++ b/foo.ts\n@@\n-old\n+new'

    onEvent({
      payload: { inline_diff: diff, name: 'review_diff', summary: diff, tool_id: 'tool-1' },
      type: 'tool.complete'
    } as any)
    onEvent({ payload: { text: 'done' }, type: 'message.complete' } as any)

    // Tool row is now placed before the diff, so telemetry does not render
    // below the patch that came from that tool.
    expect(appended).toHaveLength(2)
    expect(appended[0]?.kind).toBe('diff')
    expect(appended[0]?.text).toContain('```diff')
    expect(appended[0]?.tools?.[0]).toContain('Review Diff')
    expect(appended[0]?.tools?.[0]).not.toContain('--- a/foo.ts')
    expect(appended[1]?.text).toBe('done')
    expect(appended[1]?.tools ?? []).toEqual([])
  })

  it('shows setup panel for missing provider startup error', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: {
        message:
          'agent init failed: No LLM provider configured. Run `superforecasting-agent model` to select a provider, or run `superforecasting-agent setup` for first-time configuration.'
      },
      type: 'error'
    } as any)

    expect(appended).toHaveLength(1)
    expect(appended[0]).toMatchObject({
      kind: 'panel',
      panelData: { title: 'Setup Required' },
      role: 'system'
    })
  })

  it('on gateway.ready with no STARTUP_RESUME_ID and auto_resume off, forges a new session', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = ''
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'config.get') {
        return { config: { display: { tui_auto_resume_recent: false } } }
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(newSession).toHaveBeenCalled())
    expect(resumeById).not.toHaveBeenCalled()
  })

  it('on gateway.ready renders the forecast desk panel before chat traffic', async () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)

    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'forecast.dashboard') {
        return {
          output: 'SUPERFORECASTING DESK\n\nACTIVE FORECASTS\nfq_1 0.63 needs update',
          summary: {
            active_count: 1,
            calibration: {
              count: 3,
              mean_brier: 0.12,
              mean_log_score: -0.42,
              mean_sharpness: 0.38,
              probability_movement_count: 2,
              mean_abs_probability_movement_before_close: 0.11,
              ensemble_component_contributions: [
                {
                  count: 3,
                  mean_contribution: 0.42,
                  mean_probability: 0.56,
                  mean_weight_share: 0.75,
                  name: 'market'
                },
                {
                  count: 3,
                  mean_contribution: 0.12,
                  mean_probability: 0.48,
                  mean_weight_share: 0.25,
                  name: 'base_rate'
                }
              ],
              question_type_breakdown: [
                {
                  brier_count: 3,
                  count: 3,
                  mean_brier: 0.12,
                  mean_log_score: -0.42,
                  mean_proper_score: 0.12,
                  question_type: 'binary',
                  score_rules: ['brier']
                }
              ]
            },
            learning: {
              active_lessons: 0,
              invalidated_lessons: 0,
              recent_lessons: [
                {
                  id: 'cl_fixture001',
                  lesson: 'Election forecasts should discount late poll herding.',
                  scope_ref: 'politics',
                  scope_type: 'domain',
                  source_postmortem_count: 1,
                  source_score_count: 1,
                  status: 'tentative'
                }
              ],
              tentative_lessons: 1,
              top_error_profiles: [
                {
                  domain: 'politics',
                  mean_brier: 0.18,
                  question_type: 'binary',
                  recurring_errors: ['overweighted_late_polls'],
                  sample_count: 6
                }
              ],
              total_lessons: 1
            },
            evidence_status: {
              backtests: {
                agent_protocol_scored_count: 0,
                distinct_dataset_count: 1,
                external_dataset_count: 1,
                external_source_family_count: 1,
                leakage_free_run_count: 1,
                positive_best_baseline_edge_run_count: 1
              },
              can_claim_live_superforecasting: false,
              gaps: ['live_scored_forecasts', 'agent_protocol_scored_cases'],
              score_counts: {
                backtest: 12,
                imported_baseline: 12,
                live: 3
              },
              verdict: 'insufficient_live_evidence'
            },
            open_alert_count: 1,
            product: 'Superforecasting Agent',
            questions: [
              {
                baseline_count: 2,
                close_time: '2026-11-03T00:00:00Z',
                confidence: 0.74,
                delta: 0.08,
                evidence_count: 4,
                id: 'fq_123456789abc',
                open_alert_count: 1,
                open_assumption_count: 2,
                probability: 0.63,
                as_of: '2026-05-01T00:00:00Z',
                stale_assumption_count: 0,
                title: 'Will X win the election?'
              }
            ],
            review_queue_count: 1,
            review_queue: [
              {
                as_of: '2026-05-01T00:00:00Z',
                id: 'fq_123456789abc',
                next_action: 'forecast research fq_123456789abc; forecast update fq_123456789abc --preview ...',
                priority: 4,
                probability: 0.63,
                reasons: ['review_due', 'last_update_7d_plus'],
                title: 'Will X win the election?'
              }
            ],
            recent_backtests: [
              {
                agent_edge: 0.02,
                agent_mean_brier: 0.08,
                best_baseline: 'market:fixture',
                best_baseline_brier: 0.1,
                case_count: 12,
                claim_status: {
                  can_claim_live_superforecasting: false,
                  message: 'Benchmark replay evidence only.',
                  verdict: 'benchmark_replay_only'
                },
                dataset: 'fixture-corpus',
                id: 'bt_fixture001',
                leakage_checks_passed: true,
                paired_agent_wins: 8,
                paired_baseline_wins: 3,
                probability_sources: ['forecast-engine'],
                paired_ties: 1
              }
            ]
          }
        }
      }

      if (method === 'config.get') {
        return { config: { display: { tui_auto_resume_recent: false } } }
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(appended.some(msg => msg.kind === 'panel')).toBe(true))
    expect(getUiState().forecastDeskStatus).toBe('desk 1 active / 1 alert / 1 review / cal 3 / 1 lesson / asm 2/0')
    expect(getUiState().forecastDeskRailSections).toEqual([
      {
        rows: [
          ['active', '1'],
          ['alerts', '1'],
          ['reviews', '1'],
          ['closing', '0'],
          ['assumptions', '2/0'],
          ['refs', '0/0'],
          ['scores', '3'],
          ['lessons', '1']
        ],
        title: 'Book'
      },
      {
        rows: [
          ['/alerts', '1 open alert need source or resolution review'],
          ['/review --stale', '1 forecast queued for stale/close/evidence review'],
          ['/forecast readiness', '2 evidence gaps blocking stronger benchmark claims']
        ],
        title: 'Triage'
      },
      {
        rows: [
          [
            '12345678 P=0.630 Δ=+0.080',
            '1 alert  as-of 2026-05-01  close 2026-11-03  conf 0.74  Will X win the election?'
          ]
        ],
        title: 'Watchlist'
      },
      {
        rows: [
          ['readiness', 'insufficient live evidence'],
          ['live/backtest', '3/12'],
          ['replay', 'agent 0 edge 1 sets 1 ext 1 fam 1'],
          ['gaps', 'live scored forecasts, agent protocol scored cases']
        ],
        title: 'Evidence'
      },
      {
        rows: [
          ['component market', 'n 3  contrib 0.420000  share 0.750000  p 0.560000'],
          ['component base_rate', 'n 3  contrib 0.120000  share 0.250000  p 0.480000']
        ],
        title: 'Ensemble'
      },
      {
        rows: [
          [
            'bt_fixture001',
            'src forecast-engine  agent 0.080000  edge +0.020  replay only'
          ]
        ],
        title: 'Backtests'
      }
    ])
    expect(appended[0]).toMatchObject({
      kind: 'panel',
      panelData: {
        sections: [
          {
            rows: [
              ['product', 'Superforecasting Agent'],
              ['active forecasts', '1'],
              ['open alerts', '1'],
              ['review queue', '1'],
              ['closing soon', '0'],
              ['assumptions', '2/0'],
              ['reference classes', '0/0'],
              ['calibration n', '3'],
              ['lessons', '1']
            ],
            title: 'Desk'
          },
          {
            rows: [
              [
                '12345678  P=0.630  Δ=+0.080',
                'as-of 2026-05-01  close 2026-11-03  conf 0.74  ev 4  base 2  refs 0/0  asm 2/0  1 alert  Will X win the election?'
              ]
            ],
            title: 'Active Forecasts'
          },
          {
            rows: [
              [
                '12345678  priority 4',
                'P=0.630  as-of 2026-05-01  close -  review_due, last_update_7d_plus  forecast research fq_123456789abc; forecast update fq_123456789…'
              ]
            ],
            title: 'Review Queue'
          },
          {
            rows: [
              ['eligible scores', '3'],
              ['mean brier', '0.120000'],
              ['mean log score', '-0.420000'],
              ['mean sharpness', '0.380000'],
              ['movement n', '2'],
              ['mean abs movement', '0.110000'],
              ['component market', 'n 3  contrib 0.420000  share 0.750000  p 0.560000'],
              ['component base_rate', 'n 3  contrib 0.120000  share 0.250000  p 0.480000'],
              ['type binary', 'n 3  brier_n 3  brier 0.120000  proper 0.120000']
            ],
            title: 'Calibration'
          },
          {
            rows: [
              ['lessons', 'active 0  tentative 1  invalidated 0'],
              ['politics:binary', 'n 6  brier 0.180000  overweighted_late_polls'],
              ['tentative domain:politics', 'Election forecasts should discount late poll herding.']
            ],
            title: 'Learning Memory'
          },
          {
            rows: [
              ['verdict', 'insufficient live evidence'],
              ['scores', 'live 3  backtest 12  baseline 12'],
              ['backtests', 'agent-protocol 0  leakage-free 1  edge 1  datasets 1  external 1  families 1'],
              ['gaps', 'live scored forecasts, agent protocol scored cases']
            ],
            title: 'Evidence Status'
          },
          {
            rows: [
              [
                'bt_fixture001',
                'cases 12  src forecast-engine  agent 0.080000  market:fixture=0.100000  edge +0.020  wins 8/3/1  claim replay only  leakage ok  fixture-corpus'
              ]
            ],
            title: 'Recent Backtests'
          },
          {
            rows: [
              ['/alerts', '1 open alert need source or resolution review'],
              ['/review --stale', '1 forecast queued for stale/close/evidence review'],
              ['/forecast readiness', '2 evidence gaps blocking stronger benchmark claims'],
              ['/forecast lesson list', '1 lesson awaiting review']
            ],
            title: 'Triage'
          },
          {
            rows: [
              [
                '/forecast show fq_123456789abc',
                'P=0.630  as-of 2026-05-01  close -  reasons review_due,last_update_…  load full ledger context for Will X win the election?'
              ],
              ['/forecast research fq_123456789abc', 'collect source notes and evidence without moving probability'],
              [
                '/forecast update fq_123456789abc --probability <0-1> --rationale <why>',
                'append an explicit probability update'
              ],
              [
                '/forecast base-rate fq_123456789abc --name <reference-class> --inclusion-criteria <criteria> --base-rate <p>',
                'add reference-class evidence before changing probability'
              ],
              [
                "/trend-model fq_123456789abc --series-json '[...]' --target-date <date>",
                'run a deterministic trend projection when time series matter'
              ],
              [
                '/forecast resolve fq_123456789abc --outcome <value> --resolution-source <url>',
                'record resolution when criteria are met'
              ]
            ],
            title: 'Focused Actions'
          },
          {
            items: [
              '/sources',
              '/forecast import gdelt "<query>" --question <id>',
              '/forecast import fivethirtyeight <dataset-or-url> --question <id>',
              '/forecast import owid <slug> --entity "<entity>" --question <id>',
              '/forecast import whogho <indicator-code> --country <ISO3> --question <id>',
              '/forecast import fema <state|disaster-number|query> --question <id>',
              '/forecast import eia <series-id-or-api-url> --question <id>',
              '/forecast import treasury <dataset-path-or-api-url> --question <id>',
              '/forecast import imf <indicator>/<country> --question <id>',
              '/forecast import census "<dataset-path?get=...&for=...>" --question <id>',
              '/forecast import socrata <domain>/<dataset-id> --question <id>',
              '/forecast import ckan <domain>/<query> --question <id>',
              '/forecast import stooq <symbol-or-csv-url> --question <id>',
              '/forecast import yahoo <symbol> --question <id>',
              '/forecast import coingecko <coin-id> --question <id>',
              '/forecast import sec <cik> --question <id>',
              '/forecast import secfacts <cik>/<concept> --question <id>',
              '/forecast import crossref "<query-or-DOI>" --question <id>',
              '/forecast import wikipediapageviews <project>/<article> --question <id>',
              '/forecast import githubrepo <owner/repo> --question <id>',
              '/forecast import githubissues <owner/repo> --question <id>',
              '/forecast import githubcommits <owner/repo> --question <id>',
              '/forecast import githubactions <owner/repo> --question <id>',
              '/forecast import pypi <package> --question <id>',
              '/forecast import npm <package> --question <id>',
              '/forecast import hackernews "<query>" --question <id>',
              '/forecast import reddit "<query>" --question <id>',
              '/forecast import bluesky "<query>" --question <id>',
              '/forecast import mastodon <tag-or-instance/tag> --question <id>',
              '/forecast import reliefweb "<query>" --question <id>',
              '/forecast import clinicaltrials <query-or-NCT-id> --question <id>',
              '/forecast import openfda <query-or-application-number> --question <id>',
              '/forecast import pubmed "<query-or-PMID>" --question <id>',
              '/forecast import openmeteo <lat,lon> --question <id>',
              '/forecast import airquality <lat,lon> --question <id>',
              '/forecast import weatherhistory <lat,lon> --start-date <date> --end-date <date> --question <id>',
              '/forecast import usgs "<query>" --question <id>',
              '/forecast import eonet "<query-or-category>" --question <id>',
              '/forecast import nws "<area-or-point-or-query>" --question <id>',
              '/forecast import nvd "<keyword-or-CVE>" --question <id>',
              '/forecast import cisakev "<keyword-or-CVE-or-all>" --question <id>',
              '/forecast import federalregister "<query>" --question <id>',
              '/forecast import courtlistener "<query>" --question <id>',
              '/forecast watch add --question <id> <adapter>:<source>'
            ],
            title: 'Evidence Imports'
          },
          {
            items: [
              '/forecast review --stale',
              '/forecast self-check',
              '/sources',
              "/trend-model <id> --series-json '[...]' --target-date <date>",
              '/forecast calibration --by-origin',
              '/forecast lesson list',
              '/forecast errors',
              '/forecast schedule run --due --auto-score --auto-postmortem',
              '/forecast performance --last 5',
              '/forecast readiness',
              '/forecast pilot-report',
              '/forecast pilot-cohort examples/forecasting/live-cohort.example.csv --dry-run --json',
              '/forecast pilot-bundle --include-export --output .pilot/tester-bundle.json',
              '/forecast pilot-aggregate .pilot/*-export.json --json',
              '/forecast backtest --benchmarks'
            ],
            title: 'Next Commands'
          }
        ],
        title: 'Forecast Desk'
      },
      role: 'system'
    })
  })

  it('refreshes forecast desk status without showing startup panel for explicit resume', async () => {
    const appended: Msg[] = []
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.STARTUP_RESUME_ID = 'explicit-session'
    ctx.session.resumeById = resumeById
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'forecast.dashboard') {
        return {
          output: 'should not render',
          summary: {
            active_count: 3,
            open_alert_count: 2,
            product: 'Superforecasting Agent',
            questions: [],
            review_queue_count: 1
          }
        }
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(resumeById).toHaveBeenCalledWith('explicit-session'))
    await vi.waitFor(() => expect(getUiState().forecastDeskStatus).toBe('desk 3 active / 2 alerts / 1 review'))
    expect(ctx.gateway.rpc).toHaveBeenCalledWith('forecast.dashboard', { limit: 8 })
    expect(appended).toEqual([])
  })

  it('on gateway.ready with auto_resume on and a recent session, resumes it', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = ''
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'config.get') {
        return { config: { display: { tui_auto_resume_recent: true } } }
      }

      if (method === 'session.most_recent') {
        return { session_id: 'sess-most-recent' }
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(resumeById).toHaveBeenCalledWith('sess-most-recent'))
    expect(newSession).not.toHaveBeenCalled()
  })

  it('on gateway.ready with auto_resume on but no eligible session, falls back to new', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = ''
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'config.get') {
        return { config: { display: { tui_auto_resume_recent: true } } }
      }

      if (method === 'session.most_recent') {
        return { session_id: null }
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(newSession).toHaveBeenCalled())
    expect(resumeById).not.toHaveBeenCalled()
  })

  it('on gateway.ready when config.get rejects, falls back to new session', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = ''
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'config.get') {
        throw new Error('gateway timeout')
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(newSession).toHaveBeenCalled())
    expect(resumeById).not.toHaveBeenCalled()
  })

  it('on gateway.ready when session.most_recent rejects, falls back to new session', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = ''
    ctx.gateway.rpc = vi.fn(async (method: string) => {
      if (method === 'config.get') {
        return { config: { display: { tui_auto_resume_recent: true } } }
      }

      if (method === 'session.most_recent') {
        throw new Error('db locked')
      }

      return null
    })

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(newSession).toHaveBeenCalled())
    expect(resumeById).not.toHaveBeenCalled()
  })

  it('on gateway.ready with STARTUP_RESUME_ID set, the env wins over config auto_resume', async () => {
    const appended: Msg[] = []
    const newSession = vi.fn()
    const resumeById = vi.fn()
    const ctx = buildCtx(appended)

    ctx.session.newSession = newSession
    ctx.session.resumeById = resumeById
    ctx.session.STARTUP_RESUME_ID = 'env-explicit'
    ctx.gateway.rpc = vi.fn(async () => ({
      config: { display: { tui_auto_resume_recent: true } }
    }))

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    await vi.waitFor(() => expect(resumeById).toHaveBeenCalledWith('env-explicit'))
    expect(newSession).not.toHaveBeenCalled()
  })

  it('keeps gateway noise informational and approval out of Activity', async () => {
    const appended: Msg[] = []
    const ctx = buildCtx(appended)
    ctx.gateway.rpc = vi.fn(async () => {
      throw new Error('cold start')
    })

    const onEvent = createGatewayEventHandler(ctx)

    onEvent({ payload: { line: 'Traceback: noisy but non-fatal' }, type: 'gateway.stderr' } as any)
    onEvent({ payload: { preview: 'bad framing' }, type: 'gateway.protocol_error' } as any)
    onEvent({
      payload: { command: 'rm -rf /tmp/nope', description: 'dangerous command' },
      type: 'approval.request'
    } as any)
    onEvent({ payload: {}, type: 'gateway.ready' } as any)

    await Promise.resolve()
    await Promise.resolve()

    expect(getOverlayState().approval).toMatchObject({ description: 'dangerous command' })
    expect(getTurnState().activity).toMatchObject([
      { text: 'Traceback: noisy but non-fatal', tone: 'info' },
      { text: 'protocol noise detected · /logs to inspect', tone: 'info' },
      { text: 'protocol noise: bad framing', tone: 'info' },
      { text: 'command catalog unavailable: cold start', tone: 'info' }
    ])
  })

  it('still surfaces terminal turn failures as errors', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({ payload: { message: 'boom' }, type: 'error' } as any)

    expect(getTurnState().activity).toMatchObject([{ text: 'boom', tone: 'error' }])
  })

  it('accepts timeout/error subagent terminal statuses and ignores stale live events', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { goal: 'timeout child', subagent_id: 'sa-timeout', task_index: 0 },
      type: 'subagent.start'
    } as any)
    onEvent({
      payload: { goal: 'timeout child', status: 'timeout', subagent_id: 'sa-timeout', task_index: 0 },
      type: 'subagent.complete'
    } as any)

    expect(getTurnState().subagents.find(s => s.id === 'sa-timeout')?.status).toBe('timeout')

    // Late start/spawn updates must not clobber terminal timeout/error states.
    onEvent({
      payload: { goal: 'timeout child', subagent_id: 'sa-timeout', task_index: 0 },
      type: 'subagent.start'
    } as any)
    onEvent({
      payload: { goal: 'timeout child', subagent_id: 'sa-timeout', task_index: 0 },
      type: 'subagent.spawn_requested'
    } as any)

    expect(getTurnState().subagents.find(s => s.id === 'sa-timeout')?.status).toBe('timeout')

    onEvent({
      payload: { goal: 'error child', subagent_id: 'sa-error', task_index: 1 },
      type: 'subagent.start'
    } as any)
    onEvent({
      payload: { goal: 'error child', status: 'error', subagent_id: 'sa-error', task_index: 1 },
      type: 'subagent.complete'
    } as any)

    expect(getTurnState().subagents.find(s => s.id === 'sa-error')?.status).toBe('error')
  })

  it('normalizes unknown subagent.complete statuses to completed', () => {
    const appended: Msg[] = []
    const onEvent = createGatewayEventHandler(buildCtx(appended))

    onEvent({
      payload: { goal: 'weird child', subagent_id: 'sa-weird', task_index: 2 },
      type: 'subagent.start'
    } as any)
    onEvent({
      payload: { goal: 'weird child', status: 'mystery_status', subagent_id: 'sa-weird', task_index: 2 },
      type: 'subagent.complete'
    } as any)

    expect(getTurnState().subagents.find(s => s.id === 'sa-weird')?.status).toBe('completed')
  })

  it('drops stale reasoning/tool/todos events after ctrl-c until the next message starts', () => {
    // Repro for the discord report: ctrl-c interrupts, but late reasoning/tool
    // events from the still-winding-down agent loop kept populating the UI for
    // ~1s, making it look like the interrupt had been ignored.
    //
    // Fake timers because `interruptTurn` schedules a real setTimeout for
    // its cooldown — without flushing it inside this test, the timeout
    // can fire later and mutate uiStore/turnState during unrelated tests
    // (cross-file flake).
    vi.useFakeTimers()

    try {
      const appended: Msg[] = []
      const ctx = buildCtx(appended)
      ctx.gateway.gw.request = vi.fn(async () => ({ status: 'interrupted' }))
      const onEvent = createGatewayEventHandler(ctx)

      patchUiState({ sid: 'sess-1' })
      onEvent({ payload: {}, type: 'message.start' } as any)
      onEvent({
        payload: {
          context: 'pre',
          name: 'search',
          todos: [{ content: 'pre-interrupt', id: 'todo-1', status: 'pending' }],
          tool_id: 't-1'
        },
        type: 'tool.start'
      } as any)

      // Pre-interrupt todos should land in turn state.
      expect(getTurnState().todos).toEqual([{ content: 'pre-interrupt', id: 'todo-1', status: 'pending' }])

      turnController.interruptTurn({
        appendMessage: (msg: Msg) => appended.push(msg),
        gw: ctx.gateway.gw,
        sid: 'sess-1',
        sys: ctx.system.sys
      })

      onEvent({ payload: { text: 'still thinking…' }, type: 'reasoning.delta' } as any)
      // Post-interrupt tool.start with a todos payload — must NOT mutate todos.
      onEvent({
        payload: {
          context: 'post',
          name: 'browser',
          todos: [{ content: 'late ghost', id: 'todo-ghost', status: 'pending' }],
          tool_id: 't-2'
        },
        type: 'tool.start'
      } as any)
      // Late tool.generating must NOT push a 'drafting …' line into the trail.
      const trailBefore = getTurnState().turnTrail.length
      onEvent({ payload: { name: 'browser' }, type: 'tool.generating' } as any)
      expect(getTurnState().turnTrail.length).toBe(trailBefore)
      onEvent({ payload: { name: 'browser', preview: 'loading' }, type: 'tool.progress' } as any)
      onEvent({ payload: { summary: 'done', tool_id: 't-2' }, type: 'tool.complete' } as any)
      onEvent({ payload: { text: 'late chunk' }, type: 'message.delta' } as any)

      expect(getTurnState().tools).toEqual([])
      expect(turnController.reasoningText).toBe('')
      expect(turnController.bufRef).toBe('')
      expect(getTurnState().streamPendingTools).toEqual([])
      expect(getTurnState().streamSegments).toEqual([])
      // Stale post-interrupt todos must not have leaked through.
      // (This test does not assert that pre-interrupt todos are cleared —
      // current interrupt path leaves them visible until the next message.)
      expect(getTurnState().todos.find(t => t.content === 'late ghost')).toBeUndefined()

      onEvent({ payload: {}, type: 'message.start' } as any)
      onEvent({ payload: { text: 'fresh' }, type: 'reasoning.delta' } as any)

      expect(turnController.reasoningText).toBe('fresh')
    } finally {
      // Drain pending fake timers BEFORE restoring real timers so a mid-
      // test assertion failure can't leak the interrupt-cooldown setTimeout
      // across test files (the original Copilot concern).
      vi.runAllTimers()
      vi.useRealTimers()
    }
  })
})
