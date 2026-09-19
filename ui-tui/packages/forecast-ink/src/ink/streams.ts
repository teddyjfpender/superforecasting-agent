/** Streams are borrowed from the host; the renderer does not own their sockets. */
import type { Readable, Writable } from 'node:stream'

export type TerminalInput = Readable & {
  isTTY?: boolean
  isRaw?: boolean
  setRawMode?: (enabled: boolean) => unknown
  ref?: () => unknown
  unref?: () => unknown
}

export type TerminalOutput = Writable & {
  isTTY?: boolean
  columns?: number
  rows?: number
}
