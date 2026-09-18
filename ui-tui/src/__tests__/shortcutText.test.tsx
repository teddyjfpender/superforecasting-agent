import React from 'react'
import { describe, expect, it } from 'vitest'

import { shortcutParts, ShortcutText } from '../components/shortcutText.js'
import { DARK_THEME } from '../theme.js'

describe('authored keyboard hints', () => {
  it.each([
    ['Press f to filter, or a to add.', ['f', 'a']],
    ['[Ctrl+Enter send] [Shift+Tab chart/horizon]', ['Ctrl+Enter', 'Shift+Tab']],
    ['Tab recipient · ↑↓ select · Esc close', ['Tab', '↑↓', 'Esc']],
    ['f Filter · r Refresh · ^F Find · PgUp/Dn Read', ['f', 'r', '^F', 'PgUp/Dn']],
    ['Use `f` here; a forecast is a forecast.', ['f']],
    ['A feed from France, with factual information.', []]
  ])('recognizes actions in %s without highlighting ordinary prose', (text, keys) => {
    expect(
      shortcutParts(text)
        .filter(part => part.key)
        .map(part => part.text)
    ).toEqual(keys)
    expect(
      shortcutParts(text)
        .map(part => part.text)
        .join('')
    ).toBe(text.replaceAll('`', ''))
  })
  it('preserves the rendered instruction and marks actionable keys bold', () => {
    const tree = ShortcutText({ t: DARK_THEME, children: 'Press f to filter' })
    expect(React.Children.toArray(tree.props.children)).toContainEqual(
      expect.objectContaining({
        props: expect.objectContaining({ bold: true, color: DARK_THEME.color.accent, children: 'f' })
      })
    )
  })
})
