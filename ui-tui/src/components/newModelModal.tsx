import { Box, Text, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'
import { ModalOverlay } from './modalOverlay.js'

// New-model wizard (clone of questionOnboardModal's step machine): capture a
// quant question + key params, then hand them to the gateway via onSubmit.

export interface NewModelParams {
  analysis_type: string
  assumptions: string
  depth: string
  horizon: string
  question: string
  tickers: string[]
}

type Step = 'question' | 'asset' | 'analysis' | 'depth' | 'horizon' | 'assumptions' | 'confirm'

const ANALYSIS_CHOICES = ['regression', 'timeseries', 'simulation', 'scenario', 'exploratory']
const DEPTH_CHOICES = ['quick', 'standard', 'deep', 'ultra']

const DEPTH_BLURB: Record<string, string> = {
  deep: 'broad research + diagnostics + sensitivity',
  quick: 'fast focused read',
  standard: 'the model + supporting data + findings',
  ultra: 'exhaustive, multi-model, highly structured'
}

const ORDER: Step[] = ['question', 'asset', 'analysis', 'depth', 'horizon', 'assumptions', 'confirm']

export function NewModelModal({
  cols,
  initialAsset = '',
  onCancel,
  onSubmit,
  rows,
  t
}: {
  cols: number
  initialAsset?: string
  onCancel: () => void
  onSubmit: (params: NewModelParams) => void
  rows: number
  t: Theme
}) {
  // Go inert while the global palette / cheat-sheet stacks above this modal.
  const globalModal = useStore($globalModal)
  const [step, setStep] = useState<Step>('question')
  const [question, setQuestion] = useState('')
  const [asset, setAsset] = useState(initialAsset)
  const [analysis, setAnalysis] = useState('regression')
  const [depth, setDepth] = useState('standard')
  const [horizon, setHorizon] = useState('12mo')
  const [assumptions, setAssumptions] = useState('')
  const [text, setText] = useState('')
  const [sel, setSel] = useState(0)
  const [error, setError] = useState('')
  const [blink, setBlink] = useState(true)

  // Blinking block cursor (the modal is self-contained, so it owns its own tick).
  useEffect(() => {
    const id = setInterval(() => setBlink(b => !b), 500)
    return () => clearInterval(id)
  }, [])

  // Mirror ModalOverlay's box width so the field widths line up with the overlay.
  const narrow = cols < 100
  const modalW = narrow ? Math.max(40, cols - 2) : Math.max(48, Math.min(cols - 6, 100))

  const isChoice = step === 'analysis' || step === 'depth'
  const choices = step === 'analysis' ? ANALYSIS_CHOICES : step === 'depth' ? DEPTH_CHOICES : []

  const next = (from: Step): Step => ORDER[Math.min(ORDER.length - 1, ORDER.indexOf(from) + 1)]!

  const advanceText = () => {
    const value = text.trim()

    if (step === 'question') {
      if (!value) {
        return setError('a question is required')
      }

      setQuestion(value)
    } else if (step === 'asset') {
      setAsset(value)
    } else if (step === 'horizon') {
      setHorizon(value || '12mo')
    } else if (step === 'assumptions') {
      setAssumptions(value)
    }

    setError('')
    setText(step === 'asset' && !value ? '' : '')
    // seed the next text field where helpful
    const to = next(step)

    if (to === 'horizon') {
      setText(horizon)
    } else if (to === 'asset') {
      setText(asset)
    } else {
      setText('')
    }

    setSel(0)
    setStep(to)
  }

  const submit = () => {
    onSubmit({
      analysis_type: analysis,
      assumptions,
      depth,
      horizon,
      question,
      tickers: asset
        .split(/[,\s]+/)
        .map(s => s.trim())
        .filter(Boolean)
    })
  }

  useInput((ch, key) => {
    if (key.escape) {
      return onCancel()
    }

    if (step === 'confirm') {
      if (key.return) {
        return submit()
      }

      return
    }

    if (isChoice) {
      if (key.upArrow || ch === 'k') {
        return setSel(s => (s - 1 + choices.length) % choices.length)
      }

      if (key.downArrow || ch === 'j') {
        return setSel(s => (s + 1) % choices.length)
      }

      if (key.return) {
        const pick = choices[sel]!

        if (step === 'analysis') {
          setAnalysis(pick)
        } else {
          setDepth(pick)
        }

        setSel(0)
        setText(next(step) === 'horizon' ? horizon : '')

        return setStep(next(step))
      }

      return
    }

    // text step
    if (key.return) {
      return advanceText()
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

  const STEP_PROMPT: Record<Step, string> = {
    analysis: 'Analysis type',
    assumptions: 'Assumptions or constraints (optional)',
    asset: 'Primary asset(s) / tickers (optional, comma-separated)',
    confirm: 'Review',
    depth: 'Research depth',
    horizon: 'Horizon (e.g. 12mo, 2030)',
    question: 'Your quant question'
  }

  // One wrapping Text so the cursor stays glued to the end of the (wrapping)
  // input — separate row-Box children mispositioned it and tore the layout. The
  // cursor blinks between an inverse block and a plain space (constant width, so
  // nothing jumps).
  const field = (placeholder: string) => (
    <Box marginTop={1} width={Math.max(20, modalW - 6)}>
      <Text wrap="wrap">
        <Text color={t.color.muted}>{'› '}</Text>
        <Text color={t.color.text}>{text}</Text>
        {blink ? (
          <Text color={t.color.primary} inverse>
            {' '}
          </Text>
        ) : (
          <Text>{' '}</Text>
        )}
        {!text ? <Text color={t.color.muted}>{placeholder}</Text> : null}
      </Text>
    </Box>
  )

  const chips: FooterChip[] = isChoice
    ? [{ k: '↑↓', label: 'Choose' }, { k: '⏎', label: 'Next' }, { k: 'Esc', label: 'Cancel' }]
    : step === 'confirm'
      ? [{ k: '⏎', label: 'Build model' }, { k: 'Esc', label: 'Cancel' }]
      : [{ k: '⏎', label: 'Next' }, { k: 'Esc', label: 'Cancel' }]

  return (
    <ModalOverlay cols={cols} maxHeight={24} maxWidth={100} rows={rows} t={t} title="NEW MARKET MODEL">
        <Box flexDirection="column" flexGrow={1}>
          <Text color={t.color.label}>{STEP_PROMPT[step]}</Text>

          {step === 'question' ? field('how has GPU compute-per-chip growth driven NVIDIA revenue…') : null}
          {step === 'asset' ? field('NVDA, AMD') : null}
          {step === 'horizon' ? field('12mo') : null}
          {step === 'assumptions' ? field('blank for none') : null}

          {isChoice ? (
            <Box flexDirection="column" marginTop={1}>
              {choices.map((c, i) => (
                <Text color={i === sel ? t.color.accent : t.color.text} key={c}>
                  {i === sel ? '▸ ' : '  '}
                  {c}
                  {step === 'depth' && DEPTH_BLURB[c] ? <Text color={t.color.muted}>{`  — ${DEPTH_BLURB[c]}`}</Text> : null}
                </Text>
              ))}
            </Box>
          ) : null}

          {step === 'confirm' ? (
            <Box flexDirection="column" marginTop={1}>
              <Text color={t.color.text} wrap="truncate-end">{`Question: ${question}`}</Text>
              {asset ? <Text color={t.color.muted}>{`Assets: ${asset}`}</Text> : null}
              <Text color={t.color.muted}>{`Analysis: ${analysis} · Depth: ${depth} · Horizon: ${horizon}`}</Text>
              {assumptions ? <Text color={t.color.muted} wrap="truncate-end">{`Assumptions: ${assumptions}`}</Text> : null}
              <Box marginTop={1}>
                <Text color={t.color.accent}>Press ⏎ to build (runs in the background — watch progress or keep working).</Text>
              </Box>
            </Box>
          ) : null}

          {error ? (
            <Box marginTop={1}>
              <Text color={t.color.error}>{error}</Text>
            </Box>
          ) : null}
        </Box>

        <FooterChips chips={chips} disabled={globalModal} t={t} />
    </ModalOverlay>
  )
}
