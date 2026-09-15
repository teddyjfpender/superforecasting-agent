import { describe, expect, it } from 'vitest'

import { searchDirectory } from '../lib/messagingSearch.js'
import { parseContacts, parseEnvelope } from '../lib/signalClient.js'
import { isValidNumber, upsertContact } from '../lib/signalContacts.js'
import type { SignalCache } from '../lib/signalStore.js'

const book = {
  '+15550000001': { chatId: '+15550000001', addedAt: 1, name: 'José Silva', aliases: ['Pepe'] },
  '+15550000002': { chatId: '+15550000002', addedAt: 2, name: 'CPI Research' },
  'group:team': { chatId: 'group:team', addedAt: 3, name: 'Desk' }
}

const cache: SignalCache = {
  '+15550000001': [
    {
      chatId: '+15550000001',
      author: '+15550000001',
      text: 'The CPI release is tomorrow',
      timestamp: 1,
      fromMe: false,
      attachments: 0
    },
    { chatId: '+15550000001', author: 'me', text: 'Thank you', timestamp: 2, fromMe: true, attachments: 0 }
  ]
}

describe('private contact and conversation search', () => {
  it('finds aliases, accents, partial numbers and name typos', () => {
    for (const query of ['jose', 'pepe', 'silv', 'silva', 'silva jose', '15550000001']) {
      expect(searchDirectory(book, cache, {}, query)[0]?.id).toBe('+15550000001')
    }

    expect(searchDirectory(book, cache, {}, 'silba')[0]?.name).toBe('José Silva')
  })
  it('matches topic intent against older saved messages and explains the match', () => {
    const results = searchDirectory(book, cache, {}, 'who discussed inflation')
    expect(results.map(r => r.id)).toEqual(['+15550000001'])
    expect(results[0].snippet).toBe('The CPI release is tomorrow')
    expect(searchDirectory(book, cache, {}, 'inflation travel')).toEqual([])
  })
  it('ranks literal names first, applies scopes and includes draft-only contacts', () => {
    expect(searchDirectory(book, cache, {}, 'CPI')[0].name).toBe('CPI Research')
    expect(searchDirectory(book, cache, {}, '', 'Chats').map(r => r.id)).toEqual(['+15550000001'])
    expect(searchDirectory(book, cache, {}, '', 'Groups').map(r => r.id)).toEqual(['group:team'])
    expect(searchDirectory(book, cache, { '+15550000003': { draft: 'saved', unread: true } }, '', 'Unread')[0].id).toBe(
      '+15550000003'
    )
  })
  it('never treats a mixed name/number query as a new recipient', () => {
    expect(isValidNumber('José +15550000001')).toBe(false)
    expect(isValidNumber('+1 (555) 000-0001')).toBe(true)
  })
})
it('parses current Signal nicknames, profile alternatives and privacy-preserving UUID sends', () => {
  const contact = parseContacts([
    {
      number: '+15550000001',
      nickGivenName: 'Pepe',
      nickFamilyName: 'S',
      name: 'José',
      profile: { givenName: 'Joe', familyName: 'Silva' }
    }
  ])[0]

  expect(contact.name).toBe('Pepe S')
  expect(contact.aliases).toEqual(['Pepe S', 'José', 'Joe Silva'])
  expect(
    parseEnvelope({
      syncMessage: { sentMessage: { destinationUuid: 'recipient-uuid', timestamp: 2, message: 'from phone' } }
    })?.chatId
  ).toBe('recipient-uuid')
  expect(
    parseEnvelope({ sourceNumber: '+15550000001', sourceName: 'José', dataMessage: { message: 'Hi', timestamp: 3 } })
      ?.authorName
  ).toBe('José')
})
it('refreshes synced names without freezing them on selection or overwriting manual labels', () => {
  let saved = upsertContact({}, { chatId: 'id', name: 'First', nameSource: 'signal' })
  saved = upsertContact(saved, { chatId: 'id' })
  saved = upsertContact(saved, { chatId: 'id', name: 'Updated', nameSource: 'signal' })
  expect(saved.id.name).toBe('Updated')
  saved = upsertContact(saved, { chatId: 'id', name: 'My label' })
  saved = upsertContact(saved, { chatId: 'id', name: 'Remote', nameSource: 'signal', aliases: ['Remote'] })
  expect(saved.id.name).toBe('My label')
  expect(saved.id.aliases).toEqual(['Remote'])
})
