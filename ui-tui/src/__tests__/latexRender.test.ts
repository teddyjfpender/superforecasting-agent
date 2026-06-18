import { describe, expect, it } from 'vitest'

import { inlineLatex, renderLatex } from '../lib/latexRender.js'

describe('inlineLatex', () => {
  it('maps common math symbols to Unicode', () => {
    expect(inlineLatex('\\alpha + \\beta \\leq \\gamma')).toBe('α + β ≤ γ')
    expect(inlineLatex('x \\in \\mathbb{R}, \\sum_{i=1}^{n} a_i')).toContain('∈')
    expect(inlineLatex('a \\times b \\neq c')).toBe('a × b ≠ c')
  })

  it('unwraps emphasis/formatting to their content', () => {
    expect(inlineLatex('\\textbf{bold} and \\emph{em} and \\texttt{code}')).toBe('bold and em and code')
  })

  it('renders href/url readably', () => {
    expect(inlineLatex('see \\href{https://x.com}{the site}')).toBe('see the site (https://x.com)')
    expect(inlineLatex('\\url{https://y.org}')).toBe('https://y.org')
  })

  it('converts super/subscripts when every char maps', () => {
    expect(inlineLatex('x^2')).toBe('x²')
    expect(inlineLatex('a_{12}')).toBe('a₁₂')
    expect(inlineLatex('e^{i}')).toBe('eⁱ')
  })

  it('unescapes specials and strips unknown commands', () => {
    expect(inlineLatex('100\\% \\& more')).toBe('100% & more')
    expect(inlineLatex('\\unknownmacro{kept}')).toBe('kept')
    expect(inlineLatex('\\vspace{1cm}')).toBe('')
  })
})

describe('renderLatex', () => {
  const doc = String.raw`
\documentclass{article}
\title{On Forecasting}
\author{A. Tetlock \and B. Mellers}
\begin{document}
\maketitle
% a comment line
\section{Introduction}
Superforecasters update \textbf{often}. Probabilities are $p \in [0,1]$.

\subsection{Method}
\begin{itemize}
  \item Decompose the question
  \item Update on evidence
\end{itemize}

\[ E[X] = \sum_i p_i x_i \]
\begin{verbatim}
raw code line
\end{verbatim}
\end{document}
`

  const blocks = renderLatex(doc)

  it('extracts the title + author as the first blocks', () => {
    expect(blocks[0]).toEqual({ kind: 'heading', level: 0, text: 'On Forecasting' })
    expect(blocks[1].kind).toBe('text')
    expect(blocks[1].text).toContain('Tetlock')
  })

  it('captures section/subsection headings with levels', () => {
    const headings = blocks.filter(b => b.kind === 'heading' && (b.level ?? 0) > 0)
    expect(headings.map(h => [h.level, h.text])).toEqual([
      [1, 'Introduction'],
      [2, 'Method']
    ])
  })

  it('renders list items, math, verbatim, and strips comments/maketitle', () => {
    expect(blocks.some(b => b.kind === 'item' && b.text === 'Decompose the question')).toBe(true)
    expect(blocks.some(b => b.kind === 'math' && b.text.includes('∑'))).toBe(true)
    expect(blocks.some(b => b.kind === 'verbatim' && b.text.includes('raw code line'))).toBe(true)
    expect(blocks.some(b => b.text.includes('comment'))).toBe(false)
    expect(blocks.some(b => b.text.includes('maketitle'))).toBe(false)
  })

  it('handles bare source with no document environment', () => {
    const out = renderLatex('Just a line with \\alpha.')
    expect(out.some(b => b.kind === 'text' && b.text.includes('α'))).toBe(true)
  })
})
