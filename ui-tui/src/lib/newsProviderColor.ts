import type { Theme } from '../theme.js'

import { relLuminance } from './visualSemantics.js'

// Per-source colour coding for the News list: each provider gets a stable,
// distinct hue from hash(name) → palette, so "NWS", "NHC", "Reuters" … read
// apart at a glance. The user can override any provider's colour in the add-feed
// flow; overrides win over the hash.
//
// Two palettes (dark / light) so a source stays legible on either terminal
// background; we pick by the active theme's luminance.

export const PROVIDER_HUES_DARK = [
  '#58A6FF', // blue
  '#39C5CF', // teal
  '#3FB950', // green
  '#E3B341', // amber
  '#F778BA', // pink
  '#BC8CFF', // purple
  '#FF7B72', // salmon
  '#56D364', // lime
  '#FFA657', // orange
  '#79C0FF', // sky
  '#D2A8FF', // lilac
  '#7EE787' // mint
]

export const PROVIDER_HUES_LIGHT = [
  '#0969DA', // blue
  '#0E7490', // teal
  '#1A7F37', // green
  '#9A6700', // amber
  '#BF3989', // pink
  '#8250DF', // purple
  '#CF222E', // red
  '#1B7C2F', // forest
  '#BC4C00', // orange
  '#0550AE', // navy
  '#6639BA', // violet
  '#116329' // emerald
]

const isDarkTheme = (t: Theme): boolean => (relLuminance(t.color.text) ?? 1) > 0.4

export const providerPalette = (t: Theme): string[] => (isDarkTheme(t) ? PROVIDER_HUES_DARK : PROVIDER_HUES_LIGHT)

// Normalize a provider label to a stable key (the displayed tag is padded).
export const providerKey = (name: string): string => name.trim().toLowerCase()

// djb2 → unsigned 32-bit, so the same name always maps to the same hue.
export const hashName = (name: string): number => {
  let h = 5381

  for (let i = 0; i < name.length; i++) {
    h = (Math.imul(h, 33) + name.charCodeAt(i)) | 0
  }

  return h >>> 0
}

export const autoProviderColor = (name: string, t: Theme): string => {
  const palette = providerPalette(t)

  return palette[hashName(providerKey(name)) % palette.length]
}

// Resolve the colour for a provider: a user override wins, otherwise the hash.
export const providerColor = (name: string, t: Theme, overrides: Record<string, string> = {}): string =>
  overrides[providerKey(name)] ?? autoProviderColor(name, t)

// Cycle to the next palette hue (for the in-modal colour picker). Starts from
// the current override / auto colour so pressing the key visibly advances.
export const nextProviderColor = (name: string, t: Theme, current: string | undefined): string => {
  const palette = providerPalette(t)
  const at = current ? palette.indexOf(current) : palette.indexOf(autoProviderColor(name, t))

  return palette[(at + 1 + palette.length) % palette.length]
}
