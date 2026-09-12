import { atom } from 'nanostores'

import type { GatewayEvent } from '../gatewayTypes.js'
import { WireEvent } from '../protocol/generated.js'

export interface RunningCommand {
  id: string
  sessionId: string
  name: string
  output: string
  cancelling: boolean
}

export const $commands = atom<RunningCommand[]>([])
const finished = new Set<string>()

export function applyCommandEvent(event: GatewayEvent): boolean {
  if (
    ![WireEvent.COMMAND_STARTED, WireEvent.COMMAND_OUTPUT, WireEvent.COMMAND_FINISHED].some(type => type === event.type)
  ) {
    return false
  }

  const data = event.payload as Record<string, unknown> | undefined

  if (!event.session_id || !data || typeof data.command_id !== 'string' || !data.command_id) {
    return true
  }

  const key = `${event.session_id}:${data.command_id}`

  if (finished.has(key)) {
    return true
  }

  const current = $commands.get()
  const matches = (command: RunningCommand) => command.id === data.command_id && command.sessionId === event.session_id

  if (event.type === WireEvent.COMMAND_STARTED && typeof data.name === 'string' && !current.some(matches)) {
    $commands.set([
      ...current,
      { id: data.command_id, sessionId: event.session_id, name: data.name, output: '', cancelling: false }
    ])
  } else if (event.type === WireEvent.COMMAND_OUTPUT && typeof data.text === 'string') {
    const text = data.text
    $commands.set(
      current.map(command =>
        matches(command) ? { ...command, output: (command.output + text).slice(-4096) } : command
      )
    )
  } else if (
    event.type === WireEvent.COMMAND_FINISHED &&
    ['finished', 'failed', 'cancelled'].includes(String(data.status))
  ) {
    finished.add(key)

    if (finished.size > 64) {
      finished.delete(finished.values().next().value!)
    }

    $commands.set(current.filter(command => !matches(command)))
  }

  return true
}

export function markCommandsCancelling(sessionId: string, cancelling: boolean) {
  $commands.set(
    $commands.get().map(command => (command.sessionId === sessionId ? { ...command, cancelling } : command))
  )
}

export function clearCommands() {
  $commands.set([])
  finished.clear()
}
