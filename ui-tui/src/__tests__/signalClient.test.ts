import { describe, expect, it } from 'vitest'

import { parseContacts, parseEnvelope, parseGroups } from '../lib/signalClient.js'

describe('parseContacts', () => {
  it('extracts id + best-effort name and skips self/unidentifiable', () => {
    const out = parseContacts(
      [
        { number: '+15551112222', profile: { givenName: 'Ada', familyName: 'L' } },
        { number: '+15553334444', name: 'Saved Name' },
        { uuid: 'abc-uuid' },
        { number: '+15550000000' }, // self
        { nonsense: true }
      ],
      '+15550000000'
    )

    expect(out).toHaveLength(3)
    expect(out[0]).toEqual({ id: '+15551112222', name: 'Ada L' })
    expect(out[1].name).toBe('Saved Name')
    expect(out[2]).toEqual({ id: 'abc-uuid', name: 'abc-uuid' })
  })

  it('returns [] for non-array input', () => {
    expect(parseContacts(null)).toEqual([])
    expect(parseContacts({})).toEqual([])
  })
})

describe('parseGroups', () => {
  it('reads id, name and member count', () => {
    const out = parseGroups([
      { id: 'Z3JvdXA=', members: [{}, {}, {}], name: 'Forecast Crew' },
      { groupId: 'b2xk', name: '' }
    ])

    expect(out[0]).toEqual({ id: 'Z3JvdXA=', memberCount: 3, name: 'Forecast Crew' })
    expect(out[1]).toEqual({ id: 'b2xk', memberCount: 0, name: 'Signal group' })
  })
})

describe('parseEnvelope', () => {
  const self = '+15550000000'

  it('parses an inbound direct message', () => {
    const msg = parseEnvelope(
      {
        envelope: {
          dataMessage: { message: 'hey there', timestamp: 1700000000000 },
          sourceNumber: '+15551112222',
          timestamp: 1700000000000
        }
      },
      self
    )

    expect(msg).toEqual({
      attachments: 0,
      author: '+15551112222',
      chatId: '+15551112222',
      fromMe: false,
      text: 'hey there',
      timestamp: 1700000000000
    })
  })

  it('routes a groupV2 message to a group chat id', () => {
    const msg = parseEnvelope({
      envelope: {
        dataMessage: { groupV2: { id: 'R1JQ' }, message: 'team update', timestamp: 5 },
        sourceNumber: '+15551112222'
      }
    })

    expect(msg?.chatId).toBe('group:R1JQ')
  })

  it('captures own sends mirrored via syncMessage.sentMessage as fromMe', () => {
    const msg = parseEnvelope(
      {
        envelope: {
          syncMessage: { sentMessage: { destinationNumber: '+15553334444', message: 'sent from phone', timestamp: 9 } }
        }
      },
      self
    )

    expect(msg).toEqual({
      attachments: 0,
      author: 'me',
      chatId: '+15553334444',
      fromMe: true,
      text: 'sent from phone',
      timestamp: 9
    })
  })

  it('counts attachments and tolerates empty text', () => {
    const msg = parseEnvelope({
      envelope: { dataMessage: { attachments: [{}, {}], message: '', timestamp: 1 }, sourceNumber: '+1555' }
    })

    expect(msg?.attachments).toBe(2)
    expect(msg?.text).toBe('')
  })

  it('returns null for receipts/typing/empty envelopes', () => {
    expect(parseEnvelope({ envelope: { receiptMessage: {}, sourceNumber: '+1555' } })).toBeNull()
    expect(parseEnvelope({ envelope: { typingMessage: {}, sourceNumber: '+1555' } })).toBeNull()
    expect(parseEnvelope(null)).toBeNull()
  })
})
