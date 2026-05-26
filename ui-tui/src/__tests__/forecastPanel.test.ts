import { describe, expect, it } from 'vitest'

import {
  forecastBookSections,
  forecastDashboardSections,
  forecastDeskActionStripItems,
  forecastDeskCompactItems,
  forecastDeskPrimaryActionItem,
  forecastDeskRailSections,
  forecastDeskStatusLabel,
  forecastFreshnessLabel,
  forecastLedgerViewSections,
  forecastQuestionDetailSections,
  forecastQuestionSearchSections,
  rankForecastQuestionMatches
} from '../app/forecastPanel.js'
import type { ForecastDashboardResponse } from '../gatewayTypes.js'

describe('forecast desk panel helpers', () => {
  it('renders a numbered forecast book with freshness and drill-down commands', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        open_alert_count: 1,
        product: 'Superforecasting Agent',
        questions: [
          {
            as_of: '2026-05-24T00:00:00Z',
            close_time: '2026-06-30T00:00:00Z',
            confidence: 0.62,
            delta: 0.08,
            evidence_count: 4,
            id: 'fq_inflation001',
            open_alert_count: 0,
            probability: 0.61,
            title: 'Will the CPI release exceed consensus?'
          },
          {
            as_of: '2026-04-01T00:00:00Z',
            close_time: '2026-09-30T00:00:00Z',
            confidence: 0.55,
            delta: -0.04,
            evidence_count: 2,
            id: 'fq_default001',
            open_alert_count: 1,
            probability: 0.21,
            title: 'Will company Y default?'
          }
        ],
        review_queue_count: 0
      }
    }

    const sections = forecastBookSections(response, new Date('2026-05-26T00:00:00Z'))

    expect(forecastFreshnessLabel('2026-05-26T00:00:00Z', new Date('2026-05-26T12:00:00Z'))).toBe('fresh today')
    expect(sections.find(section => section.title === 'Forecast Questions')?.rows).toEqual([
      [
        '1. P=0.610 Δ=+0.080',
        '2d old  as-of 2026-05-24  close 2026-06-30  conf 0.62  ev 4  active  Will the CPI release exceed consensus?',
        '/questions 1'
      ],
      [
        '2. P=0.210 Δ=-0.040',
        '1mo old  as-of 2026-04-01  close 2026-09-30  conf 0.55  ev 2  1 alert  Will company Y default?',
        '/questions 2'
      ]
    ])
    expect(sections.find(section => section.title === 'Drill Down')?.rows?.[0]).toEqual([
      '/questions 1',
      'open full details for Will the CPI release exceed consensus?'
    ])
  })

  it('searches forecast questions by topic-like words and offers id-free edit shortcuts', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [
          {
            as_of: '2026-05-24T00:00:00Z',
            close_time: '2026-06-30T00:00:00Z',
            confidence: 0.62,
            delta: 0.08,
            domain: 'macro',
            evidence_count: 4,
            id: 'fq_inflation001',
            probability: 0.61,
            title: 'Will the CPI release exceed consensus?',
            topics: ['inflation', 'energy']
          },
          {
            as_of: '2026-04-01T00:00:00Z',
            close_time: '2026-09-30T00:00:00Z',
            domain: 'credit',
            id: 'fq_default001',
            probability: 0.21,
            title: 'Will company Y default?'
          }
        ],
        review_queue: [
          {
            close_time: '2026-07-01T00:00:00Z',
            domain: 'macro',
            id: 'fq_review_energy',
            probability: 0.48,
            title: 'Will energy prices move inflation forecasts?'
          }
        ],
        review_queue_count: 1
      }
    }

    const matches = rankForecastQuestionMatches(response, 'inflation energy')
    const sections = forecastQuestionSearchSections(response, 'inflation energy', new Date('2026-05-26T00:00:00Z'))

    expect(matches.map(match => match.row.id)).toEqual(['fq_inflation001', 'fq_review_energy'])
    expect(sections.find(section => section.title === 'Matches')?.rows?.[0]?.[0]).toBe('1. inflatio  P=0.610  Δ=+0.080')
    expect(sections.find(section => section.title === 'Matches')?.rows?.[0]?.[1]).toContain(
      '2d old  close 2026-06-30  conf 0.62  ev 4  active  Will the CPI release exceed consensus?'
    )
    expect(sections.find(section => section.title === 'Matches')?.rows?.[0]?.[2]).toBe('/questions fq_inflation001')
    expect(sections.find(section => section.title === 'Top Match Shortcuts')?.rows).toEqual([
      ['/questions fq_inflation001', 'open full ledger context for Will the CPI release exceed consensus?'],
      ['/evidence-for fq_inflation001 -- <note>', 'append a timestamped evidence note without copying the id'],
      [
        '/update-for fq_inflation001 -- --probability <0-1> --rationale <why>',
        'append an explicit probability update'
      ],
      ['/sources --question fq_inflation001', 'plan source coverage for this question']
    ])
  })

  it('treats zero probability as a real forecast value', () => {
    const sections = forecastBookSections(
      {
        summary: {
          active_count: 1,
          open_alert_count: 0,
          product: 'Superforecasting Agent',
          questions: [
            {
              as_of: '2026-05-26T00:00:00Z',
              close_time: '2026-06-30T00:00:00Z',
              id: 'fq_zero_case',
              probability: 0,
              status: 'active',
              title: 'Will the impossible event happen?'
            }
          ],
          review_queue_count: 0
        }
      },
      new Date('2026-05-26T00:00:00Z')
    )

    expect(sections.find(section => section.title === 'Forecast Questions')?.rows?.[0]?.[0]).toBe('1. P=0.000 Δ=-')
    expect(sections.find(section => section.title === 'Forecast Questions')?.rows?.[0]?.[1]).toContain(
      'active  Will the impossible event happen?'
    )
  })

  it('attaches drill-down commands to active forecast rows and rail watchlist rows', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        open_alert_count: 1,
        product: 'Superforecasting Agent',
        questions: [
          {
            as_of: '2026-05-24T00:00:00Z',
            close_time: '2026-06-30T00:00:00Z',
            confidence: 0.62,
            delta: 0.08,
            evidence_count: 4,
            id: 'fq_inflation001',
            open_alert_count: 1,
            probability: 0.61,
            title: 'Will the CPI release exceed consensus?'
          }
        ],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const activeRow = forecastDashboardSections(response).find(section => section.title === 'Active Forecasts')?.rows?.[0]
    const watchlistRow = forecastDeskRailSections(response).find(section => section.title === 'Watchlist')?.rows?.[0]

    expect(activeRow?.[0]).toContain('P=0.610')
    expect(activeRow?.[2]).toBe('/questions fq_inflation001')
    expect(watchlistRow?.[0]).toContain('inflatio P=0.610')
    expect(watchlistRow?.[2]).toBe('/questions fq_inflation001')
  })

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

  it('surfaces the forecast doctor gate across panel, rail, status, and actions', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        calibration: { count: 1 },
        doctor: {
          claim_live_superforecasting: false,
          doctor_status: 'needs_tester_pilot_artifacts',
          next_actions: [
            {
              action: 'Run due schedule rows with `forecast schedule run --due`.',
              requirement_id: 'scheduled_self_check_runs',
              source: 'pilot'
            }
          ],
          pilot_gap_count: 2,
          pilot_passed_checks: 7,
          pilot_status: 'collecting_pilot_evidence',
          pilot_total_checks: 9,
          readiness_gap_count: 3,
          readiness_verdict: 'insufficient_live_evidence',
          scheduled_review_run_count: 0,
          tester_handoff_ready: false
        },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        recent_backtests: [{ case_count: 4, id: 'bt_doctor', probability_sources: ['dataset'] }],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(forecastDeskStatusLabel(response)).toContain('doctor needs tester pilot artifacts')
    expect(sections.find(section => section.title === 'Doctor Gate')?.rows).toEqual(
      expect.arrayContaining([
        ['status', 'needs tester pilot artifacts'],
        ['pilot', '7/9 collecting pilot evidence'],
        ['readiness', 'insufficient live evidence  gaps 3'],
        ['claim live superiority', 'no'],
        [
          'next scheduled self check runs',
          'Run due schedule rows with `forecast schedule run --due`.'
        ]
      ])
    )
    expect(railSections.find(section => section.title === 'Doctor')?.rows).toEqual(
      expect.arrayContaining([
        ['status', 'needs tester pilot artifacts'],
        ['pilot', '7/9 collecting pilot evidence'],
        ['claim live', 'no']
      ])
    )
    expect(forecastDeskActionStripItems(railSections)[0]).toEqual({
      command: '/forecast doctor --json',
      detail: 'pilot 7/9; Run due schedule rows with `forecast schedule run --due`.'
    })
    expect(forecastDeskCompactItems(railSections)).toContainEqual({
      detail: 'needs tester pilot artifacts',
      label: 'doctor'
    })
  })

  it('makes learned-error profile reviews visible in triage and review rows', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        calibration: { count: 1 },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [
          {
            as_of: '2026-05-22T10:00:00Z',
            close_time: '2026-06-01T00:00:00Z',
            domain: 'macro',
            id: 'fq_learned',
            next_action: 'Review this active forecast against learned error patterns.',
            priority: 4,
            probability: 0.64,
            reasons: ['domain_error_profile_applies:dep_macro'],
            title: 'Will inflation stay above target?'
          }
        ],
        review_queue_count: 1
      }
    }

    const sections = forecastDeskRailSections(response)
    const panelSections = forecastDashboardSections(response)
    const triageSection = sections.find(section => section.title === 'Triage')
    const reviewSection = panelSections.find(section => section.title === 'Review Queue')

    expect(triageSection?.rows?.find(row => row[0] === '/review --stale')?.[1]).toContain(
      'learned error-profile review'
    )
    expect(reviewSection?.rows?.[0]?.[1]).toContain('learned error profile')
    expect(forecastDeskActionStripItems(sections)[0]).toEqual({
      command: '/review --stale',
      detail: '1 forecast queued by learned error-profile review'
    })
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
        '/forecast import fivethirtyeight <dataset-or-url> --question <id>',
        '/forecast import imf <indicator>/<country> --question <id>',
        '/forecast import bluesky "<query>" --question <id>',
        '/forecast import mastodon <tag-or-instance/tag> --question <id>',
        '/forecast import airquality <lat,lon> --question <id>',
        '/forecast import weatherhistory <lat,lon> --start-date <date> --end-date <date> --question <id>',
        '/forecast import sec <cik> --question <id>',
        '/forecast import secfacts <cik>/<concept> --question <id>'
      ])
    )
  })

  it('surfaces tester pilot handoff commands in next actions', () => {
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
    const nextCommands = sections.find(section => section.title === 'Next Commands')

    expect(nextCommands?.items).toEqual(
      expect.arrayContaining([
        '/forecast readiness',
        '/forecast lesson list',
        '/forecast errors',
        '/forecast autopilot status <id>',
        '/forecast autopilot enable <id> --source <adapter>:<source> --required-source <critical-adapter>:<source> --cadence 1d --mode propose',
        '/forecast autopilot history <id>',
        '/forecast schedule run --due --auto-score --auto-postmortem',
        '/forecast schedule history --json',
        '/forecast doctor',
        '/forecast pilot-report',
        '/forecast pilot-cohort examples/forecasting/live-cohort.example.csv --dry-run --json',
        '/forecast pilot-bundle --include-export --output .pilot/tester-bundle.json',
        '/forecast export all --format json --output .pilot/tester-export.json',
        '/forecast import packet .pilot/tester-export.json --conflict skip --json',
        '/forecast pilot-aggregate .pilot/*-export.json --json'
      ])
    )
  })

  it('surfaces scheduled self-check run history in panel and rail', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 0,
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [],
        review_queue_count: 0,
        scheduled_review_runs: [
          {
            alert_count: 3,
            id: 'srr_abcdef123456',
            learning_review_count: 2,
            next_run_at: '2026-05-25T09:00:00Z',
            postmortem_count: 1,
            scheduled_review_id: 'sr_macro123456',
            scope_ref: '{"domain":"macro","topic":"inflation"}',
            scope_type: 'domain_topic',
            score_count: 1
          }
        ]
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(sections.find(section => section.title === 'Scheduled Self-Checks')?.rows).toEqual([
      [
        'srr_abcd  alerts 3',
        'domain:macro/inflation  scores 1  postmortems 1  learning 2  next 2026-05-25'
      ]
    ])
    expect(railSections.find(section => section.title === 'Schedules')?.rows).toEqual([
      [
        'srr_abcd alerts 3',
        'domain:macro/inflation  scores 1  pm 1  learn 2  next 2026-05-25'
      ]
    ])
  })

  it('surfaces aggregate assumption counts in desk status and triage', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        calibration: { count: 1 },
        closing_soon_count: 1,
        open_alert_count: 0,
        open_assumption_count: 5,
        open_reference_class_count: 4,
        product: 'Superforecasting Agent',
        questions: [
          {
            id: 'fq_assumption111',
            open_assumption_count: 3,
            open_reference_class_count: 1,
            probability: 0.61,
            stale_assumption_count: 1,
            stale_reference_class_count: 1,
            title: 'Will assumptions stay visible?'
          },
          {
            id: 'fq_assumption222',
            open_assumption_count: 2,
            open_reference_class_count: 3,
            probability: 0.48,
            stale_assumption_count: 0,
            stale_reference_class_count: 1,
            title: 'Will active assumptions aggregate?'
          }
        ],
        review_queue: [],
        review_queue_count: 0,
        stale_assumption_count: 1,
        stale_reference_class_count: 2
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(forecastDeskStatusLabel(response)).toContain('asm 5/1')
    expect(forecastDeskStatusLabel(response)).toContain('refs 4/2')
    expect(forecastDeskStatusLabel(response)).toContain('1 closing forecast')
    expect(sections.find(section => section.title === 'Desk')?.rows).toContainEqual(['assumptions', '5/1'])
    expect(sections.find(section => section.title === 'Desk')?.rows).toContainEqual(['reference classes', '4/2'])
    expect(sections.find(section => section.title === 'Desk')?.rows).toContainEqual(['closing soon', '1'])
    expect(railSections.find(section => section.title === 'Book')?.rows).toContainEqual(['assumptions', '5/1'])
    expect(railSections.find(section => section.title === 'Book')?.rows).toContainEqual(['refs', '4/2'])
    expect(railSections.find(section => section.title === 'Book')?.rows).toContainEqual(['closing', '1'])
    expect(sections.find(section => section.title === 'Triage')?.rows).toContainEqual([
      '/review --stale',
      '1 forecast approaching or past close time'
    ])
    expect(sections.find(section => section.title === 'Triage')?.rows).toContainEqual([
      '/forecast self-check',
      '1 stale assumption needs evidence or status review'
    ])
    expect(sections.find(section => section.title === 'Triage')?.rows).toContainEqual([
      '/forecast self-check',
      '2 stale reference classes need base-rate or source review'
    ])
  })

  it('surfaces ensemble component contribution in calibration panels and rail', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 0,
        calibration: {
          count: 2,
          ensemble_component_contributions: [
            {
              count: 2,
              mean_contribution: 0.6,
              mean_probability: 0.8,
              mean_weight_share: 0.75,
              name: 'market'
            },
            {
              count: 2,
              mean_contribution: 0.15,
              mean_probability: 0.6,
              mean_weight_share: 0.25,
              name: 'base_rate'
            }
          ],
          question_type_breakdown: [
            {
              brier_count: 2,
              count: 2,
              mean_brier: 0.18,
              mean_proper_score: 0.18,
              question_type: 'binary',
              score_rules: ['brier']
            }
          ]
        },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(sections.find(section => section.title === 'Calibration')?.rows).toEqual(
      expect.arrayContaining([
        ['component market', 'n 2  contrib 0.600000  share 0.750000  p 0.800000'],
        ['component base_rate', 'n 2  contrib 0.150000  share 0.250000  p 0.600000'],
        ['type binary', 'n 2  brier_n 2  brier 0.180000  proper 0.180000']
      ])
    )
    expect(railSections.find(section => section.title === 'Ensemble')?.rows).toEqual([
      ['component market', 'n 2  contrib 0.600000  share 0.750000  p 0.800000'],
      ['component base_rate', 'n 2  contrib 0.150000  share 0.250000  p 0.600000']
    ])
  })

  it('surfaces resolved live performance against scored imported baselines', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 0,
        live_performance: {
          agent: {
            mean_brier: 0.0625,
            mean_log_score: -0.28
          },
          baselines: [
            {
              baseline_type: 'crowd',
              mean_brier: 0.16,
              mean_brier_improvement_vs_baseline: 0.0975,
              paired_agent_edge_ci95_high: 0.12,
              paired_agent_edge_ci95_low: 0.07,
              paired_agent_wins: 1,
              paired_baseline_wins: 0,
              paired_count: 1,
              paired_ties: 0,
              source: 'dashboard-crowd'
            }
          ],
          claim_status: {
            can_claim_live_superforecasting: false,
            message: 'Prospective evidence remains too small for a stronger claim.',
            verdict: 'live_comparison_evidence'
          },
          score_count: 1
        },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const sections = forecastDashboardSections(response)
    const railSections = forecastDeskRailSections(response)

    expect(sections.find(section => section.title === 'Live Performance')?.rows).toEqual([
      ['scores', 'live 1  agent brier 0.062500  baselines 1'],
      ['claim', 'live comparison evidence'],
      [
        'crowd:dashboard-crowd',
        'brier 0.160000  paired 1  edge +0.098  ci95 [+0.070,+0.120]  wins 1/0/0'
      ]
    ])
    expect(railSections.find(section => section.title === 'Live')?.rows).toEqual([
      ['scores', 'live 1 brier 0.062500 bases 1'],
      ['claim', 'live comparison evidence'],
      [
        'crowd:dashboard-crowd',
        'brier 0.160000 paired 1 edge +0.098 wins 1/0/0'
      ]
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
            close_time: '2026-05-31T00:00:00Z',
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
    const railSections = forecastDeskRailSections(response)
    const focused = sections.find(section => section.title === 'Focused Actions')
    const railFocused = railSections.find(section => section.title === 'Focused Actions')
    const review = sections.find(section => section.title === 'Review Queue')

    expect(focused?.rows).toEqual([
      [
        '/questions fq_review123456',
        'P=0.550  as-of 2026-05-20  close 2026-05-31  reasons stale  load full ledger context for Will review question resolve yes?'
      ],
      ['/sources --question fq_review123456', 'plan official data, RSS/news, markets, and watched searches'],
      ['/forecast research fq_review123456', 'collect source notes and evidence without moving probability'],
      ['/forecast update fq_review123456 --probability <0-1> --rationale <why>', 'append an explicit probability update'],
      [
        '/forecast base-rate fq_review123456 --name <reference-class> --inclusion-criteria <criteria> --base-rate <p>',
        'add reference-class evidence before changing probability'
      ],
      [
        "/trend-model fq_review123456 --series-json '[...]' --target-date <date>",
        'run a deterministic trend projection when time series matter'
      ],
      [
        '/forecast resolve fq_review123456 --outcome <value> --resolution-source <url>',
        'record resolution when criteria are met'
      ]
    ])
    expect(forecastDeskActionStripItems(sections, 4)).toEqual([
      { command: '/review --stale', detail: '1 forecast queued for stale/close/evidence review' },
      {
        command: '/questions fq_review123456',
        detail: 'P=0.550  as-of 2026-05-20  close 2026-05-31  reasons stale  load full ledger context for Will review question resolve yes?'
      },
      { command: '/sources --question fq_review123456', detail: 'plan official data, RSS/news, markets, and watched searches' },
      { command: '/forecast research fq_review123456', detail: 'collect source notes and evidence without moving probability' }
    ])
    expect(railFocused?.rows?.[0]).toEqual([
      '/questions fq_review123456',
      'P=0.550  as-of 2026-05-20  close 2026-05-31  reasons stale  load full ledger context for Will review question resolve yes?'
    ])
    expect(forecastDeskPrimaryActionItem(railSections)).toEqual({
      command: '/questions fq_review123456',
      detail: 'P=0.550  as-of 2026-05-20  close 2026-05-31  reasons stale  load full ledger context for Will review question resolve yes?'
    })
    expect(review?.rows?.[0]?.[1]).toContain('close 2026-05-31')
  })

  it('builds a compact desk brief for terminals without the forecast rail', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        calibration: { count: 4 },
        evidence_status: {
          gaps: ['live_scored_forecasts'],
          next_actions: [
            {
              action: 'Resolve and score live forecasts before making stronger benchmark claims.',
              requirement_id: 'live_scored_forecasts'
            }
          ],
          verdict: 'insufficient_live_evidence'
        },
        open_alert_count: 1,
        open_assumption_count: 3,
        product: 'Superforecasting Agent',
        questions: [
          {
            close_time: '2026-06-01T00:00:00Z',
            id: 'fq_watch123456',
            open_alert_count: 1,
            probability: 0.71,
            stale_assumption_count: 2,
            title: 'Will the watched forecast need review?'
          }
        ],
        review_queue: [
          {
            id: 'fq_review123456',
            probability: 0.62,
            priority: 1,
            reasons: ['stale'],
            title: 'Will review stay visible?'
          }
        ],
        review_queue_count: 1,
        stale_assumption_count: 2
      }
    }

    expect(forecastDeskCompactItems(forecastDeskRailSections(response))).toEqual([
      { detail: '2 active / 1 alerts / 1 reviews / asm 3/2', label: 'book' },
      { detail: '/alerts 1 open alert need source or resolution review', label: 'triage' },
      {
        detail: 'watch123 P=0.710 Δ=- 1 alert  as-of -  close 2026-06-01  conf -  Will the watched forecast need review?',
        label: 'watch'
      }
    ])
  })

  it('renders a structured forecast detail panel with state, evidence, history, and actions', () => {
    const sections = forecastQuestionDetailSections({
      packet: {
        assumptions: [{ id: 'as_energy', status: 'active', text: 'Gasoline prices remain material.' }],
        evidence: [
          {
            available_at: '2026-05-24T10:00:00Z',
            claim: 'Retail gasoline prices rose week over week.',
            claim_type: 'estimate',
            id: 'ev_gasoline',
            source_name: 'EIA',
            source_type: 'rss',
            stance: 'supports'
          }
        ],
        forecast_history: [
          {
            as_of: '2026-05-20T00:00:00Z',
            confidence: 0.52,
            forecast_id: 'fc_prior',
            forecast_origin: 'live',
            method: 'base_rate',
            probability_or_distribution: 0.55,
            rationale: 'Consensus roughly balanced.'
          },
          {
            as_of: '2026-05-24T00:00:00Z',
            confidence: 0.62,
            forecast_id: 'fc_current',
            forecast_origin: 'live',
            method: 'ensemble',
            probability_or_distribution: 0.61,
            rationale: 'Energy evidence moved the estimate higher.'
          }
        ],
        question: {
          close_time: '2026-06-30T00:00:00Z',
          domain: 'macro',
          id: 'fq_cpi',
          resolution_criteria: 'Official CPI release exceeds consensus.',
          status: 'active',
          title: 'Will the CPI release exceed consensus?',
          topics: ['inflation', 'energy']
        },
        reference_classes: [{ base_rate: 0.58, id: 'rc_cpi', name: 'Recent CPI surprises', status: 'active' }],
        watched_sources: [{ id: 'ws_eia' }]
      }
    })

    expect(sections.find(section => section.title === 'Current Forecast')?.rows).toContainEqual([
      'P(now)',
      '0.610'
    ])
    expect(sections.find(section => section.title === 'Current Forecast')?.rows).toContainEqual([
      'delta',
      '+0.060'
    ])
    expect(sections.find(section => section.title === 'Recent Evidence')?.rows?.[0]?.[1]).toContain(
      'Retail gasoline prices rose'
    )
    expect(sections.find(section => section.title === 'Actions')?.rows?.[0]).toEqual([
      '/evidence-for fq_cpi -- <note>',
      'append timestamped evidence; probability remains unchanged'
    ])
  })

  it('searches current forecasts across rationale and latest evidence context', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 2,
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [
          {
            domain: 'macro',
            id: 'fq_cpi',
            latest_evidence_claim: 'Retail gasoline prices rose week over week.',
            latest_rationale: 'Energy evidence moved the estimate higher.',
            probability: 0.61,
            title: 'Will the CPI release exceed consensus?',
            topics: ['inflation']
          },
          {
            domain: 'credit',
            id: 'fq_default',
            probability: 0.21,
            title: 'Will company Y default?'
          }
        ],
        review_queue_count: 0
      }
    }

    expect(rankForecastQuestionMatches(response, 'gasoline').map(match => match.row.id)).toEqual(['fq_cpi'])
    expect(rankForecastQuestionMatches(response, 'estimate higher').map(match => match.row.id)).toEqual(['fq_cpi'])
  })

  it('builds ledger view shortcuts and filtered state views', () => {
    const response: ForecastDashboardResponse = {
      summary: {
        active_count: 1,
        evidence_status: {
          gaps: ['live_scored_forecasts'],
          verdict: 'insufficient_live_evidence'
        },
        open_alert_count: 0,
        product: 'Superforecasting Agent',
        questions: [
          {
            id: 'fq_cpi',
            probability: 0.61,
            title: 'Will the CPI release exceed consensus?'
          }
        ],
        review_queue: [],
        review_queue_count: 0
      }
    }

    const evidenceSections = forecastLedgerViewSections(response, 'evidence')

    expect(evidenceSections[0]?.title).toBe('View Shortcuts')
    expect(evidenceSections[0]?.rows).toEqual(
      expect.arrayContaining([
        ['Alt+4', 'evidence (active): evidence readiness and source gaps', '/ledger evidence'],
        ['Ctrl+F', 'find: search forecasts by words, topics, rationale, or evidence', '/find <words>']
      ])
    )
    expect(evidenceSections.map(section => section.title)).toEqual(
      expect.arrayContaining(['View Shortcuts', 'Evidence Status', 'Evidence Imports', 'Triage'])
    )
  })
})
