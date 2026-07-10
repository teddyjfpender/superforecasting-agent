import type {
  ForecastDashboardQuestion,
  ForecastDashboardResponse,
  ForecastDashboardReview
} from '../../gatewayTypes.js'

import { shortId } from './format.js'

// ── Forecast question search / ranking ───────────────────────────────────────
// Query normalization, tokenization, de-dup of question+review rows, and the
// weighted match scorer that ranks forecasts by id/title/domain/topics/evidence.
// Moved out of forecastPanel.ts verbatim (Wave-5 modularization); the panel
// re-exports rankForecastQuestionMatches + the ForecastQuestionSearchMatch shape.

export interface ForecastQuestionSearchMatch {
  index: number
  matched: string[]
  row: ForecastDashboardQuestion | ForecastDashboardReview
  score: number
}

export const searchNormalize = (value: unknown) =>
  String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9_ -]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const searchTokens = (query: string) =>
  searchNormalize(query)
    .split(/\s+/)
    .filter(token => token.length >= 2)

const uniqueForecastRows = (
  questions: ForecastDashboardQuestion[],
  reviewQueue: ForecastDashboardReview[]
): Array<{ index: number; row: ForecastDashboardQuestion | ForecastDashboardReview }> => {
  const rows: Array<{ index: number; row: ForecastDashboardQuestion | ForecastDashboardReview }> = []
  const seen = new Set<string>()

  questions.forEach((row, index) => {
    if (!row.id || seen.has(row.id)) {
      return
    }

    seen.add(row.id)
    rows.push({ index, row })
  })

  reviewQueue.forEach(row => {
    if (!row.id || seen.has(row.id)) {
      return
    }

    seen.add(row.id)
    rows.push({ index: rows.length, row })
  })

  return rows
}

const scoreForecastQuestionMatch = (
  row: ForecastDashboardQuestion | ForecastDashboardReview,
  query: string,
  tokens: string[]
): ForecastQuestionSearchMatch | null => {
  const id = row.id || ''
  const short = shortId(id)
  const title = row.title || ''
  const domain = row.domain || ''
  const topics = 'topics' in row && Array.isArray(row.topics) ? row.topics.join(' ') : ''
  const status = 'status' in row ? row.status || '' : ''
  const latestRationale = 'latest_rationale' in row ? row.latest_rationale || '' : ''

  const latestEvidence = [
    'latest_evidence_claim' in row ? row.latest_evidence_claim || '' : '',
    'latest_evidence_summary' in row ? row.latest_evidence_summary || '' : ''
  ].join(' ')

  const text = searchNormalize([id, short, title, domain, topics, status, latestRationale, latestEvidence].join(' '))
  const fullQuery = searchNormalize(query)
  const matched = new Set<string>()
  let score = 0

  if (!fullQuery) {
    return null
  }

  if (searchNormalize(id) === fullQuery || searchNormalize(short) === fullQuery) {
    score += 40
    matched.add('id')
  } else if (searchNormalize(id).includes(fullQuery) || searchNormalize(short).includes(fullQuery)) {
    score += 24
    matched.add('id')
  }

  if (searchNormalize(title).includes(fullQuery)) {
    score += 14
    matched.add('title')
  }

  if (domain && searchNormalize(domain).includes(fullQuery)) {
    score += 8
    matched.add('domain')
  }

  if (topics && searchNormalize(topics).includes(fullQuery)) {
    score += 8
    matched.add('topics')
  }

  if (latestRationale && searchNormalize(latestRationale).includes(fullQuery)) {
    score += 6
    matched.add('rationale')
  }

  if (latestEvidence && searchNormalize(latestEvidence).includes(fullQuery)) {
    score += 6
    matched.add('evidence')
  }

  for (const token of tokens) {
    if (!text.includes(token)) {
      continue
    }

    score += searchNormalize(title).includes(token) ? 4 : 2

    if (searchNormalize(title).includes(token)) {
      matched.add(token)
    }
  }

  if (tokens.length && tokens.every(token => text.includes(token))) {
    score += 6
  }

  return score > 0 ? { index: 0, matched: Array.from(matched), row, score } : null
}

export const rankForecastQuestionMatches = (
  response: ForecastDashboardResponse,
  query: string,
  limit = 12
): ForecastQuestionSearchMatch[] => {
  const summary = response.summary

  if (!summary) {
    return []
  }

  const tokens = searchTokens(query)

  return uniqueForecastRows(summary.questions ?? [], summary.review_queue ?? [])
    .map(({ index, row }) => {
      const match = scoreForecastQuestionMatch(row, query, tokens)

      return match ? { ...match, index } : null
    })
    .filter((match): match is ForecastQuestionSearchMatch => Boolean(match))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, Math.max(limit, 0))
}
