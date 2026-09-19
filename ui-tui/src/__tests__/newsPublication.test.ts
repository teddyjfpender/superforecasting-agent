import { expect, it } from 'vitest'

import type { Article } from '../lib/newsFeedFetch.js'
import { sameNewsArticles } from '../lib/newsPublication.js'

it('detects new ordering and revised content, ignoring replacement object identities', () => {
  const a: Article = {
    feedUrl: 'https://example.org/rss',
    feedTitle: 'Example',
    link: 'https://example.org/a',
    title: 'A',
    summary: 'Original',
    publishedAt: 1
  }

  const b = { ...a, link: 'https://example.org/b', title: 'B' }
  expect(sameNewsArticles([a, b], [{ ...a }, { ...b }])).toBe(true)
  expect(sameNewsArticles([a, b], [b, a])).toBe(false)
  expect(sameNewsArticles([a], [{ ...a, content: 'Revised story' }])).toBe(false)
  expect(sameNewsArticles([a], [a, b])).toBe(false)
})
