import { describe, expect, it } from 'vitest'

import {
  forecastDashboardSections,
  forecastDeskActionStripItems,
  forecastDeskRailSections,
  forecastDeskStatusLabel
} from '../app/forecastPanel.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'

describe('forecast desk panel helpers', () => {
  it('promotes readiness gaps into triage actions for the persistent action strip', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        alerts: [
          {
            created_at: '2026-05-22T10:00:00Z',
            id: 'al_12345678',
            reason: 'watched_source_changed',
            recommended_action: '/forecast self-check --question fq_abc',
            scope_ref: 'fq_abc',
            scope_type: 'question',
            severity: 'warning'
          }
        ],
        evidence_status: {
          gaps: ['live_scored_forecasts', 'agent_protocol_scored_cases'],
          next_actions: [
            {
              action: 'Run prospective forecasts through the full loop: forecast resolve <id> --outcome <value> --source <url>; forecast score <id>; forecast postmortem <id>.',
              requirement_id: 'live_scored_forecasts'
            }
          ],
          verdict: 'insufficient_live_evidence'
        },
        open_alert_count: 1,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const sections = forecastDeskRailSections(response)
    const panelSections = forecastDashboardSections(response)
    const triageSection = sections.find(section => section.title === 'Triage')
    const railEvidenceSection = sections.find(section => section.title === 'Evidence')
    const panelEvidenceSection = panelSections.find(section => section.title === 'Evidence Status')

    expect(sections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          rows: expect.arrayContaining([
            ['al_12345 warning', 'watched_source_changed  /forecast self-check --question fq_abc']
          ]),
          title: 'Alerts'
        })
      ])
    )
    expect(triageSection?.rows?.find(row => row[0] === '/forecast readiness')?.[1]).toContain(
      'Run prospective forecasts through the full loop'
    )
    expect(railEvidenceSection?.rows?.find(row => row[0] === 'next live scored forecasts')?.[1]).toContain(
      'Run prospective forecasts through the full loop'
    )
    expect(panelEvidenceSection?.rows?.find(row => row[0] === 'next live scored forecasts')?.[1]).toContain(
      'Run prospective forecasts through the full loop'
    )
    expect(forecastDeskActionStripItems(sections)).toEqual([
      { command: '/alerts', detail: '1 open alert need source or resolution review' },
      expect.objectContaining({
        command: '/forecast readiness',
        detail: expect.stringContaining('Run prospective forecasts through the full loop')
      }),
      {
        command: '/forecast calibration --by-origin',
        detail: 'no eligible scores yet; resolve and score forecasts to build memory'
      }
    ])
  })

  it('deduplicates triage and next-command actions while preserving priority order', () => {
    expect(
      forecastDeskActionStripItems([
        {
          rows: [
            ['/forecast readiness', 'gaps remain'],
            ['/forecast self-check', 'desk sweep']
          ],
          title: 'Triage'
        },
        {
          items: ['/forecast self-check', '/forecast readiness', '/forecast backtest --benchmarks'],
          title: 'Next Commands'
        }
      ])
    ).toEqual([
      { command: '/forecast readiness', detail: 'gaps remain' },
      { command: '/forecast self-check', detail: 'desk sweep' },
      { command: '/forecast backtest --benchmarks', detail: '' }
    ])
  })

  it('includes fiscal and SEC adapters in evidence import shortcuts', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 0,
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const sections = forecastDashboardSections(response)
    const evidenceImports = sections.find(section => section.title === 'Evidence Imports')

    expect(evidenceImports?.items).toEqual(
      expect.arrayContaining([
        '/forecast import sec <cik> --question <id>',
        '/forecast import secfacts <cik>/<concept> --question <id>'
      ])
    )
  })

  it('surfaces aggregate assumption counts in desk status and triage', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        calibration: { count: 1 },
        open_alert_count: 0,
        open_assumption_count: 5,
        product: 'Superforecasting Agent',
        questions: [
          {
            id: 'fq_assumption111',
            open_assumption_count: 3,
            probability: 0.61,
            stale_assumption_count: 1,
            title: 'Will assumptions stay visible?'
          },
          {
            id: 'fq_assumption222',
            open_assumption_count: 2,
            probability: 0.48,
            stale_assumption_count: 0,
            title: 'Will active assumptions aggregate?'
          }
        ],
        review_queue: [],
        review_queue_count: 0,
        stale_assumption_count: 1
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(forecastDeskStatusLabel(response)).toContain('asm 5/1')
    expect(sections.find(section => section.title === 'Desk')?.rows).toContainEqual(['assumptions', '5/1'])
    expect(railSections.find(section => section.title === 'Book')?.rows).toContainEqual(['assumptions', '5/1'])
    expect(sections.find(section => section.title === 'Triage')?.rows).toContainEqual([
      '/forecast self-check',
      '1 stale assumption needs evidence or status review'
    ])
  })

  it('adds focused per-question actions from the review queue', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        calibration: { count: 3 },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [
          {
            as_of: '2026-05-22T00:00:00Z',
            close_time: '2026-06-01T00:00:00Z',
            id: 'fq_active123456',
            probability: 0.42,
            title: 'Will active question resolve yes?'
          }
        ],
        recent_backtests: [{ case_count: 10, id: 'bt_123', probability_sources: ['forecast-engine'] }],
        review_queue: [
          {
            as_of: '2026-05-20T00:00:00Z',
            id: 'fq_review123456',
            next_action: 'forecast research fq_review123456',
            priority: 1,
            probability: 0.55,
            reasons: ['stale'],
            title: 'Will review question resolve yes?'
          }
        ],
        review_queue_count: 1
      }
    }

    const sections = forecastDashboardSections(response)
    const focused = sections.find(section => section.title === 'Focused Actions')

    expect(focused?.rows).toEqual([
      ['/forecast show fq_review123456', 'load full ledger context for Will review question resolve yes?'],
      ['/forecast research fq_review123456', 'collect source notes and evidence without moving probability'],
      ['/forecast update fq_review123456 --probability <0-1>', 'append an explicit probability update with rationale'],
      [
        '/forecast resolve fq_review123456 --outcome <value> --source <url>',
        'record resolution when criteria are met'
      ]
    ])
    expect(forecastDeskActionStripItems(sections, 4)).toEqual([
      { command: '/review --stale', detail: '1 forecast queued for stale/close/evidence review' },
      { command: '/forecast show fq_review123456', detail: 'load full ledger context for Will review question resolve yes?' },
      { command: '/forecast research fq_review123456', detail: 'collect source notes and evidence without moving probability' },
      {
        command: '/forecast update fq_review123456 --probability <0-1>',
        detail: 'append an explicit probability update with rationale'
      }
    ])
  })
})
