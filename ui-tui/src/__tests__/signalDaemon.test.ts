import { createServer } from 'node:net'

import { afterEach, describe, expect, it } from 'vitest'

import { daemonArgs, findFreePort, parseMajorVersion } from '../lib/signalDaemon.js'

describe('parseMajorVersion', () => {
  it('reads modern and legacy Java + signal-cli version strings', () => {
    expect(parseMajorVersion('openjdk version "21.0.1" 2024-...')).toBe(21)
    expect(parseMajorVersion('java version "17.0.9"')).toBe(17)
    expect(parseMajorVersion('java version "1.8.0_392"')).toBe(8)
    expect(parseMajorVersion('signal-cli 0.13.4')).toBe(0)
    expect(parseMajorVersion('')).toBe(0)
  })
})

describe('daemonArgs', () => {
  it('builds the signal-cli daemon argv with the chosen port (no hardcoding)', () => {
    expect(daemonArgs('+15550000000', 8123)).toEqual([
      '-a',
      '+15550000000',
      'daemon',
      '--http',
      '127.0.0.1:8123'
    ])
  })
})

describe('findFreePort', () => {
  const servers: ReturnType<typeof createServer>[] = []
  afterEach(() => {
    for (const s of servers.splice(0)) {
      s.close()
    }
  })

  it('returns the preferred port when it is free', async () => {
    // Grab an ephemeral free port, release it, then ask for it back.
    const port = await new Promise<number>(resolve => {
      const s = createServer()
      s.listen(0, '127.0.0.1', () => {
        const addr = s.address()
        const p = addr && typeof addr === 'object' ? addr.port : 0
        s.close(() => resolve(p))
      })
    })

    expect(await findFreePort(port)).toBe(port)
  })

  it('falls back to a different free port when the preferred one is taken', async () => {
    const taken = await new Promise<number>(resolve => {
      const s = createServer()
      servers.push(s)
      s.listen(0, '127.0.0.1', () => {
        const addr = s.address()
        resolve(addr && typeof addr === 'object' ? addr.port : 0)
      })
    })

    const got = await findFreePort(taken)
    expect(got).toBeGreaterThan(0)
    expect(got).not.toBe(taken)
  })
})
