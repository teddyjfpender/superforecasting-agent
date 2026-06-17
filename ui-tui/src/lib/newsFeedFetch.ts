import { ensureFeedUrlScheme, feedHost } from './newsFeedStore.js'

// Minimal, dependency-free RSS / Atom fetch + parse. Runs in the TUI's Node
// runtime (global fetch). The parser is an attribute/tag scan, not a strict XML
// parse, so it tolerates the unescaped ampersands and odd namespacing real
// feeds ship — same approach as the catalog generator.

export interface Article {
  feedTitle: string
  feedUrl: string
  link: string
  publishedAt: number // epoch ms, 0 if unknown
  summary: string
  title: string
}

const ENTITIES: Record<string, string> = {
  amp: '&',
  apos: "'",
  gt: '>',
  lt: '<',
  nbsp: ' ',
  quot: '"'
}

const decodeEntities = (s: string): string =>
  s
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => safeCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeCodePoint(parseInt(d, 10)))
    .replace(/&(amp|lt|gt|quot|apos|nbsp);/gi, (_, n) => ENTITIES[n.toLowerCase()] ?? '')

const safeCodePoint = (code: number): string => {
  try {
    return Number.isFinite(code) ? String.fromCodePoint(code) : ''
  } catch {
    return ''
  }
}

const stripCdata = (s: string): string => s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')

const clean = (raw: string | null | undefined, limit = 0): string => {
  if (!raw) {
    return ''
  }

  let s = stripCdata(raw)
  s = s.replace(/<[^>]+>/g, ' ') // strip HTML tags
  s = decodeEntities(s)
  s = s.replace(/\s+/g, ' ').trim()

  if (limit > 0 && s.length > limit) {
    s = `${s.slice(0, limit - 1).trimEnd()}…`
  }

  return s
}

// Inner text of the first <name>…</name> (namespace-insensitive on the prefix).
const tagText = (block: string, name: string): string => {
  const re = new RegExp(`<(?:[\\w-]+:)?${name}(?:\\s[^>]*)?>([\\s\\S]*?)</(?:[\\w-]+:)?${name}>`, 'i')

  return re.exec(block)?.[1] ?? ''
}

// Atom-style <link href="…" rel="alternate"/> — prefer an explicit alternate.
const linkHref = (block: string): string => {
  const links = [...block.matchAll(/<(?:[\w-]+:)?link\b([^>]*)\/?>/gi)].map(m => m[1])
  const attrs = (a: string, k: string) => new RegExp(`${k}\\s*=\\s*"([^"]*)"`, 'i').exec(a)?.[1] ?? ''
  const alt = links.find(a => /rel\s*=\s*"alternate"/i.test(a)) ?? links.find(a => attrs(a, 'href'))

  return alt ? attrs(alt, 'href') : ''
}

const splitBlocks = (xml: string, tag: string): string[] => {
  const re = new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`, 'gi')

  return [...xml.matchAll(re)].map(m => m[1])
}

export const parseFeed = (xml: string, feedUrl: string, feedTitle: string): Article[] => {
  const isAtom = /<entry[\s>]/i.test(xml) && !/<item[\s>]/i.test(xml)
  const blocks = isAtom ? splitBlocks(xml, 'entry') : splitBlocks(xml, 'item')
  const title = feedTitle || clean(tagText(xml.split(isAtom ? '<entry' : '<item')[0] ?? '', 'title')) || feedHost(feedUrl)

  const articles: Article[] = []

  for (const block of blocks) {
    const headline = clean(tagText(block, 'title'), 200)

    if (!headline) {
      continue
    }

    const rawLink = clean(tagText(block, 'link')) || linkHref(block) || clean(tagText(block, 'guid'))

    const dateStr =
      tagText(block, 'pubDate') ||
      tagText(block, 'published') ||
      tagText(block, 'updated') ||
      tagText(block, 'date')

    const parsed = Date.parse(clean(dateStr))
    const summary = clean(tagText(block, 'description') || tagText(block, 'summary') || tagText(block, 'encoded') || tagText(block, 'content'), 400)

    articles.push({
      feedTitle: title,
      feedUrl,
      link: rawLink.trim(),
      publishedAt: Number.isFinite(parsed) ? parsed : 0,
      summary,
      title: headline
    })
  }

  return articles
}

export interface FetchResult {
  articles: Article[]
  error: null | string
}

export const fetchFeed = async (url: string, feedTitle: string, timeoutMs = 9000): Promise<FetchResult> => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(ensureFeedUrlScheme(url), {
      headers: {
        Accept: 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
        'User-Agent': 'Outrider/1.0 (+superforecasting-agent)'
      },
      redirect: 'follow',
      signal: controller.signal
    })

    if (!response.ok) {
      return { articles: [], error: `HTTP ${response.status}` }
    }

    const xml = await response.text()

    return { articles: parseFeed(xml, url, feedTitle), error: null }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)

    return { articles: [], error: message.includes('aborted') ? 'timed out' : message }
  } finally {
    clearTimeout(timer)
  }
}

// Bounded-concurrency fan-out so refreshing N feeds doesn't open N sockets.
export const fetchFeeds = async (
  feeds: { title: string; url: string }[],
  onEach: (url: string, result: FetchResult) => void,
  concurrency = 6
): Promise<void> => {
  const queue = [...feeds]

  const worker = async () => {
    for (;;) {
      const feed = queue.shift()

      if (!feed) {
        return
      }

      const result = await fetchFeed(feed.url, feed.title)
      onEach(feed.url, result)
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, feeds.length)) }, worker))
}
