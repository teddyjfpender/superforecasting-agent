import { Box, Text, useInput, useStdout } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { GatewayClient } from '../gatewayClient.js'
import { emptyAnswers, type OnboardAnswers, parseSourceLine, specFromAnswers } from '../lib/onboardSpec.js'
import { semantics } from '../lib/visualSemantics.js'
import type { Theme } from '../theme.js'

import { FooterChips } from './footerChips.js'

// Guided forecast-question onboarding: a step machine that builds a typed
// QuestionSpec and commits it through the gateway (forecast.onboard_commit),
// so a question is created with its watched sources, decision card, and
// onboarding toggles in one shot. The AI-curated version is the chat flow
// (propose_spec + clarify); this is the manual, form-driven surface.

type Step =
  | 'choices'
  | 'confirm'
  | 'criteria'
  | 'done'
  | 'evidence'
  | 'outcome'
  | 'owner'
  | 'panel'
  | 'source'
  | 'threshold'
  | 'title'
  | 'units'

interface Choice {
  label: string
  value: boolean | string
}

const OUTCOME_CHOICES: Choice[] = [
  { label: 'Yes / No (binary)', value: 'binary' },
  { label: 'Numeric value', value: 'numeric' },
  { label: 'Categorical buckets', value: 'categorical' }
]

const OWNER_CHOICES: Choice[] = [
  { label: 'Me', value: 'me' },
  { label: 'Team / desk', value: 'team' },
  { label: 'Track only (no owner)', value: '' }
]

const THRESHOLD_CHOICES: Choice[] = [
  { label: 'Act at ≥ 70%', value: '>=70% act' },
  { label: 'Act at ≥ 50%', value: '>=50% act' },
  { label: 'No action threshold', value: '' }
]

const EVIDENCE_CHOICES: Choice[] = [
  { label: 'Auto-fetch evidence each run', value: true },
  { label: "Manual only — I'll add evidence", value: false }
]

const PANEL_CHOICES: Choice[] = [
  { label: 'No panel (single model)', value: false },
  { label: 'Run a multi-model panel by default', value: true }
]

const CHOICE_STEPS: Partial<Record<Step, Choice[]>> = {
  evidence: EVIDENCE_CHOICES,
  outcome: OUTCOME_CHOICES,
  owner: OWNER_CHOICES,
  panel: PANEL_CHOICES,
  threshold: THRESHOLD_CHOICES
}

const STEP_TITLE: Record<Step, string> = {
  choices: 'Categorical buckets (comma-separated)',
  confirm: 'Review & create',
  criteria: 'How does it resolve? (measurable condition + source)',
  done: 'Created',
  evidence: 'May I fetch evidence autonomously?',
  outcome: 'How should it resolve?',
  owner: 'Who owns the decision this informs?',
  panel: 'Run a decomposition panel by default?',
  source: 'Watch a source (so re-runs can refresh) — blank to finish',
  threshold: 'At what probability does your action change?',
  title: 'What do you want to forecast?',
  units: 'Units (e.g. %, USD, count)'
}

// Order of steps; units/choices are conditional on the outcome type.
const nextStep = (step: Step, a: OnboardAnswers): Step => {
  const order: Step[] = ['title', 'criteria', 'outcome', 'units', 'choices', 'owner', 'threshold', 'evidence', 'source', 'panel', 'confirm']
  let i = order.indexOf(step) + 1

  while (i < order.length) {
    const s = order[i]

    if (s === 'units' && a.outcome !== 'numeric') {
      i += 1

      continue
    }

    if (s === 'choices' && a.outcome !== 'categorical') {
      i += 1

      continue
    }

    return s
  }

  return 'confirm'
}

interface QuestionOnboardModalProps {
  gw: GatewayClient
  onClose: () => void
  onDone?: (questionId: string) => void
  t: Theme
}

export function QuestionOnboardModal({ gw, onClose, onDone, t }: QuestionOnboardModalProps) {
  const { stdout } = useStdout()
  const cols = stdout?.columns ?? 80
  const sem = semantics(t)
  // Go inert while the Ctrl+K palette / `?` cheat-sheet stacks above the view.
  const globalModal = useStore($globalModal)

  const [step, setStep] = useState<Step>('title')
  const [answers, setAnswers] = useState<OnboardAnswers>(() => emptyAnswers())
  const [text, setText] = useState('')
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [resultId, setResultId] = useState('')

  const width = Math.min(80, Math.max(44, cols - 8))
  const choices = CHOICE_STEPS[step]

  const advance = (a: OnboardAnswers, from: Step) => {
    setAnswers(a)
    setError('')
    const to = nextStep(from, a)
    setStep(to)
    setText('')
    setSel(0)
  }

  const commit = () => {
    if (busy) {
      return
    }

    setBusy(true)
    setError('')
    const spec = specFromAnswers(answers)
    void gw
      .request<{ committed?: boolean; issues?: { field: string; message: string }[]; question_id?: string }>(
        'forecast.onboard_commit',
        { spec }
      )
      .then(res => {
        if (res?.committed && res.question_id) {
          setResultId(res.question_id)
          setStep('done')
          onDone?.(res.question_id)
        } else {
          setError((res?.issues ?? []).map(i => `${i.field}: ${i.message}`).join(' · ') || 'could not create the question')
        }

        setBusy(false)
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e))
        setBusy(false)
      })
  }

  // Commit the current text input for a text step, then advance.
  const submitText = () => {
    const value = text.trim()

    if (step === 'title') {
      if (!value) {
        return setError('a question is required')
      }

      return advance({ ...answers, title: value }, 'title')
    }

    if (step === 'criteria') {
      return advance({ ...answers, criteria: value }, 'criteria')
    }

    if (step === 'units') {
      return advance({ ...answers, units: value }, 'units')
    }

    if (step === 'choices') {
      return advance({ ...answers, choices: value.split(',').map(s => s.trim()).filter(Boolean) }, 'choices')
    }

    if (step === 'source') {
      // Blank → finish adding sources and move on. Otherwise add + stay.
      if (!value) {
        return advance(answers, 'source')
      }

      const parsed = parseSourceLine(value)

      if (parsed) {
        setAnswers(a => ({ ...a, sources: [...a.sources, parsed] }))
      }

      setText('')

      return
    }
  }

  const pickChoice = () => {
    const opt = choices?.[sel]

    if (!opt) {
      return
    }

    if (step === 'outcome') {
      return advance({ ...answers, outcome: opt.value as OnboardAnswers['outcome'] }, 'outcome')
    }

    if (step === 'owner') {
      return advance({ ...answers, owner: String(opt.value) }, 'owner')
    }

    if (step === 'threshold') {
      return advance({ ...answers, threshold: String(opt.value) }, 'threshold')
    }

    if (step === 'evidence') {
      return advance({ ...answers, evidence: Boolean(opt.value) }, 'evidence')
    }

    if (step === 'panel') {
      return advance({ ...answers, panel: Boolean(opt.value) }, 'panel')
    }
  }

  useInput((ch, key) => {
    if (key.escape) {
      return onClose()
    }

    if (step === 'done') {
      return onClose()
    }

    if (step === 'confirm') {
      if (key.return) {
        return commit()
      }

      return
    }

    if (choices) {
      if (key.upArrow) {
        return setSel(s => (s - 1 + choices.length) % choices.length)
      }

      if (key.downArrow) {
        return setSel(s => (s + 1) % choices.length)
      }

      if (key.return) {
        return pickChoice()
      }

      return
    }

    // text steps
    if (key.return) {
      return submitText()
    }

    if (key.backspace || key.delete) {
      return setText(s => s.slice(0, -1))
    }

    if (ch && !key.ctrl && !key.meta) {
      const printable = [...ch].filter(c => c >= ' ').join('')

      if (printable) {
        setText(s => s + printable)
      }
    }
  }, { isActive: !globalModal })

  return (
    <Box alignItems="stretch" flexDirection="column" flexGrow={1} paddingX={1} paddingY={1}>
      <Box flexShrink={0} marginBottom={1}>
        <Text bold color={t.color.primary}>
          NEW FORECAST
        </Text>
        <Text color={t.color.muted}>{'   guided question onboarding'}</Text>
      </Box>

      <Box alignItems="center" flexGrow={1} justifyContent="center">
        <Box flexDirection="column" width={width}>
          <Text bold color={t.color.text}>
            {STEP_TITLE[step]}
          </Text>

          {step === 'done' ? (
            <Box flexDirection="column" marginTop={1}>
              <Text color={sem.up}>{`Created forecast question ${resultId}.`}</Text>
              <Text color={t.color.muted}>{answers.sources.length ? `${answers.sources.length} watched source(s) attached — re-runs can refresh them.` : 'Tip: add watched sources later so re-runs can refresh.'}</Text>
            </Box>
          ) : step === 'confirm' ? (
            <Box flexDirection="column" marginTop={1}>
              <Text color={t.color.text}>{answers.title || '(untitled)'}</Text>
              <Text color={t.color.muted}>{`outcome ${answers.outcome}${answers.units ? ` (${answers.units})` : ''} · owner ${answers.owner || '—'} · ${answers.threshold || 'no threshold'}`}</Text>
              <Text color={t.color.muted}>{`evidence ${answers.evidence ? 'auto-fetch' : 'manual'} · panel ${answers.panel ? 'on' : 'off'} · ${answers.sources.length} source(s)`}</Text>
              {answers.sources.length ? (
                <Text color={t.color.label} wrap="truncate-end">{answers.sources.map(s => s.source).join(', ')}</Text>
              ) : null}
            </Box>
          ) : choices ? (
            <Box flexDirection="column" marginTop={1}>
              {choices.map((opt, i) => (
                <Text color={i === sel ? t.color.accent : t.color.text} key={opt.label}>
                  {i === sel ? '▸ ' : '  '}
                  {opt.label}
                  {i === 0 ? <Text color={t.color.muted}> (recommended)</Text> : null}
                </Text>
              ))}
            </Box>
          ) : (
            <Box marginTop={1}>
              <Text color={t.color.muted}>{'› '}</Text>
              <Text color={t.color.text}>{text}</Text>
              <Text color={t.color.text} inverse>
                {' '}
              </Text>
              {step === 'source' && answers.sources.length ? (
                <Text color={t.color.muted}>{`   added: ${answers.sources.length}`}</Text>
              ) : null}
            </Box>
          )}
        </Box>
      </Box>

      <Box flexDirection="column" flexShrink={0} marginTop={1}>
        <FooterChips
          chips={
            step === 'confirm'
              ? [{ k: '⏎', label: busy ? 'creating…' : 'Create' }, { k: '⎋', label: 'Cancel' }]
              : step === 'done'
                ? [{ k: '⏎', label: 'Close' }]
                : choices
                  ? [{ k: '↑↓', label: 'Choose' }, { k: '⏎', label: 'Select' }, { k: '⎋', label: 'Cancel' }]
                  : [{ k: '⏎', label: step === 'source' ? 'Add / next' : 'Next' }, { k: '⎋', label: 'Cancel' }]
          }
          t={t}
        />
        <Text color={t.color.muted} wrap="truncate-end">
          {error ? <Text color={t.color.error}>{error} · </Text> : null}
          {step === 'confirm'
            ? '⏎ create · Esc cancel'
            : step === 'done'
              ? 'Esc/⏎ close'
              : choices
                ? '↑↓ choose · ⏎ select · Esc cancel'
                : `type · ⏎ ${step === 'source' ? 'add a source (blank ⏎ to finish)' : 'next'} · Esc cancel`}
        </Text>
      </Box>
    </Box>
  )
}
