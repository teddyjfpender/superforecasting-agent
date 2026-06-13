import { describe, expect, it } from 'vitest'

import {
  ensembleComponentRows
} from '../components/forecastsWorkspace.js'
import type { ForecastQuestionPacket, ForecastTailAudit } from '../gatewayTypes.js'
import {
  looksLikeMarketSource,
  nullModelLine,
  outcomeSeverity,
  packetTailAudit,
  snapshotTailAudit,
  tailAuditChip,
  tailAuditFails,
  tailPct,
  unearnedHeadline,
  unearnedOutcomes
} from '../lib/forecastTail.js'

const audit = (overrides: Partial<ForecastTailAudit> = {}): ForecastTailAudit => ({
  issues: [],
  null_model: { agent_tail: 0.04, null_tail: 0.006, ratio: 6.7, within_tolerance: false },
  outcomes: [
    { classification: 'live', has_path: true, name: 'A', probability: 0.62, unearned: false },
    { classification: 'unpriced', has_path: false, name: 'Conway', probability: 0.017, unearned: true }
  ],
  passes: false,
  residual_cap: 0.05,
  threshold: 0.005,
  total_mass: 1,
  unearned_mass: 0.017,
  ...overrides
})

describe('forecastTail helpers', () => {
  it('treats an audit as failing when it did not pass or unearned mass clears the threshold', () => {
    expect(tailAuditFails(audit())).toBe(true)
    expect(tailAuditFails(audit({ passes: true, unearned_mass: 0 }))).toBe(false)
    // passes omitted but unearned mass over threshold → still a finding.
    expect(tailAuditFails(audit({ passes: undefined, unearned_mass: 0.02 }))).toBe(true)
    expect(tailAuditFails(null)).toBe(false)
  })

  it('extracts only the unearned outcomes', () => {
    expect(unearnedOutcomes(audit()).map(o => o.name)).toEqual(['Conway'])
  })

  it('maps outcome classification onto severity', () => {
    expect(outcomeSeverity({ classification: 'live', unearned: false })).toBe('ok')
    expect(outcomeSeverity({ classification: 'unpriced', has_path: false, name: 'X', probability: 0.02, unearned: true })).toBe('error')
    expect(outcomeSeverity({ classification: 'remote_tail', unearned: false })).toBe('warn')
    expect(outcomeSeverity({ classification: 'residual', unearned: false })).toBe('muted')
  })

  it('formats the unearned-mass headline and null-model line', () => {
    expect(unearnedHeadline(audit())).toBe('unearned tail mass 1.7% (over 0.5%)')
    expect(unearnedHeadline(audit({ unearned_mass: 0 }))).toBeNull()
    expect(nullModelLine(audit())).toBe('no-path tail 4% vs simple-null 0.6% (6.7x)')
    expect(nullModelLine(audit({ null_model: null }))).toBeNull()
  })

  it('builds the FAIL/PASS chip with the lead offender', () => {
    expect(tailAuditChip(audit())).toBe('tail audit: FAIL — Conway 1.7% unpriced')
    expect(tailAuditChip(audit({ passes: true, unearned_mass: 0 }))).toBe('tail audit: PASS')
    expect(tailAuditChip(null)).toBeNull()
  })

  it('formats tail percentages with one decimal under 10%', () => {
    expect(tailPct(0.017)).toBe('1.7%')
    expect(tailPct(0.62)).toBe('62%')
    expect(tailPct(null)).toBe('—')
  })

  it('recognises market source slugs', () => {
    expect(looksLikeMarketSource('kalshi:tx-senate')).toBe(true)
    expect(looksLikeMarketSource('polymarket:x')).toBe(true)
    expect(looksLikeMarketSource('reference_class')).toBe(false)
    expect(looksLikeMarketSource(null)).toBe(false)
  })

  it('reads the audit off the current snapshot metadata, null when absent', () => {
    const packet: ForecastQuestionPacket = {
      forecast_history: [
        { as_of: '1', metadata: {} },
        { as_of: '2', metadata: { tail_audit: audit() } }
      ]
    }

    expect(snapshotTailAudit(packet.forecast_history?.[0])).toBeNull()
    expect(packetTailAudit(packet)?.unearned_mass).toBe(0.017)
    expect(packetTailAudit({ forecast_history: [] })).toBeNull()
  })

  it('parses ensemble component rows preserving source and weight (array + dict forms)', () => {
    const arrayForm: ForecastQuestionPacket = {
      forecast_history: [
        {
          as_of: '1',
          ensemble_components: {
            components: [
              { name: 'outside', probability: 0.5, source: 'reference_class', weight: 1 },
              { name: 'kalshi', probability: 0.58, source: 'kalshi:x', weight: 0.2 }
            ]
          }
        }
      ]
    }

    const rows = ensembleComponentRows(arrayForm)
    expect(rows).toHaveLength(2)
    expect(rows[1]).toMatchObject({ name: 'kalshi', source: 'kalshi:x', weight: 0.2 })

    const dictForm: ForecastQuestionPacket = {
      forecast_history: [
        { as_of: '1', ensemble_components: { market: { probability: 0.6, weight: 2 }, prior: 0.4 } }
      ]
    }

    const dictRows = ensembleComponentRows(dictForm)
    expect(dictRows.map(r => r.name).sort()).toEqual(['market', 'prior'])
    expect(ensembleComponentRows({ forecast_history: [] })).toEqual([])
  })
})
