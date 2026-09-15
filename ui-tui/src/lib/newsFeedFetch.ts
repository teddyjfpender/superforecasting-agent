import { ensureFeedUrlScheme, feedHost } from './newsFeedStore.js'

// Minimal, dependency-free RSS / Atom fetch + parse. Runs in the TUI's Node
// runtime (global fetch). The parser is an attribute/tag scan, not a strict XML
// parse, so it tolerates the unescaped ampersands and odd namespacing real
// feeds ship — same approach as the catalog generator.

export interface Article {
  content?: string
  author?: string
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

const clean = (raw: string | null | undefined, limit = 0, paragraphs = false): string => {
  if (!raw) {
    return ''
  }

  let s = stripCdata(raw)
  s = s.replace(/<(script|style|noscript)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
  s = s.replace(/<[^>]+>/g, ' ') // strip HTML tags
  s = decodeEntities(s)
  s = [...s]
    .filter(char => {
      const code = char.codePointAt(0)!

      return code === 9 || code === 10 || (code >= 32 && (code < 127 || code >= 160))
    })
    .join('')
  s = paragraphs
    ? s
        .split(/\n\s*\n/)
        .map(paragraph => paragraph.replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .join('\n\n')
    : s.replace(/\s+/g, ' ').trim()

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
  const attrs = (a: string, k: string) => new RegExp(`${k}\\s*=\\s*["']([^"']*)["']`, 'i').exec(a)?.[1] ?? ''
  const alt = links.find(a => attrs(a, 'rel') === 'alternate') ?? links.find(a => attrs(a, 'href'))

  return alt ? attrs(alt, 'href') : ''
}

const splitBlocks = (xml: string, tag: string): string[] => {
  const re = new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}>`, 'gi')

  return [...xml.matchAll(re)].map(m => m[1])
}

export const parseFeed = (xml: string, feedUrl: string, feedTitle: string): Article[] => {
  const isAtom = /<entry[\s>]/i.test(xml) && !/<item[\s>]/i.test(xml)
  const blocks = isAtom ? splitBlocks(xml, 'entry') : splitBlocks(xml, 'item')

  const title =
    feedTitle || clean(tagText(xml.split(isAtom ? '<entry' : '<item')[0] ?? '', 'title')) || feedHost(feedUrl)

  const articles: Article[] = []

  for (const block of blocks.slice(0, 200)) {
    const headline = clean(tagText(block, 'title'), 200)

    if (!headline) {
      continue
    }

    const rawLink = clean(tagText(block, 'link')) || decodeEntities(linkHref(block)) || clean(tagText(block, 'guid'))
    let link = ''

    try {
      const parsedLink = new URL(rawLink, feedUrl)

      if (rawLink && ['http:', 'https:'].includes(parsedLink.protocol)) {
        link = parsedLink.href
      }
    } catch {
      /* A missing/broken source link is not an executable URL. */
    }

    const dateStr =
      tagText(block, 'pubDate') || tagText(block, 'published') || tagText(block, 'updated') || tagText(block, 'date')

    const parsed = Date.parse(clean(dateStr))

    const bodies = ['encoded', 'content', 'description', 'summary'].map(name =>
      clean(decodeEntities(tagText(block, name)).replace(/<\/(?:p|div|li|h[1-6])>|<br\s*\/?>/gi, '\n\n'), 24000, true)
    )

    const content = bodies.sort((a, b) => b.length - a.length)[0] ?? ''
    const summary = clean(tagText(block, 'description') || tagText(block, 'summary') || content, 600)
    const author = clean(tagText(block, 'creator') || tagText(block, 'author'), 200)

    articles.push({
      content,
      author,
      feedTitle: title,
      feedUrl,
      link,
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
        'User-Agent': 'Superforecasting-Agent/1.0'
      },
      redirect: 'follow',
      signal: controller.signal
    })

    if (!response.ok) {
      return { articles: [], error: `HTTP ${response.status}` }
    }

    const reader = response.body?.getReader()

    if (!reader) {
      return { articles: [], error: 'Empty feed response' }
    }

    const chunks: Uint8Array[] = []
    let bytes = 0

    try {
      for (;;) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        bytes += value.byteLength

        if (bytes > 2 * 1024 * 1024) {
          throw new Error('Feed exceeds 2 MiB limit')
        }

        chunks.push(value)
      }
    } finally {
      await reader.cancel()
      reader.releaseLock()
    }

    const xml = Buffer.concat(chunks).toString('utf8')

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
  concurrency = 6,
  loader = fetchFeed,
  signal?: AbortSignal
): Promise<void> => {
  const queue = [...feeds]

  const worker = async () => {
    for (;;) {
      if (signal?.aborted) {
        return
      }

      const feed = queue.shift()

      if (!feed) {
        return
      }

      const result = await loader(feed.url, feed.title)

      if (!signal?.aborted) {
        onEach(feed.url, result)
      }
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, feeds.length)) }, worker))
}
