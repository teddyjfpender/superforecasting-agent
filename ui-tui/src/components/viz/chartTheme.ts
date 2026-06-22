// Map the app Theme → the engine's ChartTheme. Diverging RdBu-style heat ramp
// (blue ↔ neutral ↔ red) so correlation sign reads instantly; band ramp from the
// muted/border greys.

import { diverging } from '../../lib/viz/color.js'
import type { ChartTheme } from '../../lib/viz/index.js'
import type { Theme } from '../../theme.js'

export const themeToChartTheme = (t: Theme): ChartTheme => ({
  bands: [t.color.border, t.color.muted],
  down: t.color.info ?? '#3b82f6',
  fg: t.color.text,
  gain: t.color.ok, // price up / bids — green
  grid: t.color.border,
  // negative=blue (info), neutral=muted grey, positive=red (error).
  heat: diverging(t.color.info ?? '#3b82f6', t.color.muted, t.color.error),
  loss: t.color.error, // price down / asks — red
  muted: t.color.muted,
  up: t.color.error
})
