import { Box, Text, useInput } from '@superforecasting/ink'
import { Component, type ReactNode } from 'react'

import type { Theme } from '../theme.js'

// A captured render crash, normalized to plain strings for display + reporting.
export type CrashReport = { message: string; stack: string }

const truncate = (value: string, max: number): string =>
  value.length > max ? `${value.slice(0, Math.max(0, max - 1))}…` : value

// The recovery surface shown in place of a crashed view. Quality over a raw
// stack dump: explain what happened, that the desk recovered, and offer to file
// a GitHub issue (the agent writes it up). Keyboard: Y files, Esc/n dismisses.
function CrashRecoveryModal({
  onDismiss,
  onReport,
  report,
  t
}: {
  onDismiss: () => void
  onReport: () => void
  report: CrashReport
  t: Theme
}) {
  useInput((ch, key) => {
    const c = (ch || '').toLowerCase()

    if (c === 'y') {
      return onReport()
    }

    if (key.escape || c === 'n' || c === 'q') {
      return onDismiss()
    }
  })

  return (
    <Box borderColor={t.color.error} borderStyle="round" flexDirection="column" padding={1} width="100%">
      <Text bold color={t.color.error}>
        ⚠ This view hit an error — the desk caught it and recovered
      </Text>
      <Box marginTop={1}>
        <Text color={t.color.text} wrap="wrap">
          {truncate(report.message || 'Unknown error', 240)}
        </Text>
      </Box>
      {report.stack ? (
        <Box marginTop={1}>
          <Text color={t.color.muted} wrap="truncate-end">
            {truncate(report.stack.split('\n').slice(0, 4).join(' · '), 200)}
          </Text>
        </Box>
      ) : null}
      <Box marginTop={1}>
        <Text color={t.color.label}>
          Press <Text bold color={t.color.primary}>Y</Text> to load a ready-to-send GitHub-issue report into
          the chat (then press Enter — the agent files it), or <Text bold color={t.color.primary}>Esc</Text> to
          dismiss and keep working.
        </Text>
      </Box>
    </Box>
  )
}

// React error boundary around the rich overlay views. A render crash (e.g. a
// malformed config row) is contained here instead of taking down the whole TUI;
// the user gets a recovery modal + a one-key path to file a GitHub issue, and
// `onRecover` returns them to a safe screen so the crashed view can't re-throw.
export class ViewErrorBoundary extends Component<
  { children: ReactNode; onRecover: () => void; onReport: (report: CrashReport) => void; t: Theme },
  { report: CrashReport | null }
> {
  state: { report: CrashReport | null } = { report: null }

  static getDerivedStateFromError(error: unknown): { report: CrashReport } {
    const err = error as { message?: string; stack?: string } | null

    return {
      report: {
        message: String(err?.message ?? error ?? 'Unknown error'),
        stack: String(err?.stack ?? '')
      }
    }
  }

  private recover = () => {
    this.props.onRecover()
    this.setState({ report: null })
  }

  render() {
    const { report } = this.state

    if (report) {
      return (
        <CrashRecoveryModal
          onDismiss={this.recover}
          onReport={() => {
            this.props.onReport(report)
            this.recover()
          }}
          report={report}
          t={this.props.t}
        />
      )
    }

    return this.props.children
  }
}
