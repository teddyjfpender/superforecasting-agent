import { tuiEnvValue } from './lib/envAlias.js'

export interface ThemeColors {
  primary: string
  accent: string
  border: string
  text: string
  muted: string
  completionBg: string
  completionCurrentBg: string
  completionMetaBg: string
  completionMetaCurrentBg: string

  label: string
  ok: string
  error: string
  warn: string
  // Informational emphasis (model names, lenses, non-command links): a calm
  // blue distinct from both the gold brand family and the severity triple,
  // so gold can stay reserved for brand + interactive affordances.
  info: string

  prompt: string
  sessionLabel: string
  sessionBorder: string

  statusBg: string
  statusFg: string
  statusGood: string
  statusWarn: string
  statusBad: string
  statusCritical: string
  selectionBg: string

  diffAdded: string
  diffRemoved: string
  diffAddedWord: string
  diffRemovedWord: string

  shellDollar: string
}

export interface ThemeBrand {
  name: string
  icon: string
  prompt: string
  welcome: string
  goodbye: string
  tool: string
  helpHeader: string
}

export interface Theme {
  color: ThemeColors
  brand: ThemeBrand
  bannerLogo: string
  bannerHero: string
}

// ── Color math ───────────────────────────────────────────────────────

function parseHex(h: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(h)

  if (!m) {
    return null
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

function mix(a: string, b: string, t: number) {
  const pa = parseHex(a)
  const pb = parseHex(b)

  if (!pa || !pb) {
    return a
  }

  const lerp = (i: 0 | 1 | 2) => Math.round(pa[i] + (pb[i] - pa[i]) * t)

  return '#' + ((1 << 24) | (lerp(0) << 16) | (lerp(1) << 8) | lerp(2)).toString(16).slice(1)
}

const XTERM_6_LEVELS = [0, 95, 135, 175, 215, 255] as const
const ANSI_LIGHT_MAX_LUMINANCE = 0.72
const ANSI_LIGHT_TARGET_LUMINANCE = 0.34
const ANSI_LIGHT_MIN_SATURATION = 0.22
const ANSI_MUTED_BUCKET = 245

const ANSI_NORMALIZED_FOREGROUNDS: readonly (keyof ThemeColors)[] = [
  'text',
  'label',
  'ok',
  'error',
  'warn',
  'prompt',
  'statusFg',
  'statusGood',
  'statusWarn',
  'statusBad',
  'statusCritical',
  'shellDollar'
]

const ANSI_MUTED_FOREGROUNDS: readonly (keyof ThemeColors)[] = ['muted', 'sessionLabel', 'sessionBorder']

function xtermEightBitRgb(colorNumber: number): [number, number, number] {
  if (colorNumber >= 232) {
    const value = 8 + (colorNumber - 232) * 10

    return [value, value, value]
  }

  if (colorNumber >= 16) {
    const offset = colorNumber - 16

    return [
      XTERM_6_LEVELS[Math.floor(offset / 36) % 6]!,
      XTERM_6_LEVELS[Math.floor(offset / 6) % 6]!,
      XTERM_6_LEVELS[offset % 6]!
    ]
  }

  return [0, 0, 0]
}

function channelLuminance(value: number): number {
  const normalized = value / 255

  return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4
}

function relativeLuminance(red: number, green: number, blue: number): number {
  return 0.2126 * channelLuminance(red) + 0.7152 * channelLuminance(green) + 0.0722 * channelLuminance(blue)
}

// ── Dark-terminal contrast floor ─────────────────────────────────────
// Several skins set `muted`/dim foregrounds dark enough to be near-invisible
// on a black terminal (e.g. ares crimson #6B1717 ≈ 1.8:1, poseidon navy ≈
// 1.9:1) — well under the 4.5:1 WCAG AA floor for body text. Since `muted`
// carries the bulk of secondary text (hints, descriptions, separators), that
// reads as "faint, hard-to-read text". We lift only the text-bearing
// foregrounds toward white until they clear the floor, preserving the rest of
// the palette. Applied to ANY skin (built-in or user), only in dark mode.

// Pure-black reference background (the WCAG comparison point). Using true
// black keeps the floor surgical — it lifts only colors that are unreadable
// even on black (the 1.0–2.8:1 dim values several skins ship), and leaves
// already-readable foregrounds (incl. the gold default muted at ~6:1)
// byte-for-byte unchanged.
const DARK_BG_LUMINANCE = 0.0
const DARK_TEXT_CONTRAST_FLOOR = 4.5

// Foregrounds that carry readable TEXT or headers — the ones we lift. On
// dark-designed skins these are all already bright (so the floor is a no-op
// and DEFAULT_THEME === DARK_THEME still holds); on a LIGHT skin forced into
// dark mode their dark values get lifted so the theme stays legible instead
// of vanishing into the background. Severity colors (ok/warn/error) are
// bright on every shipped skin; borders/backgrounds are decorative — left.
const DARK_CONTRAST_FLOORED_KEYS: readonly (keyof ThemeColors)[] = [
  'text',
  'muted',
  'label',
  'prompt',
  'sessionLabel',
  'sessionBorder',
  'info',
  'primary',
  'accent'
]

function wcagContrast(luminance: number, background: number): number {
  const hi = Math.max(luminance, background)
  const lo = Math.min(luminance, background)

  return (hi + 0.05) / (lo + 0.05)
}

function colorLuminance(hex: string): null | number {
  const rgb = parseHex(hex)

  return rgb ? relativeLuminance(rgb[0], rgb[1], rgb[2]) : null
}

// Lift a too-dark color toward white until it clears `floor` against a dark
// background. Non-hex inputs (e.g. `ansi256(...)`) pass through untouched.
function enforceDarkContrast(
  hex: string,
  floor = DARK_TEXT_CONTRAST_FLOOR,
  background = DARK_BG_LUMINANCE
): string {
  const lum = colorLuminance(hex)

  if (lum === null || wcagContrast(lum, background) >= floor) {
    return hex
  }

  // Binary-search the blend toward white; 14 steps resolves to hex precision.
  let lo = 0
  let hi = 1
  let result = mix(hex, '#FFFFFF', 1)

  for (let i = 0; i < 14; i++) {
    const t = (lo + hi) / 2
    const candidate = mix(hex, '#FFFFFF', t)
    const candidateLum = colorLuminance(candidate)

    if (candidateLum !== null && wcagContrast(candidateLum, background) >= floor) {
      result = candidate
      hi = t
    } else {
      lo = t
    }
  }

  return result
}

export function enforceDarkContrastFloor(theme: Theme, isLight = detectLightMode()): Theme {
  if (isLight) {
    return theme
  }

  const color = { ...theme.color }
  let changed = false

  for (const key of DARK_CONTRAST_FLOORED_KEYS) {
    const lifted = enforceDarkContrast(color[key])

    if (lifted !== color[key]) {
      color[key] = lifted
      changed = true
    }
  }

  // Return the SAME theme object when nothing needed lifting — preserves the
  // DEFAULT_THEME === DARK_THEME aliasing invariant other code relies on.
  return changed ? { ...theme, color } : theme
}

function rgbToHsl(red: number, green: number, blue: number): [number, number, number] {
  const rn = red / 255
  const gn = green / 255
  const bn = blue / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const lightness = (max + min) / 2

  if (max === min) {
    return [0, 0, lightness]
  }

  const delta = max - min
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min)

  const hue =
    max === rn ? (gn - bn) / delta + (gn < bn ? 6 : 0) : max === gn ? (bn - rn) / delta + 2 : (rn - gn) / delta + 4

  return [hue / 6, saturation, lightness]
}

function circularDistance(a: number, b: number): number {
  const distance = Math.abs(a - b)

  return Math.min(distance, 1 - distance)
}

// Mirrors @hermes/ink's colorize.ts. Keep local: app code compiles from
// ui-tui/src, while @hermes/ink is bundled separately from packages/.
function richEightBitColorNumber(red: number, green: number, blue: number): number {
  const [, saturation, lightness] = rgbToHsl(red, green, blue)

  if (saturation < 0.15) {
    const gray = Math.round(lightness * 25)

    return gray === 0 ? 16 : gray === 25 ? 231 : 231 + gray
  }

  const sixRed = red < 95 ? red / 95 : 1 + (red - 95) / 40
  const sixGreen = green < 95 ? green / 95 : 1 + (green - 95) / 40
  const sixBlue = blue < 95 ? blue / 95 : 1 + (blue - 95) / 40

  return 16 + 36 * Math.round(sixRed) + 6 * Math.round(sixGreen) + Math.round(sixBlue)
}

function bestReadableAnsiColor(red: number, green: number, blue: number): number {
  const [hue, saturation, lightness] = rgbToHsl(red, green, blue)
  let bestColor = richEightBitColorNumber(red, green, blue)
  let bestScore = Number.POSITIVE_INFINITY

  for (let colorNumber = 16; colorNumber <= 255; colorNumber += 1) {
    const [candidateRed, candidateGreen, candidateBlue] = xtermEightBitRgb(colorNumber)
    const candidateLuminance = relativeLuminance(candidateRed, candidateGreen, candidateBlue)

    if (candidateLuminance > ANSI_LIGHT_MAX_LUMINANCE) {
      continue
    }

    const [candidateHue, candidateSaturation, candidateLightness] = rgbToHsl(
      candidateRed,
      candidateGreen,
      candidateBlue
    )

    const saturationFloorPenalty =
      candidateSaturation < ANSI_LIGHT_MIN_SATURATION ? (ANSI_LIGHT_MIN_SATURATION - candidateSaturation) * 3 : 0

    const score =
      circularDistance(candidateHue, hue) * 4 +
      Math.abs(candidateSaturation - Math.max(ANSI_LIGHT_MIN_SATURATION, saturation)) * 0.8 +
      Math.abs(candidateLightness - Math.min(lightness, ANSI_LIGHT_TARGET_LUMINANCE)) * 2 +
      saturationFloorPenalty

    if (score < bestScore) {
      bestColor = colorNumber
      bestScore = score
    }
  }

  return bestColor
}

function normalizeAnsiForeground(color: string): string {
  const rgb = parseHex(color)

  if (!rgb) {
    return color
  }

  const richAnsi = richEightBitColorNumber(rgb[0], rgb[1], rgb[2])
  const richRgb = xtermEightBitRgb(richAnsi)

  const ansi =
    relativeLuminance(richRgb[0], richRgb[1], richRgb[2]) > ANSI_LIGHT_MAX_LUMINANCE
      ? bestReadableAnsiColor(rgb[0], rgb[1], rgb[2])
      : richAnsi

  return `ansi256(${ansi})`
}

// ── Defaults ─────────────────────────────────────────────────────────

const BRAND: ThemeBrand = {
  name: 'Outrider',
  icon: '✦',
  prompt: '❯',
  welcome: 'Forecast desk ready. Type /forecast or /help.',
  goodbye: 'Goodbye.',
  tool: '┊',
  helpHeader: 'Commands'
}

const cleanPromptSymbol = (s: string | undefined, fallback: string) => {
  const cleaned = String(s ?? '')
    .replace(/\s+/g, ' ')
    .trim()

  return cleaned || fallback
}

// The brand gradient — a blue → lavender-purple → rose-pink ramp (inspired by
// the Gemini CLI's signature banner gradient), applied to the Outrider hero so
// the wordmark glows across the spectrum. The stops echo the palette's own
// info / accent / error accents so the gradient and the rest of the UI agree.
export const BRAND_GRADIENT = ['#58A6FF', '#A98BFF', '#FF8FAB'] as const

// Darker blue → violet → magenta for LIGHT terminals: the hero ramps
// dark→colour→white, so on a white background the pastel dark gradient would
// wash out — these saturated stops keep the figure crisp and readable on white.
export const BRAND_GRADIENT_LIGHT = ['#2563EB', '#7C3AED', '#C2185B'] as const

// Standard dark palette: a refined pastel-on-near-black system inspired by the
// Gemini CLI's "professional" look — a lavender-purple accent, a calm soft-blue
// for informational emphasis, and a rose family for alerts, all high-value /
// low-saturation so they read crisp (not 1990s-ANSI bright) on a dark terminal.
// Replaces the old slate/blue default (the gold heritage lives on as the `gold`
// skin). This is the single source of truth the `default` skin mirrors, so the
// picker preview matches the live UI. Every text-bearing foreground clears the
// 4.5:1 dark-contrast floor on pure black, preserving DEFAULT_THEME === DARK_THEME.
export const DARK_THEME: Theme = {
  color: {
    primary: '#E9E5F4',
    accent: '#CBA6FF',
    border: '#3A3350',
    text: '#E9E5F4',
    muted: '#9C95B5',
    completionBg: '#1A1726',
    completionCurrentBg: '#27232C',
    completionMetaBg: '#1A1726',
    completionMetaCurrentBg: '#27232C',

    label: '#B3AAD0',
    ok: '#7FD99A',
    error: '#FF7E9D',
    warn: '#F0C674',
    info: '#8FB8FF',

    prompt: '#CBA6FF',
    sessionLabel: '#9C95B5',
    sessionBorder: '#9C95B5',

    statusBg: '#13111B',
    statusFg: '#C9C3DB',
    statusGood: '#7FD99A',
    statusWarn: '#F0C674',
    statusBad: '#FFA45C',
    statusCritical: '#FF5C77',
    selectionBg: '#27232C',

    diffAdded: 'rgb(214,247,222)',
    diffRemoved: 'rgb(255,224,232)',
    diffAddedWord: 'rgb(127,217,154)',
    diffRemovedWord: 'rgb(255,126,157)',
    shellDollar: '#8FB8FF'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: ''
}

// Light-terminal palette: darker golds/ambers that stay legible on white
// backgrounds. Same shape as DARK_THEME so `fromSkin` still layers on top
// cleanly (#11300).
export const LIGHT_THEME: Theme = {
  color: {
    primary: '#241F33',
    accent: '#7C3AED',
    border: '#D9D3E6',
    text: '#241F33',
    muted: '#6B6480',
    completionBg: '#F6F4FB',
    completionCurrentBg: mix('#F6F4FB', '#7C3AED', 0.16),
    completionMetaBg: '#F6F4FB',
    completionMetaCurrentBg: mix('#F6F4FB', '#7C3AED', 0.16),

    label: '#5A5470',
    ok: '#15803D',
    error: '#BE185D',
    warn: '#B45309',
    info: '#2563EB',

    prompt: '#7C3AED',
    sessionLabel: '#6B6480',
    sessionBorder: '#6B6480',

    statusBg: '#F6F4FB',
    statusFg: '#241F33',
    statusGood: '#15803D',
    statusWarn: '#B45309',
    statusBad: '#C2410C',
    statusCritical: '#BE123C',
    selectionBg: mix('#F6F4FB', '#7C3AED', 0.16),

    diffAdded: 'rgb(214,240,222)',
    diffRemoved: 'rgb(248,216,228)',
    diffAddedWord: 'rgb(21,128,61)',
    diffRemovedWord: 'rgb(190,24,93)',
    shellDollar: '#2563EB'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: ''
}

const TRUE_RE = /^(?:1|true|yes|on)$/
const FALSE_RE = /^(?:0|false|no|off)$/

// TERM_PROGRAM fallback allow-list for terminals whose default profile is
// light and which may not expose COLORFGBG. This currently includes Apple
// Terminal. Explicit FORECAST_TUI_THEME / HERMES_TUI_THEME / COLORFGBG signals above still win,
// so dark Apple Terminal profiles that advertise a dark background stay dark.
const LIGHT_DEFAULT_TERM_PROGRAMS = new Set<string>(['Apple_Terminal'])

// Best-effort RGB → luminance check.  Currently only accepts a 3- or
// 6-digit hex value (with or without a leading `#`); the env var name
// `FORECAST_TUI_BACKGROUND` / `HERMES_TUI_BACKGROUND` is intentionally generic so a future OSC11
// query helper can cache its answer there too, but additional formats
// (rgb()/hsl()/named colours) would need explicit parsing here first.
const LUMA_LIGHT_THRESHOLD = 0.6

// Strict allow-list: parseInt(..., 16) silently truncates at the first
// non-hex character (e.g. `fffgff` would parse as `fff` and yield a
// false-positive "white" reading), so reject anything that doesn't match
// the canonical 3- or 6-digit shape up front.
const HEX_3_RE = /^[0-9a-f]{3}$/
const HEX_6_RE = /^[0-9a-f]{6}$/

function backgroundLuminance(raw: string): null | number {
  const v = raw.trim().toLowerCase()

  if (!v) {
    return null
  }

  const hex = v.startsWith('#') ? v.slice(1) : v

  const rgb = HEX_6_RE.test(hex)
    ? [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
    : HEX_3_RE.test(hex)
      ? [parseInt(hex[0]! + hex[0]!, 16), parseInt(hex[1]! + hex[1]!, 16), parseInt(hex[2]! + hex[2]!, 16)]
      : null

  if (!rgb) {
    return null
  }

  // Rec. 709 luma — close enough for "is this background bright".
  return (0.2126 * rgb[0]! + 0.7152 * rgb[1]! + 0.0722 * rgb[2]!) / 255
}

// Pick light vs dark with ordered, explainable signals (#11300):
//
//   1. `FORECAST_TUI_LIGHT` / `HERMES_TUI_LIGHT` boolean — `1`/`true`/`yes`/`on` → light;
//      `0`/`false`/`no`/`off` → dark.  Either explicit value wins
//      regardless of any later signal.
//   2. `FORECAST_TUI_THEME` / `HERMES_TUI_THEME` named override — `light` / `dark` win over
//      every signal below.
//   3. `FORECAST_TUI_BACKGROUND` / `HERMES_TUI_BACKGROUND` hex hint (3- or 6-digit) — luminance
//      ≥ LUMA_LIGHT_THRESHOLD → light.
//   4. `COLORFGBG` last field — XFCE / rxvt / Terminal.app emit
//      slot 7 or 15 on light profiles; 0–15 ranges are otherwise
//      treated as authoritatively dark so the TERM_PROGRAM
//      allow-list below cannot override an explicit dark profile.
//   5. `TERM_PROGRAM` light-default allow-list.
//
// Anything we can't decide stays dark — the default compatibility palette
// is the dark one.
export function detectLightMode(
  env: NodeJS.ProcessEnv = process.env,
  // Injectable so tests can prove the COLORFGBG-over-TERM_PROGRAM
  // precedence rule even though the production allow-list is empty.
  lightDefaultTermPrograms: ReadonlySet<string> = LIGHT_DEFAULT_TERM_PROGRAMS
): boolean {
  const lightFlag = tuiEnvValue('LIGHT', env).toLowerCase()

  if (TRUE_RE.test(lightFlag)) {
    return true
  }

  if (FALSE_RE.test(lightFlag)) {
    return false
  }

  const themeFlag = tuiEnvValue('THEME', env).toLowerCase()

  if (themeFlag === 'light') {
    return true
  }

  if (themeFlag === 'dark') {
    return false
  }

  const bgHint = backgroundLuminance(tuiEnvValue('BACKGROUND', env))

  if (bgHint !== null) {
    return bgHint >= LUMA_LIGHT_THRESHOLD
  }

  const colorfgbg = (env.COLORFGBG ?? '').trim()

  if (colorfgbg) {
    // Validate as a decimal integer before coercing — `Number('')` is 0,
    // so a malformed `COLORFGBG='15;'` would otherwise look like an
    // authoritative dark slot and incorrectly block the TERM_PROGRAM
    // allow-list.  Anything that isn't pure digits falls through.
    const lastField = colorfgbg.split(';').at(-1) ?? ''

    if (/^\d+$/.test(lastField)) {
      const bg = Number(lastField)

      if (bg === 7 || bg === 15) {
        return true
      }

      // Slots 0–6 and 8–14 are the dark half of the 0–15 ANSI range.
      // When COLORFGBG is set we trust it as authoritative — a non-light
      // value here shouldn't get overridden by the TERM_PROGRAM allow-list.
      if (bg >= 0 && bg < 16) {
        return false
      }
    }
  }

  const termProgram = (env.TERM_PROGRAM ?? '').trim()

  return lightDefaultTermPrograms.has(termProgram)
}

function shouldNormalizeAnsiLightTheme(env: NodeJS.ProcessEnv = process.env, isLight = detectLightMode(env)): boolean {
  const colorTerm = (env.COLORTERM ?? '').trim().toLowerCase()
  const termProgram = (env.TERM_PROGRAM ?? '').trim()

  return termProgram === 'Apple_Terminal' && colorTerm !== 'truecolor' && colorTerm !== '24bit' && isLight
}

export function normalizeThemeForAnsiLightTerminal(
  theme: Theme,
  env: NodeJS.ProcessEnv = process.env,
  isLight = detectLightMode(env)
): Theme {
  if (!shouldNormalizeAnsiLightTheme(env, isLight)) {
    return theme
  }

  const color = { ...theme.color }

  for (const key of ANSI_NORMALIZED_FOREGROUNDS) {
    color[key] = normalizeAnsiForeground(color[key])
  }

  for (const key of ANSI_MUTED_FOREGROUNDS) {
    color[key] = `ansi256(${ANSI_MUTED_BUCKET})`
  }

  return { ...theme, color }
}

const DEFAULT_LIGHT_MODE = detectLightMode()

export const DEFAULT_THEME: Theme = enforceDarkContrastFloor(
  normalizeThemeForAnsiLightTerminal(
    DEFAULT_LIGHT_MODE ? LIGHT_THEME : DARK_THEME,
    process.env,
    DEFAULT_LIGHT_MODE
  ),
  DEFAULT_LIGHT_MODE
)

// ── Skin → Theme ─────────────────────────────────────────────────────

// `isLightOverride` lets the caller force light/dark independent of terminal
// auto-detection — the in-TUI /theme picker passes the user's explicit
// appearance choice so they can flip mode and see it live. Undefined keeps
// the auto-detected DEFAULT_LIGHT_MODE.
export function fromSkin(
  colors: Record<string, string>,
  branding: Record<string, string>,
  bannerLogo = '',
  bannerHero = '',
  toolPrefix = '',
  helpHeader = '',
  isLightOverride?: boolean
): Theme {
  const isLight = isLightOverride ?? DEFAULT_LIGHT_MODE
  const d = DEFAULT_THEME
  const c = (k: string) => colors[k]
  const hasSkinColors = Object.keys(colors).length > 0

  const accent = c('ui_accent') ?? c('banner_accent') ?? d.color.accent
  const bannerAccent = c('banner_accent') ?? c('banner_title') ?? d.color.accent
  const muted = c('banner_dim') ?? d.color.muted
  const completionBg = c('completion_menu_bg') ?? d.color.completionBg

  const completionCurrentBg =
    c('completion_menu_current_bg') ??
    (hasSkinColors ? mix(completionBg, bannerAccent, 0.25) : d.color.completionCurrentBg)

  const completionMetaBg = c('completion_menu_meta_bg') ?? completionBg
  const completionMetaCurrentBg = c('completion_menu_meta_current_bg') ?? completionCurrentBg

  return enforceDarkContrastFloor(
    normalizeThemeForAnsiLightTerminal(
    {
      color: {
        primary: c('ui_primary') ?? c('banner_title') ?? d.color.primary,
        accent,
        border: c('ui_border') ?? c('banner_border') ?? d.color.border,
        text: c('ui_text') ?? c('banner_text') ?? d.color.text,
        muted,
        completionBg,
        completionCurrentBg,
        completionMetaBg,
        completionMetaCurrentBg,

        label: c('ui_label') ?? d.color.label,
        ok: c('ui_ok') ?? d.color.ok,
        error: c('ui_error') ?? d.color.error,
        warn: c('ui_warn') ?? d.color.warn,
        info: c('ui_info') ?? d.color.info,

        prompt: c('prompt') ?? c('banner_text') ?? d.color.prompt,
        sessionLabel: c('session_label') ?? muted,
        sessionBorder: c('session_border') ?? muted,

        statusBg: d.color.statusBg,
        statusFg: d.color.statusFg,
        statusGood: c('ui_ok') ?? d.color.statusGood,
        statusWarn: c('ui_warn') ?? d.color.statusWarn,
        statusBad: d.color.statusBad,
        statusCritical: d.color.statusCritical,
        selectionBg:
          c('selection_bg') ??
          c('completion_menu_current_bg') ??
          (hasSkinColors ? completionCurrentBg : d.color.selectionBg),

        diffAdded: d.color.diffAdded,
        diffRemoved: d.color.diffRemoved,
        diffAddedWord: d.color.diffAddedWord,
        diffRemovedWord: d.color.diffRemovedWord,
        shellDollar: c('shell_dollar') ?? d.color.shellDollar
      },

      brand: {
        name: branding.agent_name ?? d.brand.name,
        icon: d.brand.icon,
        prompt: cleanPromptSymbol(branding.prompt_symbol, d.brand.prompt),
        welcome: branding.welcome ?? d.brand.welcome,
        goodbye: branding.goodbye ?? d.brand.goodbye,
        tool: toolPrefix || d.brand.tool,
        helpHeader: branding.help_header ?? (helpHeader || d.brand.helpHeader)
      },

      bannerLogo,
      bannerHero
    },
    process.env,
    isLight
    ),
    isLight
  )
}
