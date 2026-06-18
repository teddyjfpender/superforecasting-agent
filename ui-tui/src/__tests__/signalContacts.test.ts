import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterAll, beforeEach, describe, expect, it } from 'vitest'

import {
  type ContactBook,
  isValidNumber,
  loadContactBook,
  normalizeNumber,
  saveContactBook,
  upsertContact
} from '../lib/signalContacts.js'

const tmp = mkdtempSync(join(tmpdir(), 'signal-contacts-'))
const prevHome = process.env.SUPERFORECASTING_AGENT_HOME

beforeEach(() => {
  process.env.SUPERFORECASTING_AGENT_HOME = tmp
})

afterAll(() => {
  rmSync(tmp, { force: true, recursive: true })

  if (prevHome === undefined) {
    delete process.env.SUPERFORECASTING_AGENT_HOME
  } else {
    process.env.SUPERFORECASTING_AGENT_HOME = prevHome
  }
})

describe('number normalization', () => {
  it('strips formatting but keeps a leading +', () => {
    expect(normalizeNumber('+1 (267) 455-3945')).toBe('+12674553945')
    expect(normalizeNumber('  +44 7700 900123 ')).toBe('+447700900123')
  })

  it('validates E.164', () => {
    expect(isValidNumber('+12674553945')).toBe(true)
    expect(isValidNumber('+1 (267) 455-3945')).toBe(true)
    expect(isValidNumber('2674553945')).toBe(false) // no +
    expect(isValidNumber('+123')).toBe(false) // too short
  })
})

describe('contact book', () => {
  it('upsert keeps prior fields and addedAt, fills new ones', () => {
    let book: ContactBook = {}
    book = upsertContact(book, { addedAt: 100, chatId: '+12674553945', name: 'Levy', number: '+12674553945' })
    expect(book['+12674553945'].name).toBe('Levy')
    // a later, unnamed sighting must not wipe the saved name
    book = upsertContact(book, { chatId: '+12674553945' })
    expect(book['+12674553945'].name).toBe('Levy')
    expect(book['+12674553945'].addedAt).toBe(100)
  })

  it('round-trips through disk', () => {
    const book = upsertContact({}, { addedAt: 7, chatId: '+12674553945', name: 'Levy', number: '+12674553945' })
    expect(saveContactBook(book)).toBe(true)
    const loaded = loadContactBook()
    expect(loaded['+12674553945']).toEqual({ addedAt: 7, chatId: '+12674553945', name: 'Levy', number: '+12674553945' })
  })

  it('returns {} for a missing file', () => {
    expect(loadContactBook(join(tmp, 'nope.json'))).toEqual({})
  })
})
