import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

const keyboard = vi.hoisted(() => ({ handler: null as null | ((input: string, key: unknown) => unknown) }))
vi.mock('@superforecasting/ink', () => ({
  useInput: (handler: typeof keyboard.handler) => {
    keyboard.handler = handler
  },
  Box: 'box',
  Text: 'text'
}))
import { FooterChips } from '../components/footerChips.js'
import { footerKey, useViewInput } from '../lib/useViewInput.js'
import { DARK_THEME } from '../theme.js'

it('footer actions and physical keys reach the same guarded view handler', () => {
  const action = vi.fn()

  const onKey = useViewInput((input, key) => {
    if (input === 'M' || key.return) {
      action(input)
    }
  })

  const row = FooterChips({
    chips: [
      { k: 'M', label: 'Models' },
      { k: '↑↓', label: 'Select' }
    ],
    onKey,
    t: DARK_THEME
  })

  const children = (row.props as { children: ReactElement<{ onClick?: (event: object) => void }>[] }).children
  children[0]!.props.onClick?.({})
  expect(action).toHaveBeenLastCalledWith('M')
  const enter = footerKey('⏎')!
  keyboard.handler?.(enter.input, enter.key)
  expect(action).toHaveBeenCalledTimes(2)
  expect(children[1]!.props.onClick).toBeUndefined()
})

it('disabled view and modal-covered footer cannot dispatch', () => {
  const action = vi.fn()
  const onKey = useViewInput(action, { isActive: false })
  onKey('x')
  expect(action).not.toHaveBeenCalled()
  const row = FooterChips({ chips: [{ k: 'x', label: 'Delete', run: action }], disabled: true, t: DARK_THEME })
  const children = (row.props as { children: ReactElement<{ onClick?: unknown }>[] }).children
  expect(children[0]!.props.onClick).toBeUndefined()
})

it('keeps uppercase and control commands distinct and never guesses combined hints', () => {
  expect(footerKey('M')).toMatchObject({ input: 'M', key: { shift: true } })
  expect(footerKey('m')).toMatchObject({ input: 'm', key: { shift: false } })
  expect(footerKey('^O')).toMatchObject({ input: 'o', key: { ctrl: true } })
  expect(footerKey('PgUp/Dn')).toBeNull()
  expect(footerKey('g/G')).toBeNull()
})

describe('shared help and footer ownership', () => {
  const read = (path: string) => readFileSync(resolve('src', path), 'utf8')
  it('Home no longer renders the retired inline hint', () => {
    expect(read('components/appLayout.tsx')).not.toContain('HelpHint')
  })

  for (const view of [
    'deskView',
    'marketsView',
    'newsView',
    'messagingView',
    'documentDesk',
    'hooksView',
    'calendarView',
    'calibrationView',
    'alertsView',
    'agentsOverlay',
    'demoVizView'
  ]) {
    it(`${view} shares keyboard and footer dispatch`, () => {
      const source = read(`components/${view}.tsx`)
      expect(source).toContain('useViewInput(')
      expect(source).toContain('onKey={handleFooterKey}')
    })
  }
})
