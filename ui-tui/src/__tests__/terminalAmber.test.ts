import { readFileSync } from 'node:fs'

import { expect, it } from 'vitest'

import { relLuminance } from '../lib/visualSemantics.js'
import { fromSkin } from '../theme.js'

const colors = JSON.parse(readFileSync(new URL('./fixtures/terminal-amber.json', import.meta.url), 'utf8')) as Record<
  string,
  string
>

const theme = fromSkin(colors, {}, '', '', '', '', false)

const ratio = (fg: string, bg: string) => {
  const a = relLuminance(fg)!
  const b = relLuminance(bg)!

  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

it('keeps its explicit black canvas even when the terminal advertises light mode', () => {
  expect(fromSkin(colors, {}, '', '', '', '', true).color).toEqual(theme.color)
  expect(theme.color.canvas).toBe('#000000')
})

it('meets AAA text contrast across normal, selected, status and completion surfaces', () => {
  const backgrounds = [
    theme.color.canvas!,
    theme.color.selectionBg,
    theme.color.statusBg,
    theme.color.completionBg,
    theme.color.completionCurrentBg,
    theme.color.completionMetaBg,
    theme.color.completionMetaCurrentBg
  ]

  const foregrounds = [
    'text',
    'muted',
    'primary',
    'accent',
    'label',
    'info',
    'ok',
    'warn',
    'error',
    'prompt',
    'sessionLabel',
    'statusFg',
    'statusGood',
    'statusWarn',
    'statusBad',
    'statusCritical',
    'shellDollar'
  ] as const

  for (const bg of backgrounds) {
    for (const key of foregrounds) {
      expect(ratio(theme.color[key], bg), `${key} on ${bg}`).toBeGreaterThanOrEqual(7)
    }

    // Borders are also used for empty-cell text, so require text AA, not just 3:1.
    expect(ratio(theme.color.border, bg)).toBeGreaterThanOrEqual(4.5)
  }
})
