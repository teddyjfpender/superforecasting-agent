import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { activeSessionFileFromEnv, writeActiveSessionFile } from '../app/useSessionLifecycle.js'

describe('writeActiveSessionFile', () => {
  let dir = ''

  afterEach(() => {
    if (dir) {
      rmSync(dir, { force: true, recursive: true })
      dir = ''
    }
  })

  it('writes the actual resumed session id for the shell exit summary', () => {
    dir = mkdtempSync(join(tmpdir(), 'forecast-tui-active-'))
    const path = join(dir, 'active.json')

    writeActiveSessionFile('actual_session', path)

    expect(JSON.parse(readFileSync(path, 'utf8'))).toEqual({ session_id: 'actual_session' })
  })

  it('prefers forecast-native active-session env aliases', () => {
    expect(
      activeSessionFileFromEnv({
        HERMES_TUI_ACTIVE_SESSION_FILE: '/tmp/legacy.json',
        FORECAST_TUI_ACTIVE_SESSION_FILE: '/tmp/forecast.json',
        SUPERFORECASTING_AGENT_TUI_ACTIVE_SESSION_FILE: '/tmp/native.json'
      })
    ).toBe('/tmp/native.json')
    expect(
      activeSessionFileFromEnv({
        HERMES_TUI_ACTIVE_SESSION_FILE: '/tmp/legacy.json',
        FORECAST_TUI_ACTIVE_SESSION_FILE: '/tmp/forecast.json'
      })
    ).toBe('/tmp/forecast.json')
  })

  it('creates a replacement before closing the active session', () => {
    const source = readFileSync(new URL('../app/useSessionLifecycle.ts', import.meta.url), 'utf8')

    expect(source.indexOf("rpc<SessionCreateResponse>('session.create'")).toBeLessThan(
      source.indexOf('await closeSession(previousSid)')
    )
  })
})
