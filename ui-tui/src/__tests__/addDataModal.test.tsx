import { PassThrough } from 'node:stream'

import { Box, render } from '@superforecasting/ink'
import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetOverlayState } from '../app/overlayStore.js'
import { AddProviderModal } from '../components/addProviderModal.js'
import { stripAnsi } from '../lib/text.js'
import type { DataCatalog, DeskSelection } from '../protocol/generated.js'
import { DARK_THEME } from '../theme.js'

const catalog: DataCatalog = {
  version: 1,
  countries: [{ id: 'DEU', name: 'Germany', region: 'europe' }],
  categories: [{ id: 'inflation', name: 'Inflation', group: 'Economy', aliases: [] }],
  regions: [{ id: 'europe', name: 'Europe', members: [] }],
  providers: [
    {
      id: 'example',
      name: 'Official Statistics',
      description: 'Official monthly observations',
      website: 'https://example.test',
      auth: 'none',
      key_env: null,
      signup_url: null,
      access_note: '',
      capabilities: ['latest', 'history']
    }
  ],
  series: [
    {
      id: 'example:inflation',
      provider: 'example',
      symbol: 'CPI',
      name: 'Germany · Consumer inflation',
      category: 'inflation',
      region: 'europe',
      country: 'DEU',
      location: null,
      kind: 'observation',
      frequency: 'monthly',
      change_basis: 'previous_observation',
      unit: '% annual change',
      dimensions: {},
      concept_id: 'inflation:de',
      source_family: 'official',
      source_url: 'https://example.test',
      revision_policy: 'latest',
      refresh_seconds: 86400,
      expected_lag_seconds: null,
      history_points: 24,
      tags: [],
      line: null
    }
  ],
  presets: [
    {
      id: 'global',
      version: 1,
      name: 'Global starter set',
      description: 'A useful global collection',
      series_ids: ['example:inflation']
    }
  ]
}

const empty: DeskSelection = {
  revision: 'empty',
  state: 'unconfigured',
  series_ids: [],
  categories: [],
  providers: [],
  custom: [],
  watchlist: [],
  pm_saved: [],
  server_side: null,
  home_region: null,
  weather_locations: null
}

const tick = () => new Promise(resolve => setTimeout(resolve, 70))

const mount = async (columns: number, rows: number, discovery?: (params: unknown) => Promise<unknown>) => {
  resetOverlayState()
  process.env.FORECAST_TUI_INLINE = '1'
  const stdout = new PassThrough()
  Object.assign(stdout, { columns, rows, isTTY: false })
  const stdin = new PassThrough()
  Object.assign(stdin, {
    columns,
    rows,
    isTTY: true,
    isRaw: false,
    setRawMode: () => undefined,
    ref: () => stdin,
    unref: () => stdin
  })
  let output = ''
  stdout.on('data', chunk => {
    output += String(chunk)
  })

  const request = vi.fn(async (method: string, params?: unknown) => {
    if (method === 'market.discover') {
      return discovery ? discovery(params) : { results: [], statuses: [] }
    }

    if (method === 'market.catalog') {
      return { catalog, catalog_revision: 'catalog', selection: empty, configured_providers: [] }
    }

    if (method === 'market.selection.preview') {
      return {
        preview: {
          revision: 'empty',
          catalog_revision: 'catalog',
          added: ['example:inflation'],
          removed: [],
          already_selected: [],
          credential_providers: [],
          selection: { ...empty, state: 'preset', series_ids: ['example:inflation'] }
        }
      }
    }

    if (method === 'market.selection.apply') {
      return { selection: { ...empty, state: 'preset', series_ids: ['example:inflation'] } }
    }

    throw new Error('Unexpected request')
  })

  const cancel = vi.fn()
  const saved = vi.fn()

  const instance = await render(
    <Box height={rows} width={columns}>
      <AddProviderModal
        cols={columns}
        gw={{ request } as never}
        initial={{ categories: [], providers: [], custom: [], watchlist: [] }}
        onCancel={cancel}
        onSaved={saved}
        rows={rows}
        t={DARK_THEME}
      />
    </Box>,
    { stdin, stdout, patchConsole: false, exitOnCtrlC: false }
  )

  await tick()

  return {
    cancel,
    saved,
    request,
    text: () => stripAnsi(output),
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
    }
  }
}

afterEach(() => {
  delete process.env.FORECAST_TUI_INLINE
  resetOverlayState()
})

describe('Add data interaction', () => {
  it('searches as you type and reviews indicator selection before saving', async () => {
    const app = await mount(120, 40)

    try {
      await app.press('\t')
      expect(app.text()).toContain('TOPICS')
      await app.press('Germany')
      expect(app.text()).toContain('Germany · Consumer inflation')
      await app.press('\r')
      expect(app.request.mock.calls.some(([method]) => method === 'market.selection.apply')).toBe(false)
      await app.press('\u0013') // Ctrl+S reviews selected changes
      expect(app.text()).toContain('1 additions')
      await app.press('\u001b')
      await app.press('\u001b')
      expect(app.cancel).toHaveBeenCalledOnce()
      expect(app.request.mock.calls.some(([method]) => method === 'market.selection.apply')).toBe(false)
    } finally {
      app.close()
    }
  })

  it.each([
    [120, 40],
    [80, 24]
  ])('previews before applying at %i×%i', async (cols, rows) => {
    const app = await mount(cols, rows)

    try {
      expect(app.text()).toContain('Global starter set')
      await app.press('\r')
      expect(app.text()).toContain('Germany')
      expect(app.request.mock.calls.filter(([method]) => method === 'market.selection.apply')).toHaveLength(0)
      await app.press('\r')
      expect(app.saved).toHaveBeenCalledTimes(1)
    } finally {
      app.close()
    }
  })

  it('Escape abandons pending series changes without a write', async () => {
    const app = await mount(120, 40)

    try {
      await app.press('\t')
      expect(app.text()).toContain('Germany')
      await app.press('\r')
      await app.press('\u001b')
      expect(app.cancel).toHaveBeenCalledTimes(1)
      expect(
        app.request.mock.calls.some(
          ([method]) => method === 'market.selection.apply' || method === 'market.selection.update'
        )
      ).toBe(false)
    } finally {
      app.close()
    }
  })
})

const liveHit = {
  id: 'custom:yahoo:NEW',
  catalog_id: null,
  provider: 'yahoo',
  symbol: 'NEW',
  name: 'New listing beyond defaults',
  category: 'stocks',
  region: '',
  country: null,
  kind: 'quote',
  frequency: 'daily',
  unit: 'USD',
  source_url: '',
  description: 'Live symbol lookup'
}

it.each([
  [120, 40],
  [80, 24]
])('filters use Shift+Tab and arrows, Escape returns to results at %i×%i', async (cols, rows) => {
  const app = await mount(cols, rows)

  try {
    await app.press('\t')
    expect(app.text()).not.toContain('Ctrl+K Kind')
    await app.press('\u001b[Z') // Shift+Tab
    expect(app.text()).toContain('Backspace Reset')
    expect(app.text()).toContain('TOPICS')
    expect(app.text()).toContain('Germany · Consumer inflation')

    await app.press('\u001b[B')
    expect(app.text()).toContain('Region: Europe')
    await app.press('\u001b[C')
    await app.press('\u001b[B')
    expect(app.text()).toContain('Country: Germany')
    expect(app.text()).toContain('Region: All')
    await app.press('\u001b[C')
    await app.press('\u001b[B')
    expect(app.text()).toContain('Kind: observation')
    await app.press('\u001b[C')
    await app.press('\u001b[B')
    expect(app.text()).toContain('Source: Official Statistics')
    await app.press('\u007f')
    expect(app.text()).toContain('Country: All')
    await app.press('\u001b')
    expect(app.cancel).not.toHaveBeenCalled()
    await app.press('Germany')
    expect(app.text()).toContain('Consumer inflation')
  } finally {
    app.close()
  }
})

it('selects a live result and includes its identity in the same review transaction', async () => {
  const app = await mount(120, 40, async () => ({ results: [liveHit], statuses: [] }))

  try {
    await app.press('\t')
    await app.press('NEW')
    await new Promise(resolve => setTimeout(resolve, 400))
    expect(app.text()).toContain('New listing beyond defaults')
    await app.press('\r')
    await app.press('\u0013')
    const call = app.request.mock.calls.find(([method]) => method === 'market.selection.preview')
    expect(call?.[1]).toMatchObject({
      edit: { add: [], custom_add: [{ provider: 'yahoo', symbol: 'NEW', unit: 'USD' }] }
    })
  } finally {
    app.close()
  }
})

it('late discovery results cannot replace the current query', async () => {
  let answer: ((value: unknown) => void) | undefined

  const app = await mount(120, 40, async params => {
    if ((params as { query: string }).query === 'old') {
      return new Promise(resolve => {
        answer = resolve
      })
    }

    return { results: [], statuses: [] }
  })

  try {
    await app.press('\t')
    await app.press('old')
    await new Promise(resolve => setTimeout(resolve, 400))
    await app.press('new')
    answer?.({ results: [liveHit], statuses: [] })
    await tick()
    expect(app.text()).not.toContain('New listing beyond defaults')
  } finally {
    app.close()
  }
})
