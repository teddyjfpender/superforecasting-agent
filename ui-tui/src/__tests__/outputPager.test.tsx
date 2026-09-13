import { PassThrough } from 'stream'

import { Box, render, Text } from '@superforecasting/ink'
import React from 'react'
import { afterEach, expect, it } from 'vitest'

import { patchOverlayState } from '../app/overlayStore.js'
import { patchUiState } from '../app/uiStore.js'
import { OutputPager } from '../components/appOverlays.js'

process.env.FORECAST_TUI_INLINE = '1'

afterEach(() => patchOverlayState({ pager: null }))

it.each([[80, 24, 0], [160, 45, 0], [80, 24, 50], [160, 45, 50]])('paints score output without a model session at %sx%s after %s rows', async (cols, rows, filler) => {
  const stdout = Object.assign(new PassThrough(), { columns: cols, isTTY: false, rows })
  const stdin = Object.assign(new PassThrough(), { isTTY: false })
  let output = ''

  stdout.on('data', chunk => { output += chunk.toString() })
  patchUiState({ sid: null, status: 'setup required' })
  patchOverlayState({ pager: { lines: [...Array.from({ length: filler }, (_, i) => `earlier row ${i}`), 'score: fixture', 'baseline_scores: none'], offset: filler ? 999 : 0, title: 'Forecast' } })

  const instance = await render(
    <Box flexDirection="column" height={rows} width={cols}>
      <Text>Setup Required</Text>
      <OutputPager cols={cols} pageSize={rows - 13} rows={rows} />
    </Box>,
    { exitOnCtrlC: false, patchConsole: false, stdin, stdout }
  )

  try {
    await new Promise(resolve => setTimeout(resolve, 60))
    expect(output).toContain('baseline_scores: none')
    expect(output).toContain('score: fixture')
  } finally {
    instance.unmount()
    instance.cleanup()
  }
})
