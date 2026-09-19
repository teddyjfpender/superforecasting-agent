import { useContext } from 'react'

import { TerminalSizeContext } from '../components/TerminalSizeContext.js'

/** Read the renderer-owned viewport and rerender when it is resized. */
export function useTerminalSize(): { columns: number; rows: number } {
  return (
    useContext(TerminalSizeContext) ?? {
      columns: process.stdout.columns || 80,
      rows: process.stdout.rows || 24
    }
  )
}
