import { useStore } from '@nanostores/react'
import { Box, Text } from '@superforecasting/ink'

import { useGateway } from '../app/gatewayContext.js'
import type { AppOverlaysProps } from '../app/interfaces.js'
import { $overlayState, patchOverlayState } from '../app/overlayStore.js'
import { pagerWindow } from '../app/pager.js'
import { $uiSessionId, $uiTheme } from '../app/uiStore.js'

import { FloatBox } from './appChrome.js'
import { MaskedPrompt } from './maskedPrompt.js'
import { ModalOverlay } from './modalOverlay.js'
import { ModelPicker } from './modelPicker.js'
import { ApprovalPrompt, ClarifyPrompt, ConfirmPrompt } from './prompts.js'
import { SessionPicker } from './sessionPicker.js'
import { SkillsHub } from './skillsHub.js'
import { ThemePicker } from './themePicker.js'

const COMPLETION_WINDOW = 16

// Color a generic pager line by role so dumps like `/api-key list` read as a
// table rather than a flat wall of text: column/section headers in accent,
// urls and "(not set)" markers muted, everything else in the body text color.
const pagerLineColor = (
  line: string,
  theme: { color: { accent: string; muted: string; text: string } }
): string => {
  const trimmed = line.trim()

  if (!trimmed) {
    return theme.color.muted
  }

  if (/\bENV VAR\b|\bPROVIDER\b|VALUE \/ DESCRIPTION/.test(line) || /^[A-Z][A-Z /_]{3,}$/.test(trimmed)) {
    return theme.color.accent
  }

  if (/^get:/.test(trimmed) || /https?:\/\//.test(trimmed) || /\(not set\)/.test(trimmed)) {
    return theme.color.muted
  }

  return theme.color.text
}

export function PromptZone({
  cols,
  onApprovalChoice,
  onClarifyAnswer,
  onSecretSubmit,
  onSudoSubmit
}: Pick<AppOverlaysProps, 'cols' | 'onApprovalChoice' | 'onClarifyAnswer' | 'onSecretSubmit' | 'onSudoSubmit'>) {
  const overlay = useStore($overlayState)
  const theme = useStore($uiTheme)

  if (overlay.approval) {
    return (
      <Box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
        <ApprovalPrompt onChoice={onApprovalChoice} req={overlay.approval} t={theme} />
      </Box>
    )
  }

  if (overlay.confirm) {
    const req = overlay.confirm

    const onConfirm = () => {
      patchOverlayState({ confirm: null })
      req.onConfirm()
    }

    const onCancel = () => patchOverlayState({ confirm: null })

    return (
      <Box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
        <ConfirmPrompt onCancel={onCancel} onConfirm={onConfirm} req={req} t={theme} />
      </Box>
    )
  }

  if (overlay.clarify) {
    return (
      <Box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
        <ClarifyPrompt
          cols={cols}
          onAnswer={onClarifyAnswer}
          onCancel={() => onClarifyAnswer('')}
          req={overlay.clarify}
          t={theme}
        />
      </Box>
    )
  }

  if (overlay.sudo) {
    return (
      <Box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
        <MaskedPrompt cols={cols} icon="🔐" label="sudo password required" onSubmit={onSudoSubmit} t={theme} />
      </Box>
    )
  }

  if (overlay.secret) {
    return (
      <Box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
        <MaskedPrompt
          cols={cols}
          icon="🔑"
          label={overlay.secret.prompt}
          onSubmit={onSecretSubmit}
          sub={`for ${overlay.secret.envVar}`}
          t={theme}
        />
      </Box>
    )
  }

  return null
}

export function FloatingOverlays({
  cols,
  compIdx,
  completions,
  onModelConnect,
  onModelSelect,
  onPickerSelect,
}: Pick<AppOverlaysProps, 'cols' | 'compIdx' | 'completions' | 'onModelConnect' | 'onModelSelect' | 'onPickerSelect'>) {
  const { gw } = useGateway()
  const overlay = useStore($overlayState)
  const sid = useStore($uiSessionId)
  const theme = useStore($uiTheme)

  const hasAny =
    overlay.modelPicker ||
    overlay.themePicker ||
    overlay.picker ||
    overlay.skillsHub ||
    completions.length

  if (!hasAny) {
    return null
  }

  // Fixed viewport centered on compIdx — previously the slice end was
  // compIdx + 8 so the dropdown grew from 8 rows to 16 as the user scrolled
  // down, bouncing the height on every keystroke.
  const viewportSize = Math.min(COMPLETION_WINDOW, completions.length)

  const start = Math.max(0, Math.min(compIdx - Math.floor(COMPLETION_WINDOW / 2), completions.length - viewportSize))

  return (
    <Box alignItems="flex-start" bottom="100%" flexDirection="column" left={0} position="absolute" right={0}>
      {overlay.picker && (
        <FloatBox color={theme.color.border}>
          <SessionPicker
            gw={gw}
            onCancel={() => patchOverlayState({ picker: false })}
            onSelect={onPickerSelect}
            t={theme}
          />
        </FloatBox>
      )}

      {overlay.modelPicker && (
        <FloatBox color={theme.color.border}>
          <ModelPicker
            gw={gw}
            onCancel={() => patchOverlayState({ modelPicker: false })}
            onConnect={onModelConnect}
            onSelect={onModelSelect}
            sessionId={sid}
            t={theme}
          />
        </FloatBox>
      )}

      {overlay.themePicker && (
        <FloatBox color={theme.color.border}>
          <ThemePicker gw={gw} onClose={() => patchOverlayState({ themePicker: false })} t={theme} />
        </FloatBox>
      )}

      {overlay.skillsHub && (
        <FloatBox color={theme.color.border}>
          <SkillsHub gw={gw} onClose={() => patchOverlayState({ skillsHub: false })} t={theme} />
        </FloatBox>
      )}

      {!!completions.length && (
        <FloatBox color={theme.color.primary}>
          <Box flexDirection="column" width={Math.max(28, cols - 6)}>
            {completions.slice(start, start + viewportSize).map((item, i) => {
              const active = start + i === compIdx

              return (
                <Box
                  backgroundColor={active ? theme.color.completionCurrentBg : theme.color.completionBg}
                  flexDirection="row"
                  key={`${start + i}:${item.text}:${item.display}:${item.meta ?? ''}`}
                  width="100%"
                >
                  <Text bold color={theme.color.label}>
                    {' '}
                    {item.display}
                  </Text>
                  {item.meta ? (
                    <Text
                      backgroundColor={active ? theme.color.completionMetaCurrentBg : theme.color.completionMetaBg}
                      color={theme.color.muted}
                    >
                      {' '}
                      {item.meta}
                    </Text>
                  ) : null}
                </Box>
              )
            })}
          </Box>
        </FloatBox>
      )}
    </Box>
  )
}


/** Output viewers belong to the viewport, not the composer's floating menu. */
export function OutputPager({ cols, rows, pageSize }: { cols: number; rows: number; pageSize: number }) {
  const state = useStore($overlayState)
  const theme = useStore($uiTheme)

  if (!state.pager) {return null}

  const pager = pagerWindow(state.pager, cols, pageSize)
  const end = Math.min(pager.offset + pageSize, pager.lines.length)

  return (
    <ModalOverlay
      cols={cols}
      footerHint={`↑↓ line · PgUp/PgDn page · g/G ends · Esc close (${end}/${pager.lines.length})`}
      maxHeight={Math.min(rows - 6, pager.lines.length + 7)}
      maxWidth={cols}
      rows={rows}
      t={theme}
      title={state.pager.title || 'Output'}
    >
      {pager.lines.slice(pager.offset, pager.offset + pageSize).map((line, i) => (
        <Text color={pagerLineColor(line, theme)} key={i}>{line || ' '}</Text>
      ))}
    </ModalOverlay>
  )
}
