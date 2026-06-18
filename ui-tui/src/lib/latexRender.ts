// A pragmatic LaTeX → terminal renderer. LaTeX can't be typeset in a TUI, but
// most of a paper's *structure* and prose can be made readable: titles,
// sections, lists, emphasis, and the common math symbols mapped to Unicode.
// Pure + unit-tested; the view maps the returned blocks to themed Text.

export type LatexBlockKind = 'blank' | 'heading' | 'item' | 'math' | 'rule' | 'text' | 'verbatim'

export interface LatexBlock {
  kind: LatexBlockKind
  level?: number // heading depth (0 title, 1 section, 2 subsection, 3+ deeper); item indent
  text: string
}

// Common math/text macros → Unicode. Longest names first so `\subseteq` isn't
// eaten by `\sub…`; the regex below sorts by length anyway.
const SYMBOLS: Record<string, string> = {
  Delta: 'Δ',
  Gamma: 'Γ',
  Lambda: 'Λ',
  Omega: 'Ω',
  Phi: 'Φ',
  Pi: 'Π',
  Psi: 'Ψ',
  Sigma: 'Σ',
  Theta: 'Θ',
  alpha: 'α',
  approx: '≈',
  beta: 'β',
  bullet: '•',
  cdot: '·',
  chi: 'χ',
  circ: '∘',
  cup: '∪',
  cap: '∩',
  ddots: '⋱',
  delta: 'δ',
  div: '÷',
  dots: '…',
  ldots: '…',
  cdots: '⋯',
  emptyset: '∅',
  epsilon: 'ε',
  equiv: '≡',
  eta: 'η',
  exists: '∃',
  forall: '∀',
  gamma: 'γ',
  geq: '≥',
  ge: '≥',
  gg: '≫',
  in: '∈',
  infty: '∞',
  int: '∫',
  lambda: 'λ',
  langle: '⟨',
  rangle: '⟩',
  leftarrow: '←',
  leq: '≤',
  le: '≤',
  ll: '≪',
  mapsto: '↦',
  mu: 'μ',
  nabla: '∇',
  neq: '≠',
  ne: '≠',
  neg: '¬',
  notin: '∉',
  nu: 'ν',
  odot: '⊙',
  oplus: '⊕',
  otimes: '⊗',
  partial: '∂',
  phi: 'φ',
  pi: 'π',
  pm: '±',
  prod: '∏',
  propto: '∝',
  psi: 'ψ',
  rho: 'ρ',
  rightarrow: '→',
  to: '→',
  Rightarrow: '⇒',
  Leftarrow: '⇐',
  leftrightarrow: '↔',
  Leftrightarrow: '⇔',
  sigma: 'σ',
  sim: '∼',
  subset: '⊂',
  subseteq: '⊆',
  sum: '∑',
  supset: '⊃',
  supseteq: '⊇',
  tau: 'τ',
  theta: 'θ',
  times: '×',
  varepsilon: 'ε',
  varphi: 'φ',
  vdots: '⋮',
  wedge: '∧',
  vee: '∨',
  xi: 'ξ',
  zeta: 'ζ',
  sqrt: '√',
  angle: '∠',
  perp: '⊥',
  parallel: '∥',
  star: '⋆'
}

const SUP: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
  '+': '⁺', '-': '⁻', n: 'ⁿ', i: 'ⁱ', T: 'ᵀ'
}

const SUB: Record<string, string> = {
  '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
  '+': '₊', '-': '₋', a: 'ₐ', e: 'ₑ', i: 'ᵢ', j: 'ⱼ', n: 'ₙ', t: 'ₜ', x: 'ₓ'
}

const mapScript = (body: string, table: Record<string, string>): null | string => {
  const out: string[] = []

  for (const ch of body) {
    if (!(ch in table)) {
      return null
    }

    out.push(table[ch])
  }

  return out.join('')
}

const SYMBOL_RE = new RegExp(`\\\\(${Object.keys(SYMBOLS).sort((a, b) => b.length - a.length).join('|')})(?![a-zA-Z])`, 'g')

// Inline transforms applied to a run of text/math: emphasis → content, symbols →
// Unicode, super/subscripts → Unicode where every char maps, escaped chars, and
// strip remaining unknown control sequences (keeping their braced argument).
export const inlineLatex = (input: string): string => {
  let s = input

  // \href{url}{label} → label (url) ; \url{u} → u ; \texttt/\textbf/\textit/\emph{x} → x
  s = s.replace(/\\href\{([^}]*)\}\{([^}]*)\}/g, (_m, url, label) => `${label} (${url})`)
  s = s.replace(/\\url\{([^}]*)\}/g, (_m, url) => url)
  s = s.replace(/\\(?:textbf|textit|texttt|emph|textsf|textrm|mathrm|mathbf|mathit|text|textsc|underline)\{([^{}]*)\}/g, '$1')

  // Symbols (math + text macros)
  s = s.replace(SYMBOL_RE, (_m, name) => SYMBOLS[name])
  s = s.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, (_m, a, b) => `(${a})/(${b})`)

  // Super/subscripts: ^{...} / _{...} or single char. Convert only when every
  // character has a Unicode form; otherwise fall back to ^/_ notation.
  s = s.replace(/\^\{([^{}]+)\}|\^(\S)/g, (_m, braced, single) => {
    const body = braced ?? single

    return mapScript(body, SUP) ?? `^${body}`
  })
  s = s.replace(/_\{([^{}]+)\}|_(\S)/g, (_m, braced, single) => {
    const body = braced ?? single

    return mapScript(body, SUB) ?? `_${body}`
  })

  // Escaped specials and spacing
  s = s
    .replace(/\\(\$|%|&|#|_|\{|\})/g, '$1')
    .replace(/\\,|\\;|\\:|\\!|\\ |~/g, ' ')
    .replace(/``|''/g, '"')
    .replace(/---/g, '—')
    .replace(/--/g, '–')

  // Layout / reference / graphics macros: drop the command AND its argument
  // (their content isn't prose). Everything else keeps its braced content.
  s = s.replace(
    /\\(?:vspace|hspace|vskip|hskip|vfill|hfill|label|ref|eqref|pageref|autoref|cite[a-zA-Z]*|includegraphics|setlength|addtolength|setcounter|input|include|usepackage|documentclass|newcommand|renewcommand|bibliography|bibliographystyle|index|hyphenation|graphicspath)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?/g,
    ''
  )

  // Drop any remaining \command but keep a braced argument's content.
  s = s.replace(/\\[a-zA-Z]+\*?\{([^{}]*)\}/g, '$1')
  s = s.replace(/\\[a-zA-Z]+\*?/g, '')
  s = s.replace(/[{}]/g, '')

  return s.replace(/[ \t]{2,}/g, ' ').trimEnd()
}

const stripComment = (line: string): string => {
  // Remove an unescaped % to end of line.
  const m = /(^|[^\\])%/.exec(line)

  return m ? line.slice(0, m.index + m[1].length) : line
}

const HEADING_RE = /^\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\{(.*)\}\s*$/

const HEADING_LEVEL: Record<string, number> = {
  chapter: 1,
  paragraph: 4,
  part: 1,
  section: 1,
  subsection: 2,
  subsubsection: 3
}

// Render LaTeX source into a flat list of readable blocks.
export const renderLatex = (source: string): LatexBlock[] => {
  // Prefer the document body, but pull \title/\author/\date from the preamble.
  const titleM = /\\title\{([\s\S]*?)\}/.exec(source)
  const authorM = /\\author\{([\s\S]*?)\}/.exec(source)
  const bodyM = /\\begin\{document\}([\s\S]*?)\\end\{document\}/.exec(source)
  const body = bodyM ? bodyM[1] : source

  const blocks: LatexBlock[] = []

  if (titleM) {
    blocks.push({ kind: 'heading', level: 0, text: inlineLatex(titleM[1].replace(/\\\\/g, ' ').trim()) })
  }

  if (authorM) {
    blocks.push({ kind: 'text', text: inlineLatex(authorM[1].replace(/\\\\|\\and/g, ' · ').trim()) })
    blocks.push({ kind: 'blank', text: '' })
  }

  const lines = body.split('\n')
  let inVerbatim = false
  let listDepth = 0
  let para: string[] = []

  const flushPara = () => {
    if (para.length) {
      const text = inlineLatex(para.join(' ').replace(/\\\\/g, ' ').trim())

      if (text.trim()) {
        blocks.push({ kind: 'text', text })
      }

      para = []
    }
  }

  for (const raw of lines) {
    const line = inVerbatim ? raw : stripComment(raw)
    const trimmed = line.trim()

    if (/\\begin\{(verbatim|lstlisting|minted)\}/.test(trimmed)) {
      flushPara()
      inVerbatim = true

      continue
    }

    if (inVerbatim) {
      if (/\\end\{(verbatim|lstlisting|minted)\}/.test(trimmed)) {
        inVerbatim = false
      } else {
        blocks.push({ kind: 'verbatim', text: raw })
      }

      continue
    }

    if (!trimmed) {
      flushPara()
      blocks.push({ kind: 'blank', text: '' })

      continue
    }

    const heading = HEADING_RE.exec(trimmed)

    if (heading) {
      flushPara()
      blocks.push({ kind: 'heading', level: HEADING_LEVEL[heading[1]] ?? 3, text: inlineLatex(heading[2]) })

      continue
    }

    if (/\\begin\{(itemize|enumerate|description)\}/.test(trimmed)) {
      flushPara()
      listDepth += 1

      continue
    }

    if (/\\end\{(itemize|enumerate|description)\}/.test(trimmed)) {
      flushPara()
      listDepth = Math.max(0, listDepth - 1)

      continue
    }

    if (/^\\item\b/.test(trimmed)) {
      flushPara()
      const text = inlineLatex(trimmed.replace(/^\\item\s*(\[[^\]]*\])?\s*/, ''))
      blocks.push({ kind: 'item', level: Math.max(1, listDepth), text })

      continue
    }

    // Display math: \[ ... \], $$ ... $$, or equation/align environments (single line).
    const display = /^\\\[(.*)\\\]$|^\$\$(.*)\$\$$/.exec(trimmed)

    if (display) {
      flushPara()
      blocks.push({ kind: 'math', text: inlineLatex((display[1] ?? display[2] ?? '').trim()) })

      continue
    }

    if (/\\begin\{(equation|align|gather|displaymath)\*?\}/.test(trimmed)) {
      flushPara()

      continue // the math content lands as math lines below until \end
    }

    if (/\\end\{(equation|align|gather|displaymath)\*?\}/.test(trimmed)) {
      continue
    }

    if (/^\\(hrule|rule|hline|midrule|toprule|bottomrule)/.test(trimmed)) {
      flushPara()
      blocks.push({ kind: 'rule', text: '' })

      continue
    }

    if (/^\\(maketitle|tableofcontents|newpage|clearpage|centering|begin|end)\b/.test(trimmed)) {
      flushPara()

      continue
    }

    para.push(trimmed)
  }

  flushPara()

  // Collapse 3+ blanks to one.
  const out: LatexBlock[] = []

  for (const b of blocks) {
    if (b.kind === 'blank' && out[out.length - 1]?.kind === 'blank') {
      continue
    }

    out.push(b)
  }

  return out
}
