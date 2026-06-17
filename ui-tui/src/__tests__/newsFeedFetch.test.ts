import { describe, expect, it } from 'vitest'

import { parseFeed } from '../lib/newsFeedFetch.js'

const RSS = `<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example News</title>
  <item>
    <title>Markets rally &amp; bonds slip</title>
    <link>https://example.com/a</link>
    <pubDate>Wed, 18 Jun 2025 09:00:00 GMT</pubDate>
    <description><![CDATA[<p>Stocks <b>up</b> 2%.</p>]]></description>
  </item>
  <item>
    <title>Second story</title>
    <link>https://example.com/b</link>
    <description>Plain summary &lt;ok&gt;</description>
  </item>
</channel></rss>`

const ATOM = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Example</title>
  <entry>
    <title>Atom entry one</title>
    <link rel="alternate" href="https://atom.example/one"/>
    <updated>2025-06-17T12:00:00Z</updated>
    <summary>Summary text</summary>
  </entry>
</feed>`

describe('parseFeed — RSS', () => {
  const items = parseFeed(RSS, 'https://example.com/rss', 'Example News')

  it('extracts items with decoded titles and links', () => {
    expect(items).toHaveLength(2)
    expect(items[0].title).toBe('Markets rally & bonds slip')
    expect(items[0].link).toBe('https://example.com/a')
  })

  it('parses pubDate to epoch ms and strips HTML from the summary', () => {
    expect(items[0].publishedAt).toBe(Date.parse('Wed, 18 Jun 2025 09:00:00 GMT'))
    expect(items[0].summary).toBe('Stocks up 2%.')
  })

  it('tolerates a missing date (publishedAt 0) and decodes entities', () => {
    expect(items[1].publishedAt).toBe(0)
    expect(items[1].summary).toBe('Plain summary <ok>')
  })

  it('stamps the feed title/url onto every article', () => {
    expect(items.every(a => a.feedTitle === 'Example News')).toBe(true)
    expect(items.every(a => a.feedUrl === 'https://example.com/rss')).toBe(true)
  })
})

describe('parseFeed — Atom', () => {
  it('reads <entry>, the alternate link href, and <updated>', () => {
    const items = parseFeed(ATOM, 'https://atom.example/feed', 'Atom Example')
    expect(items).toHaveLength(1)
    expect(items[0].title).toBe('Atom entry one')
    expect(items[0].link).toBe('https://atom.example/one')
    expect(items[0].publishedAt).toBe(Date.parse('2025-06-17T12:00:00Z'))
    expect(items[0].summary).toBe('Summary text')
  })
})

describe('parseFeed — robustness', () => {
  it('returns [] for non-feed input rather than throwing', () => {
    expect(parseFeed('<html><body>not a feed</body></html>', 'https://x', 'X')).toEqual([])
    expect(parseFeed('', 'https://x', 'X')).toEqual([])
  })
})
