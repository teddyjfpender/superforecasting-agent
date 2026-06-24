import { describe, expect, it } from 'vitest'

import { classifyVoiceIntent, normalizeTranscript, resolveVoiceSubmission } from '../lib/voiceIntent.js'

describe('voiceIntent', () => {
  it('maps safe spoken commands to slash commands (case/punctuation tolerant)', () => {
    expect(classifyVoiceIntent('voice off')).toEqual({ kind: 'command', command: '/voice off', destructive: false })
    expect(classifyVoiceIntent('Open Markets.')).toEqual({ kind: 'command', command: '/markets', destructive: false })
    expect(normalizeTranscript('  Show Forecasts!  ')).toBe('show forecasts')
  })

  it('passes an explicit slash command straight through', () => {
    expect(classifyVoiceIntent('/help')).toEqual({ kind: 'command', command: '/help', destructive: false })
  })

  it('recognises destructive intents but never auto-fires them', () => {
    expect(classifyVoiceIntent('cancel')).toEqual({ kind: 'command', command: '/cancel', destructive: true })
    // resolveVoiceSubmission submits a destructive intent VERBATIM (dictation), not as a command
    expect(resolveVoiceSubmission('cancel')).toEqual({ submit: 'cancel', isCommand: false })
  })

  it('treats free speech as dictation', () => {
    expect(classifyVoiceIntent('what is the forecast for the senate race')).toEqual({ kind: 'dictation' })
    expect(resolveVoiceSubmission('what is the forecast')).toEqual({ submit: 'what is the forecast', isCommand: false })
  })

  it('routes a safe command to its slash command on submit', () => {
    expect(resolveVoiceSubmission('go to markets')).toEqual({ submit: '/markets', isCommand: true })
  })

  it('empty transcript is dictation', () => {
    expect(classifyVoiceIntent('   ')).toEqual({ kind: 'dictation' })
  })
})
