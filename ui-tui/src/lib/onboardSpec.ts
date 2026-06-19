// Pure spec-builder for the forecast-question onboarding modal: maps the
// collected step answers into a QuestionSpec dict the gateway's
// forecast.onboard_commit RPC accepts. Kept separate from the Ink component so
// the field mapping is unit-testable.

export interface OnboardSource {
  reliabilityPrior?: number
  source: string
  sourceType?: string
}

export interface OnboardAnswers {
  choices?: string[] // categorical
  criteria: string
  evidence: boolean // allow_evidence_gathering
  outcome: 'binary' | 'categorical' | 'numeric'
  owner?: string
  panel: boolean // panel_by_default
  sources: OnboardSource[]
  threshold?: string
  title: string
  units?: string // numeric
}

export const emptyAnswers = (): OnboardAnswers => ({
  criteria: '',
  evidence: true,
  outcome: 'binary',
  owner: '',
  panel: false,
  sources: [],
  threshold: '',
  title: ''
})

export const specFromAnswers = (a: OnboardAnswers): Record<string, unknown> => {
  const spec: Record<string, unknown> = {
    allow_evidence_gathering: a.evidence,
    outcome_type: a.outcome,
    panel_by_default: a.panel,
    resolution_criteria: a.criteria.trim(),
    title: a.title.trim()
  }

  if (a.outcome === 'numeric' && a.units?.trim()) {
    spec.units = a.units.trim()
  }

  if (a.outcome === 'categorical' && a.choices?.length) {
    spec.choices = a.choices.map(c => c.trim()).filter(Boolean)
  }

  if (a.owner?.trim()) {
    spec.decision_owner = a.owner.trim()
  }

  if (a.threshold?.trim()) {
    spec.action_threshold = a.threshold.trim()
  }

  if (a.sources.length) {
    spec.watched_sources = a.sources
      .filter(s => s.source.trim())
      .map(s => ({
        reliability_prior: s.reliabilityPrior ?? 0.7,
        source: s.source.trim(),
        ...(s.sourceType ? { source_type: s.sourceType } : {})
      }))
  }

  return spec
}

// Parse a "source[:type]" line (e.g. "polymarket:fed-cut-sept" or
// "fred:CPIAUCSL" or a bare URL) into a watched-source answer. Returns null for
// blank input.
export const parseSourceLine = (line: string): null | OnboardSource => {
  const text = line.trim()

  if (!text) {
    return null
  }

  // A leading "<type>:" prefix where the type is a known adapter family.
  const m = /^([a-z0-9]+):(.+)$/i.exec(text)

  const KNOWN = new Set([
    'fred', 'polymarket', 'kalshi', 'manifold', 'metaculus', 'rss', 'gdelt',
    'bls', 'eia', 'treasury', 'worldbank', 'imf', 'census', 'yahoo', 'sec', 'arxiv', 'url'
  ])

  if (m && KNOWN.has(m[1].toLowerCase())) {
    return { source: text, sourceType: m[1].toLowerCase() }
  }

  return { source: text }
}
