import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

// Seed a fresh LaTeX workspace with compilable example documents so the Docs
// reader has real content to render immediately — a standard symbol reference,
// math examples, a sample article, and two templates, across two folders
// (examples/ and templates/).

const SYMBOLS = String.raw`\documentclass{article}
\usepackage{amsmath,amssymb}
\title{LaTeX Symbol Reference}
\author{Outrider Docs}
\date{\today}

\begin{document}
\maketitle

\section{Greek letters}
Lowercase: $\alpha\ \beta\ \gamma\ \delta\ \epsilon\ \zeta\ \eta\ \theta\ \lambda\ \mu\ \nu\ \xi\ \pi\ \rho\ \sigma\ \tau\ \phi\ \chi\ \psi\ \omega$.

Uppercase: $\Gamma\ \Delta\ \Theta\ \Lambda\ \Pi\ \Sigma\ \Phi\ \Psi\ \Omega$.

\section{Binary operators}
$\pm\quad \times\quad \div\quad \cdot\quad \cap\quad \cup\quad \oplus\quad \otimes\quad \odot\quad \wedge\quad \vee$.

\section{Relations}
$\leq\quad \geq\quad \neq\quad \approx\quad \equiv\quad \sim\quad \propto\quad \subset\quad \subseteq\quad \supset\quad \in\quad \notin$.

\section{Arrows}
$\rightarrow\quad \leftarrow\quad \leftrightarrow\quad \Rightarrow\quad \Leftarrow\quad \Leftrightarrow\quad \mapsto$.

\section{Big operators and calculus}
$\sum_{i=1}^{n} i \qquad \prod_{k=1}^{n} k \qquad \int_0^1 x^2 \, dx \qquad \partial \quad \nabla \quad \infty$.

\section{Logic and sets}
$\forall x\ \exists y \quad \emptyset \quad \neg p \quad \langle a, b \rangle$.

\end{document}
`

const MATH = String.raw`\documentclass{article}
\usepackage{amsmath}
\title{Math Examples}
\author{Outrider Docs}
\date{\today}

\begin{document}
\maketitle

\section{Fractions and powers}
Mass--energy and a sum of fractions:
\[ E = mc^2, \qquad \frac{a}{b} + \frac{c}{d} = \frac{ad + bc}{bd}. \]

\section{Sums and integrals}
\[ \sum_{i=1}^{n} i = \frac{n(n+1)}{2}, \qquad \int_0^\infty e^{-x} \, dx = 1. \]

\section{A softmax}
The probability of class $i$ over logits $x_j$:
\[ p_i = \frac{e^{x_i}}{\sum_j e^{x_j}}. \]

\section{Inequalities}
For $0 \leq p \leq 1$ we have $p(1-p) \leq \tfrac{1}{4}$ with equality at $p = \tfrac{1}{2}$.

\end{document}
`

const ARTICLE = String.raw`\documentclass{article}
\title{A Sample Article}
\author{Outrider Docs \and A. Reader}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
A short article exercising headings, lists, emphasis, and inline math, so the
Docs reader has structure to render.
\end{abstract}

\section{Introduction}
Superforecasters decompose questions and update \textbf{often}. A probability
lives in $[0,1]$, and good forecasts are both calibrated and sharp.

\subsection{Method}
\begin{itemize}
  \item Decompose the question into tractable parts.
  \item Find a reference class and a base rate.
  \item Update on new evidence, $p \leftarrow p'$.
\end{itemize}

\section{Results}
\begin{enumerate}
  \item Calibrated forecasts beat unaided intuition.
  \item \emph{Sharpness} matters once you are calibrated.
\end{enumerate}

See \href{https://example.com}{the project page} for more.

\end{document}
`

const REPORT = String.raw`\documentclass{report}
\title{Report Template}
\author{}
\date{\today}

\begin{document}
\maketitle
\tableofcontents

\chapter{Overview}
Replace this with your report. Chapters become top-level sections.

\section{Background}
\section{Findings}

\chapter{Conclusion}

\end{document}
`

const LETTER = String.raw`\documentclass{letter}
\signature{Your Name}
\address{Your Address \\ City, ZIP}

\begin{document}
\begin{letter}{Recipient \\ Their Address}
\opening{Dear Recipient,}

Body of the letter goes here.

\closing{Sincerely,}
\end{letter}
\end{document}
`

const FILES: { content: string; rel: string }[] = [
  { content: SYMBOLS, rel: 'examples/symbols.tex' },
  { content: MATH, rel: 'examples/math.tex' },
  { content: ARTICLE, rel: 'examples/article.tex' },
  { content: REPORT, rel: 'templates/report.tex' },
  { content: LETTER, rel: 'templates/letter.tex' }
]

// Write the examples into <latexDir>. One-time: skips entirely if the
// examples/ folder already exists (so deleting a single file won't resurrect
// it). Returns the rel paths it created.
export const seedLatexExamples = (latexDir: string): string[] => {
  try {
    if (existsSync(join(latexDir, 'examples'))) {
      return []
    }

    const created: string[] = []

    for (const { content, rel } of FILES) {
      const full = join(latexDir, rel)
      mkdirSync(dirname(full), { recursive: true })

      if (!existsSync(full)) {
        writeFileSync(full, content)
        created.push(rel)
      }
    }

    return created
  } catch {
    return []
  }
}
