import { createHash } from 'node:crypto'
/** Recoverable unsaved edits are local to the active TUI profile. */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { forecastHomeDir } from './forecastHome.js'
export interface DocumentDraft {
  content: string
  original: string
}

const pathFor = (identity: string) =>
  join(forecastHomeDir(), 'document-drafts', `${createHash('sha256').update(identity).digest('hex')}.json`)

export const readDocumentDraft = (identity: string): DocumentDraft | null => {
  try {
    const raw = JSON.parse(readFileSync(pathFor(identity), 'utf8')) as DocumentDraft

    return typeof raw.content === 'string' && typeof raw.original === 'string' ? raw : null
  } catch {
    return null
  }
}

export const saveDocumentDraft = (identity: string, draft: DocumentDraft): void => {
  const path = pathFor(identity)
  mkdirSync(dirname(path), { recursive: true })
  const tmp = `${path}.${process.pid}.tmp`
  writeFileSync(tmp, JSON.stringify(draft), { mode: 0o600 })
  renameSync(tmp, path)
}
