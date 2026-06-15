import { describe, expect, it } from 'vitest'

import { addComment, splitComments } from '../components/obsidianView.js'

const NOTE = `# Bayesian Updating

Body text.

## Work in log-odds

More text.
`

describe('obsidian comments (managed block + rail model)', () => {
  it('a note with no comments parses to an empty list and unchanged body', () => {
    const { body, comments } = splitComments(NOTE)
    expect(comments).toEqual([])
    expect(body).toBe(NOTE)
  })

  it('addComment anchors to a section and keeps it out of the prose', () => {
    const next = addComment(NOTE, 'Work in log-odds', 'needs a citation')
    expect(next).toContain('<!-- comments:begin -->')
    expect(next).toContain('@@ Work in log-odds')
    expect(next).toContain('needs a citation')

    // The body the reader sees no longer contains the comment text…
    const { body, comments } = splitComments(next)
    expect(body).not.toContain('needs a citation')
    expect(body).not.toContain('comments:begin')
    // …but it is parsed back out as an anchored comment.
    expect(comments).toEqual([{ anchor: 'Work in log-odds', text: 'needs a citation' }])
  })

  it('accumulates multiple comments across sections', () => {
    let content = addComment(NOTE, 'Bayesian Updating', 'first')
    content = addComment(content, 'Work in log-odds', 'second')
    const { comments } = splitComments(content)
    expect(comments).toEqual([
      { anchor: 'Bayesian Updating', text: 'first' },
      { anchor: 'Work in log-odds', text: 'second' }
    ])
  })

  it('preserves multi-line comment text', () => {
    const next = addComment(NOTE, 'note', 'line one\nline two')
    const { comments } = splitComments(next)
    expect(comments[0]).toEqual({ anchor: 'note', text: 'line one\nline two' })
  })
})
