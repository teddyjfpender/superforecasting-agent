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

it('removes cached NHC empty-basin placeholders and demotes future publication claims', () => {
  const now = Date.parse('2026-09-15T13:00:00Z')

  const base = {
    title: 'Report',
    summary: '',
    feedTitle: 'Source',
    feedUrl: 'https://example.org/feed',
    link: '',
    publishedAt: now - 1000
  }

  const articles = [
    {
      ...base,
      title: 'There are no tropical cyclones at this time.',
      feedUrl: 'https://www.nhc.noaa.gov/index-at.xml',
      publishedAt: now + 86400000
    },
    { ...base, title: 'Future story', publishedAt: now + 86400000 },
    { ...base, title: 'Older story', publishedAt: now - 2000 },
    base
  ]

  expect(uniqueArticles(articles, now).map(article => article.title)).toEqual(['Report', 'Older story', 'Future story'])
  expect(articles).toHaveLength(4)
  expect(uniqueArticles(articles, now + 86400001)[0].title).toBe('Future story')
})
