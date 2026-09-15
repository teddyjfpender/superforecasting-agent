import { PassThrough } from 'node:stream'

import { Box, render } from '@superforecasting/ink'
import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { resetOverlayState } from '../app/overlayStore.js'
import { NewsView } from '../components/newsView.js'
import { stripAnsi } from '../lib/text.js'
import { DARK_THEME } from '../theme.js'

const tick = (ms = 80) => new Promise(resolve => setTimeout(resolve, ms))
const feed = { url: 'https://example.org/feed', title: 'Example · World', category: 'World', addedAt: 0, custom: false }

const xml =
  '<rss><channel><item><title>First source report</title><link>https://example.org/first</link><description>Teaser</description><content:encoded>' +
  'Detailed publisher feed content. '.repeat(40) +
  '</content:encoded></item><item><title>Second source report</title><link>https://example.org/second</link><description>Second teaser</description></item></channel></rss>'

async function mount(cols: number, rows: number, configured = false) {
  resetOverlayState()

  const dimensions = ['columns', 'rows'].map(
    key => [key, Object.getOwnPropertyDescriptor(process.stdout, key)] as const
  )

  Object.defineProperty(process.stdout, 'columns', { value: cols, configurable: true })
  Object.defineProperty(process.stdout, 'rows', { value: rows, configurable: true })
  process.env.FORECAST_TUI_INLINE = '1'

  const starter = [
    'Markets',
    'Business',
    'World',
    'Europe',
    'Asia Pacific',
    'Latin America',
    'Middle East',
    'Africa',
    'Central Banks',
    'Economics',
    'Energy',
    'Technology',
    'Science',
    'Climate',
    'Weather',
    'Disasters'
  ].map((category, i) => ({ ...feed, category, url: `https://example.org/feed${i}` }))

  let feeds = configured ? [feed] : []
  let fail = false
  let release: ((value: unknown) => void) | undefined
  let delay = false

  const request = vi.fn(async (method: string, params: { action?: string; url?: string }) => {
    if (method === 'news.desk') {
      return { feeds, starter, state: configured ? 'configured' : 'unconfigured' }
    }

    if (method === 'news.configure') {
      feeds = params.action === 'starter' ? [feed] : []

      return { feeds, starter, state: 'configured' }
    }

    if (method === 'news.feed') {
      if (fail) {
        throw new Error('Source offline')
      }

      return { xml, url: feed.url }
    }

    if (method === 'news.article') {
      if (delay && params.url?.endsWith('first')) {
        return new Promise(resolve => {
          release = resolve
        })
      }

      return {
        text: 'Current article body. '.repeat(100),
        url: params.url,
        status: 'article',
        message: 'Publisher article text'
      }
    }

    throw new Error('Unexpected method')
  })

  const stdout = new PassThrough()
  const stdin = new PassThrough()
  Object.assign(stdout, { columns: cols, rows, isTTY: false })
  Object.assign(stdin, { isTTY: true, isRaw: false, setRawMode: () => undefined, ref: () => stdin, unref: () => stdin })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const instance = await render(
    <Box height={rows} width={cols}>
      <NewsView gw={{ request } as never} onClose={() => undefined} t={DARK_THEME} />
    </Box>,
    { stdin, stdout, patchConsole: false, exitOnCtrlC: false }
  )

  await tick()

  return {
    request,
    text: () => stripAnsi(output),
    fail: () => {
      fail = true
    },
    delay: () => {
      delay = true
    },
    release: () =>
      release?.({
        text: 'STALE BODY '.repeat(200),
        url: 'https://example.org/first',
        status: 'article',
        message: 'Publisher article text'
      }),
    press: async (key: string) => {
      output = ''
      stdin.write(key)
      await tick()
    },
    close: () => {
      instance.unmount()
      instance.cleanup()
      stdin.destroy()
      stdout.destroy()

      for (const [key, descriptor] of dimensions) {
        if (descriptor) {
          Object.defineProperty(process.stdout, key, descriptor)
        } else {
          Reflect.deleteProperty(process.stdout, key)
        }
      }
    }
  }
}

afterEach(() => {
  delete process.env.FORECAST_TUI_INLINE
  resetOverlayState()
})

it.each([
  [80, 24],
  [120, 40]
])('offers an explicit starter or empty choice at %i×%i', async (cols, rows) => {
  const app = await mount(cols, rows)

  try {
    expect(app.text()).toContain('Load global starter')
    expect(app.text()).toContain('Start empty')
    await app.press('\u001b[B')
    await app.press('\r')
    expect(app.request).toHaveBeenCalledWith('news.configure', { action: 'empty', feed: null })
    await app.press('s')
    await app.press('\r')
    expect(app.request).toHaveBeenCalledWith('news.configure', { action: 'starter', feed: null })
    expect(app.text()).toContain('First source report')
    expect(app.text()).toContain('Detailed publisher')
  } finally {
    app.close()
  }
})

it('preserves cached headlines when a refresh fails', async () => {
  const app = await mount(120, 40, true)

  try {
    expect(app.text()).toContain('First source report')
    app.fail()
    await app.press('r')
    expect(app.text()).toContain('First source report')
    expect(app.text()).toContain('source errors')
  } finally {
    app.close()
  }
})

it('never displays a stale article response after moving to the next story', async () => {
  const app = await mount(120, 40, true)

  try {
    app.delay()
    await tick(550)
    await app.press('\u001b[B')
    await tick(550)
    app.release()
    await tick(100)
    expect(app.text()).toContain('Current article body')
    expect(app.text()).not.toContain('STALE BODY')
  } finally {
    app.release()
    app.close()
  }
})
