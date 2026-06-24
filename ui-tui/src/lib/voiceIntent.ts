/**
 * Voice intent classification: map a spoken transcript to either a COMMAND (a slash
 * command to dispatch) or DICTATION (free text fed to the agent as a turn).
 *
 * v1 is a deterministic, low-latency rule classifier over a small SAFE vocabulary
 * (view switches, voice toggles). It is the seam where a smarter (LLM) classifier can
 * later plug in. Destructive intents (cancel / stop / new session / clear) are
 * RECOGNISED but flagged `destructive` so the caller never auto-fires them without a
 * confirmation step — until that UX exists, the caller treats them as dictation, so a
 * misheard word can never silently cancel a turn or wipe a session.
 */

export type VoiceIntent =
  | { kind: 'command'; command: string; destructive: boolean }
  | { kind: 'dictation' }

// Spoken phrase (normalized) -> slash command. Safe, idempotent navigation/toggles.
const SAFE_COMMANDS: Record<string, string> = {
  'voice off': '/voice off',
  'turn off voice': '/voice off',
  'stop voice': '/voice off',
  'disable voice': '/voice off',
  'voice on': '/voice on',
  'open markets': '/markets',
  'go to markets': '/markets',
  'show markets': '/markets',
  'open forecasts': '/forecasts',
  'go to forecasts': '/forecasts',
  'show forecasts': '/forecasts',
  'show alerts': '/alerts',
  'open alerts': '/alerts',
  'show calendar': '/calendar',
  'open calendar': '/calendar',
  'show help': '/help',
  help: '/help',
}

// Destructive single-word intents: recognised but NOT auto-fired (need confirmation).
const DESTRUCTIVE = new Set(['cancel', 'stop', 'abort', 'new session', 'clear', 'reset'])

/** Normalize a transcript for matching: trim, lowercase, drop trailing punctuation. */
export const normalizeTranscript = (text: string): string =>
  text.trim().toLowerCase().replace(/[.!?,;:]+$/u, '').trim()

export const classifyVoiceIntent = (text: string): VoiceIntent => {
  const raw = (text ?? '').trim()
  if (!raw) return { kind: 'dictation' }
  // an explicitly spoken/typed slash command passes straight through
  if (raw.startsWith('/')) return { kind: 'command', command: raw, destructive: false }

  const norm = normalizeTranscript(raw)
  const safe = SAFE_COMMANDS[norm]
  if (safe) return { kind: 'command', command: safe, destructive: false }
  if (DESTRUCTIVE.has(norm)) return { kind: 'command', command: `/${norm.replace(/\s+/u, '-')}`, destructive: true }

  return { kind: 'dictation' }
}

/**
 * Resolve a transcript to the string the caller should SUBMIT, plus whether it was a
 * command. Safe commands -> the slash command; dictation OR an unconfirmed destructive
 * command -> the raw text (so destructive intents are never auto-executed in v1).
 */
export const resolveVoiceSubmission = (text: string): { submit: string; isCommand: boolean } => {
  const intent = classifyVoiceIntent(text)
  if (intent.kind === 'command' && !intent.destructive) {
    return { submit: intent.command, isCommand: true }
  }
  return { submit: text.trim(), isCommand: false }
}
