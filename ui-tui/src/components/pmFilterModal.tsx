import { Box, Text, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'

import { $globalModal } from '../app/overlayStore.js'
import { venueLabel } from '../lib/pmData.js'
import { parseMoneyShorthand, parseProbPercent, type PmFilter } from '../lib/pmRows.js'
import type { Theme } from '../theme.js'

import { type FooterChip, FooterChips } from './footerChips.js'
import { ModalOverlay } from './modalOverlay.js'

// The `f` structured filter for the Prediction section. A compact form over the
// fetched events: venue (←→), topic (text), min volume ($ shorthand), a prob
// range (min/max %), and an honest "hide sports" heuristic toggle. Tab/↑↓ move
// fields, Enter applies, Esc cancels. Keyboard fully trapped while open (the
// standing rule) — the parent early-returns from its useInput while a modal is up.

type FieldKind = 'text' | 'toggle' | 'venue'
type FieldKey = 'hideDead' | 'hideSports' | 'maxProb' | 'minProb' | 'minVolume' | 'topic' | 'venue'

const FIELDS: { key: FieldKey; kind: FieldKind; label: string; placeholder?: string }[] = [
  { key: 'venue', kind: 'venue', label: 'Venue' },
  { key: 'topic', kind: 'text', label: 'Topic', placeholder: 'category or title contains…' },
  { key: 'minVolume', kind: 'text', label: 'Min volume', placeholder: 'e.g. 1m, 500k, 250000' },
  { key: 'minProb', kind: 'text', label: 'Prob min %', placeholder: 'e.g. 5' },
  { key: 'maxProb', kind: 'text', label: 'Prob max %', placeholder: 'e.g. 95' },
  { key: 'hideSports', kind: 'toggle', label: 'Hide sports', placeholder: 'heuristic — leagues + sports categories' },
  { key: 'hideDead', kind: 'toggle', label: 'Hide dead/closed', placeholder: 'no estimate, $0 volume, or past close (default on)' }
]

const VENUE_CYCLE: PmFilter['venue'][] = ['all', 'polymarket', 'kalshi']

export function PmFilterModal({
  cols,
  filter,
  onApply,
  onCancel,
  rows,
  t
}: {
  cols: number
  filter: PmFilter
  onApply: (next: PmFilter) => void
  onCancel: () => void
  rows: number
  t: Theme
}) {
  const globalModal = useStore($globalModal)
  const [venue, setVenue] = useState<PmFilter['venue']>(filter.venue)
  const [topic, setTopic] = useState(filter.topic)
  const [minVolume, setMinVolume] = useState(filter.minVolume === null ? '' : String(filter.minVolume))
  const [minProb, setMinProb] = useState(filter.minProb === null ? '' : String(Math.round(filter.minProb * 100)))
  const [maxProb, setMaxProb] = useState(filter.maxProb === null ? '' : String(Math.round(filter.maxProb * 100)))
  const [hideSports, setHideSports] = useState(filter.hideSports)
  const [hideDead, setHideDead] = useState(filter.hideDead)
  const [sel, setSel] = useState(0)
  const [blink, setBlink] = useState(true)

  useEffect(() => {
    const id = setInterval(() => setBlink(b => !b), 500)

    return () => clearInterval(id)
  }, [])

  const values: Record<FieldKey, string> = { hideDead: '', hideSports: '', maxProb, minProb, minVolume, topic, venue }

  const toggles: Partial<Record<FieldKey, [boolean, (v: (b: boolean) => boolean) => void]>> = {
    hideDead: [hideDead, setHideDead],
    hideSports: [hideSports, setHideSports]
  }

  const setText = (key: FieldKey, updater: (s: string) => string) => {
    if (key === 'topic') {return setTopic(updater)}

    if (key === 'minVolume') {return setMinVolume(updater)}

    if (key === 'minProb') {return setMinProb(updater)}

    if (key === 'maxProb') {return setMaxProb(updater)}
  }

  const apply = () => {
    onApply({
      hideDead,
      hideSports,
      maxProb: parseProbPercent(maxProb),
      minProb: parseProbPercent(minProb),
      minVolume: parseMoneyShorthand(minVolume),
      topic: topic.trim(),
      venue
    })
  }

  const cycleVenue = (dir: number) =>
    setVenue(v => VENUE_CYCLE[(VENUE_CYCLE.indexOf(v) + dir + VENUE_CYCLE.length) % VENUE_CYCLE.length]!)

  useInput(
    (ch, key) => {
      if (key.escape) {
        return onCancel()
      }

      if (key.return) {
        return apply()
      }

      if (key.tab) {
        return setSel(s => (s + (key.shift ? FIELDS.length - 1 : 1)) % FIELDS.length)
      }

      if (key.upArrow) {
        return setSel(s => (s - 1 + FIELDS.length) % FIELDS.length)
      }

      if (key.downArrow) {
        return setSel(s => (s + 1) % FIELDS.length)
      }

      const field = FIELDS[sel]!

      if (field.kind === 'venue') {
        if (key.leftArrow) {return cycleVenue(-1)}

        if (key.rightArrow) {return cycleVenue(1)}

        return
      }

      if (field.kind === 'toggle') {
        if (ch === ' ' || key.leftArrow || key.rightArrow) {
          return toggles[field.key]?.[1]?.(v => !v)
        }

        return
      }

      // text field
      if (key.backspace || key.delete) {
        return setText(field.key, s => s.slice(0, -1))
      }

      if (ch && !key.ctrl && !key.meta) {
        const printable = [...ch].filter(c => c >= ' ').join('')

        if (printable) {
          setText(field.key, s => s + printable)
        }
      }
    },
    { isActive: !globalModal }
  )

  const chips: FooterChip[] = [
    { k: 'Tab/↑↓', label: 'Field' },
    { k: '←→', label: 'Venue/Toggle' },
    { k: '⏎', label: 'Apply' },
    { k: 'Esc', label: 'Cancel' }
  ]

  const cursor = blink ? (
    <Text color={t.color.primary} inverse>
      {' '}
    </Text>
  ) : (
    <Text>{' '}</Text>
  )

  return (
    <ModalOverlay cols={cols} footerHint="Filters compose with / search and the column sort." maxHeight={20} maxWidth={72} rows={rows} t={t} title="Filter prediction markets">
      <Box flexDirection="column" flexGrow={1}>
        {FIELDS.map((f, i) => {
          const on = i === sel

          return (
            <Box key={f.key} marginTop={i === 0 ? 0 : 1}>
              <Text color={on ? t.color.accent : t.color.muted}>{on ? '▸ ' : '  '}</Text>
              <Box width={12}>
                <Text bold={on} color={on ? t.color.accent : t.color.label}>
                  {f.label}
                </Text>
              </Box>
              {f.kind === 'venue' ? (
                <Text color={t.color.text}>
                  {'‹ '}
                  <Text bold color={t.color.primary}>
                    {venue === 'all' ? 'All' : venueLabel(venue)}
                  </Text>
                  {' ›'}
                </Text>
              ) : f.kind === 'toggle' ? (
                <Text color={toggles[f.key]?.[0] ? t.color.primary : t.color.muted}>
                  {toggles[f.key]?.[0] ? '[x] on' : '[ ] off'}
                  <Text color={t.color.muted}>{`  — ${f.placeholder}`}</Text>
                </Text>
              ) : (
                <Text wrap="truncate-end">
                  <Text color={t.color.text}>{values[f.key]}</Text>
                  {on ? cursor : null}
                  {!values[f.key] ? <Text color={t.color.muted}>{f.placeholder}</Text> : null}
                </Text>
              )}
            </Box>
          )
        })}
      </Box>
      <FooterChips chips={chips} disabled={globalModal} t={t} />
    </ModalOverlay>
  )
}
