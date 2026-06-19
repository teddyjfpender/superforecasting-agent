import { describe, expect, it } from 'vitest'

import { emptyAnswers, parseSourceLine, specFromAnswers } from '../lib/onboardSpec.js'

describe('specFromAnswers', () => {
  it('builds a minimal binary spec', () => {
    const spec = specFromAnswers({ ...emptyAnswers(), title: ' CPI > 3% ', criteria: ' BLS June CPI YoY > 3.0% ' })
    expect(spec).toMatchObject({
      allow_evidence_gathering: true,
      outcome_type: 'binary',
      panel_by_default: false,
      resolution_criteria: 'BLS June CPI YoY > 3.0%',
      title: 'CPI > 3%'
    })
    expect('units' in spec).toBe(false)
    expect('decision_owner' in spec).toBe(false)
    expect('watched_sources' in spec).toBe(false)
  })

  it('includes units for numeric and choices for categorical', () => {
    expect(specFromAnswers({ ...emptyAnswers(), outcome: 'numeric', units: '%' }).units).toBe('%')
    const cat = specFromAnswers({ ...emptyAnswers(), outcome: 'categorical', choices: ['a', ' b ', ''] })
    expect(cat.choices).toEqual(['a', 'b'])
  })

  it('maps owner/threshold/sources and defaults reliability_prior', () => {
    const spec = specFromAnswers({
      ...emptyAnswers(),
      owner: 'me',
      threshold: '>=70% act',
      sources: [{ source: 'fred:CPIAUCSL', sourceType: 'fred' }, { source: '  ' }]
    })

    expect(spec.decision_owner).toBe('me')
    expect(spec.action_threshold).toBe('>=70% act')
    expect(spec.watched_sources).toEqual([{ reliability_prior: 0.7, source: 'fred:CPIAUCSL', source_type: 'fred' }])
  })
})

describe('parseSourceLine', () => {
  it('detects a known adapter prefix', () => {
    expect(parseSourceLine('fred:CPIAUCSL')).toEqual({ source: 'fred:CPIAUCSL', sourceType: 'fred' })
    expect(parseSourceLine('polymarket:fed-cut')).toEqual({ source: 'polymarket:fed-cut', sourceType: 'polymarket' })
  })
  it('leaves an unknown prefix / URL as a bare source', () => {
    expect(parseSourceLine('https://example.com/feed')).toEqual({ source: 'https://example.com/feed' })
  })
  it('returns null for blank', () => {
    expect(parseSourceLine('   ')).toBeNull()
  })
})
