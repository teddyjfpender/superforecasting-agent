import { describe, expect, it } from 'vitest'

import { uniqueArticles } from '../lib/newsDesk.js'
import { normalizeFeedUrl } from '../lib/newsFeedStore.js'

it('keeps case-sensitive feeds distinct', () => {
  expect(normalizeFeedUrl('https://EXAMPLE.org/Feed?Key=A')).toBe('example.org/Feed?Key=A')
  expect(normalizeFeedUrl('https://example.org/Feed')).not.toBe(normalizeFeedUrl('https://example.org/feed'))
})

describe('news aggregation', () => {
  it('collapses tracking variants but preserves independent reporting', () => {
    const base = {
      title: 'Story',
      summary: 'Text',
      feedTitle: 'Source',
      feedUrl: 'https://example.org/feed',
      publishedAt: 1
    }

    expect(
      uniqueArticles([
        { ...base, link: 'https://example.org/story?utm_source=rss' },
        { ...base, link: 'https://example.org/story' },
        { ...base, link: 'https://another.org/story', publishedAt: 2 }
      ])
    ).toHaveLength(2)
  })
})
