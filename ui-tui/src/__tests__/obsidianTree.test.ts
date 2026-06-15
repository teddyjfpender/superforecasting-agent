import { describe, expect, it } from 'vitest'

import { buildNoteRows } from '../components/obsidianView.js'
import type { ObsidianNote } from '../gatewayTypes.js'

const notes: ObsidianNote[] = [
  { rel_path: 'Forecasting/Knowledge/Bayesian Updating.md', title: 'Bayesian Updating' },
  { rel_path: 'Forecasting/Knowledge/Calibration and Scoring.md', title: 'Calibration and Scoring' },
  { rel_path: 'Forecasting/Index.md', title: 'Forecasting Desk' }
]

describe('buildNoteRows (directory tree)', () => {
  it('groups notes under their folders with depth, expanded by default', () => {
    const rows = buildNoteRows(notes, new Set())

    // Top-level: the Forecasting folder.
    expect(rows[0]).toMatchObject({ depth: 0, kind: 'folder', name: 'Forecasting' })

    // Folders sort before notes at each level, so Knowledge (folder) precedes
    // the Index note inside Forecasting.
    const knowledge = rows.find(r => r.kind === 'folder' && r.name === 'Knowledge')
    expect(knowledge).toMatchObject({ depth: 1, path: 'Forecasting/Knowledge' })

    // The two notes live at depth 2 under Knowledge.
    const bayes = rows.find(r => r.name === 'Bayesian Updating')
    expect(bayes).toMatchObject({ depth: 2, kind: 'note' })

    // The Index note sits at depth 1 under Forecasting.
    expect(rows.find(r => r.name === 'Forecasting Desk')).toMatchObject({ depth: 1, kind: 'note' })
  })

  it('collapsing a folder hides its descendants', () => {
    const collapsedAll = buildNoteRows(notes, new Set(['Forecasting']))
    // Only the Forecasting folder row remains; nothing under it.
    expect(collapsedAll).toHaveLength(1)
    expect(collapsedAll[0]).toMatchObject({ kind: 'folder', expanded: false, name: 'Forecasting' })

    const collapsedKnowledge = buildNoteRows(notes, new Set(['Forecasting/Knowledge']))
    // Knowledge's two notes are hidden, but the Index note stays.
    expect(collapsedKnowledge.some(r => r.name === 'Bayesian Updating')).toBe(false)
    expect(collapsedKnowledge.some(r => r.name === 'Forecasting Desk')).toBe(true)
  })
})
