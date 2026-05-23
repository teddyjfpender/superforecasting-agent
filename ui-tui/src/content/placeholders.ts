import { pick } from '../lib/text.js'

export const PLACEHOLDERS = [
  'Forecast a scoreable question…',
  'Try /forecast new "Will X happen?"',
  'Try /forecast review --stale',
  'Try /forecast readiness',
  'Try /forecast backtest --benchmarks',
  'Try /forecast self-check',
  'Try /sources for evidence adapters'
]

export const PLACEHOLDER = pick(PLACEHOLDERS)
