import { useMemo } from 'react'

import { resolveCaps } from '../../lib/viz/index.js'
import type { TerminalCaps } from '../../lib/viz/index.js'

// Resolve terminal capabilities once per mount (sync env heuristic; no async
// probe in v1). Stable across renders so chart memoization keys on it cheaply.
export const useViewportCaps = (): TerminalCaps => useMemo(() => resolveCaps(), [])
