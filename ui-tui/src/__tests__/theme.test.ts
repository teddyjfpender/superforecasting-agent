import { afterEach, describe, expect, it, vi } from 'vitest'

// `theme.js` reads `process.env` at module-load to compute DEFAULT_THEME,
// and `fromSkin` closes over DEFAULT_THEME.  A developer shell with
// HERMES_TUI_THEME=light (or HERMES_TUI_BACKGROUND set to something
// bright) would flip the base and turn these assertions into a local-
// only failure.  We sterilize the relevant env vars + dynamically
// import the module fresh so EVERY symbol that closes over the env
// (DEFAULT_THEME, DARK_THEME, LIGHT_THEME, fromSkin) is loaded against
// a known-empty environment.
//
// `detectLightMode` takes env as an explicit arg, so it's safe to import
// statically — but we stay consistent and dynamic-import it too.
const RELEVANT_ENV = [
  'SUPERFORECASTING_AGENT_TUI_LIGHT',
  'SUPERFORECASTING_AGENT_TUI_THEME',
  'SUPERFORECASTING_AGENT_TUI_BACKGROUND',
  'FORECAST_TUI_LIGHT',
  'FORECAST_TUI_THEME',
  'FORECAST_TUI_BACKGROUND',
  'HERMES_TUI_LIGHT',
  'HERMES_TUI_THEME',
  'HERMES_TUI_BACKGROUND',
  'COLORFGBG',
  'COLORTERM',
  'TERM_PROGRAM'
] as const

async function importThemeWithEnv(env: Partial<Record<(typeof RELEVANT_ENV)[number], string>> = {}) {
  for (const key of RELEVANT_ENV) {
    vi.stubEnv(key, env[key] ?? '')
  }

  vi.resetModules()

  return import('../theme.js')
}

async function importThemeWithCleanEnv() {
  return importThemeWithEnv()
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('DEFAULT_THEME', () => {
  it('has brand defaults', async () => {
    const { DEFAULT_THEME } = await importThemeWithCleanEnv()

    expect(DEFAULT_THEME.brand.name).toBe('Outrider')
    expect(DEFAULT_THEME.brand.prompt).toBe('❯')
    expect(DEFAULT_THEME.brand.tool).toBe('┊')
  })

  it('has color palette', async () => {
    const { DEFAULT_THEME } = await importThemeWithCleanEnv()

    expect(DEFAULT_THEME.color.primary).toBe('#E9E5F4')
    expect(DEFAULT_THEME.color.error).toBe('#FF7E9D')
  })
})

describe('LIGHT_THEME', () => {
  it('avoids bright-yellow accents unreadable on white backgrounds (#11300)', async () => {
    const { LIGHT_THEME } = await importThemeWithCleanEnv()

    expect(LIGHT_THEME.color.primary).not.toBe('#FFD700')
    expect(LIGHT_THEME.color.accent).not.toBe('#FFBF00')
    expect(LIGHT_THEME.color.muted).not.toBe('#B8860B')
    expect(LIGHT_THEME.color.statusWarn).not.toBe('#FFD700')
  })

  it('keeps the same shape as DARK_THEME', async () => {
    const { DARK_THEME, LIGHT_THEME } = await importThemeWithCleanEnv()

    expect(Object.keys(LIGHT_THEME.color).sort()).toEqual(Object.keys(DARK_THEME.color).sort())
    expect(LIGHT_THEME.brand).toEqual(DARK_THEME.brand)
  })
})

describe('DEFAULT_THEME aliasing', () => {
  it('defaults to DARK_THEME when nothing signals light', async () => {
    const { DEFAULT_THEME, DARK_THEME: DARK } = await importThemeWithCleanEnv()

    expect(DEFAULT_THEME).toBe(DARK)
  })
})

describe('detectLightMode', () => {
  it('returns false on empty env', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({})).toBe(false)
  })

  it('defaults Apple Terminal to light when no stronger signal is present', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ TERM_PROGRAM: 'Apple_Terminal' })).toBe(true)
  })

  it('honors HERMES_TUI_LIGHT on/off', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ HERMES_TUI_LIGHT: '1' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'true' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'on' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: '0' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'off' })).toBe(false)
  })

  it('prefers fork-native light-mode aliases before legacy Hermes names', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ HERMES_TUI_THEME: 'dark', FORECAST_TUI_THEME: 'light' })).toBe(true)
    expect(
      detectLightMode({
        HERMES_TUI_LIGHT: '1',
        FORECAST_TUI_LIGHT: '1',
        SUPERFORECASTING_AGENT_TUI_LIGHT: '0'
      })
    ).toBe(false)
  })

  it('sniffs COLORFGBG bg slots 7 and 15 as light (#11300)', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ COLORFGBG: '0;15' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '0;default;15' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '0;7' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '15;0' })).toBe(false)
    expect(detectLightMode({ COLORFGBG: '7;default;0' })).toBe(false)
  })

  it('falls through on malformed COLORFGBG with empty/non-numeric trailing field', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()
    // `Number('')` is 0, so `'15;'` would have been read as bg=0
    // (authoritative dark) and incorrectly blocked TERM_PROGRAM.
    // The strict /^\d+$/ guard makes these fall through instead.
    const allowList = new Set(['Apple_Terminal'])

    expect(detectLightMode({ COLORFGBG: '15;', TERM_PROGRAM: 'Apple_Terminal' }, allowList)).toBe(true)
    expect(detectLightMode({ COLORFGBG: 'default;default', TERM_PROGRAM: 'Apple_Terminal' }, allowList)).toBe(true)
    // Without an allow-list match, fall-through still defaults to dark.
    expect(detectLightMode({ COLORFGBG: '15;' })).toBe(false)
  })

  it('lets HERMES_TUI_LIGHT=0 override a light COLORFGBG', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ COLORFGBG: '0;15', HERMES_TUI_LIGHT: '0' })).toBe(false)
  })

  it('honors HERMES_TUI_THEME=light/dark as a symmetric explicit override', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ HERMES_TUI_THEME: 'light' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_THEME: 'dark' })).toBe(false)
    expect(detectLightMode({ COLORFGBG: '0;15', HERMES_TUI_THEME: 'dark' })).toBe(false)
    expect(detectLightMode({ COLORFGBG: '15;0', HERMES_TUI_THEME: 'light' })).toBe(true)
  })

  it('uses HERMES_TUI_BACKGROUND luminance when COLORFGBG is missing', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()

    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#ffffff' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#000000' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#1e1e1e' })).toBe(false)
    // Three-char hex normalises like CSS.
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#fff' })).toBe(true)
    // Garbage falls through to the default-dark path.
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: 'not-a-colour' })).toBe(false)
  })

  it('rejects partially-invalid hex instead of silently truncating', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()
    // `parseInt('fffgff'.slice(2,4), 16)` would return 15 — the strict
    // regex must reject these inputs so they fall through to default-
    // dark instead of producing a false-positive light reading.
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#fffgff' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: 'ffggff' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#xyz' })).toBe(false)
    // Wrong length also rejected (no implicit padding/truncation).
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#fffff' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_BACKGROUND: '#fffffff' })).toBe(false)
  })

  it('treats COLORFGBG as authoritative when present so it dominates the TERM_PROGRAM allow-list', async () => {
    const { detectLightMode } = await importThemeWithCleanEnv()
    // Injecting the allow-list keeps this precedence rule explicit even if
    // production defaults change.
    const allowList = new Set(['Apple_Terminal'])

    // Sanity: the allow-list alone WOULD turn this terminal light.
    expect(detectLightMode({ TERM_PROGRAM: 'Apple_Terminal' }, allowList)).toBe(true)

    // Dark COLORFGBG must beat the allow-list.
    expect(detectLightMode({ COLORFGBG: '15;0', TERM_PROGRAM: 'Apple_Terminal' }, allowList)).toBe(false)
  })
})

describe('fromSkin', () => {
  // `fromSkin` closes over DEFAULT_THEME (which is env-derived), so we
  // must dynamic-import it after sterilizing env — otherwise an ambient
  // HERMES_TUI_THEME=light would flip the base palette and make these
  // assertions order-dependent on the developer's shell.

  it('overrides banner colors', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    expect(fromSkin({ banner_title: '#FF0000' }, {}).color.primary).toBe('#FF0000')
  })

  it('preserves unset colors', async () => {
    const { DEFAULT_THEME, fromSkin } = await importThemeWithCleanEnv()

    expect(fromSkin({ banner_title: '#FF0000' }, {}).color.accent).toBe(DEFAULT_THEME.color.accent)
  })

  it('derives completion current background from resolved completion background', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    const theme = fromSkin({ banner_accent: '#000000', completion_menu_bg: '#ffffff' }, {})

    expect(theme.color.completionBg).toBe('#ffffff')
    expect(theme.color.completionCurrentBg).toBe('#bfbfbf')
  })

  it('uses active completion color as the selection highlight fallback', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    const theme = fromSkin({ completion_menu_current_bg: '#123456' }, {})

    expect(theme.color.selectionBg).toBe('#123456')
  })

  it('maps completion meta background colors from skins', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    const theme = fromSkin(
      {
        completion_menu_meta_bg: '#111111',
        completion_menu_meta_current_bg: '#222222'
      },
      {}
    )

    expect(theme.color.completionMetaBg).toBe('#111111')
    expect(theme.color.completionMetaCurrentBg).toBe('#222222')
  })

  it('lets selection_bg override completion highlight colors', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    const theme = fromSkin({ completion_menu_current_bg: '#123456', selection_bg: '#654321' }, {})

    expect(theme.color.selectionBg).toBe('#654321')
  })

  it('overrides branding', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()
    const { brand } = fromSkin({}, { agent_name: 'TestBot', prompt_symbol: '$' })

    expect(brand.name).toBe('TestBot')
    expect(brand.prompt).toBe('$')
  })

  it('normalizes skin prompt symbols to trimmed single-line text', async () => {
    const { DEFAULT_THEME, fromSkin } = await importThemeWithCleanEnv()

    expect(fromSkin({}, { prompt_symbol: ' ⚔ ❯ \n' }).brand.prompt).toBe('⚔ ❯')
    expect(fromSkin({}, { prompt_symbol: ' Ψ > \n' }).brand.prompt).toBe('Ψ >')
    expect(fromSkin({}, { prompt_symbol: '\n\t' }).brand.prompt).toBe(DEFAULT_THEME.brand.prompt)
  })

  it('defaults for empty skin', async () => {
    const { DEFAULT_THEME, fromSkin } = await importThemeWithCleanEnv()

    expect(fromSkin({}, {}).color).toEqual(DEFAULT_THEME.color)
    expect(fromSkin({}, {}).brand.icon).toBe(DEFAULT_THEME.brand.icon)
  })

  it('normalizes non-banner foregrounds on light Apple Terminal', async () => {
    const { fromSkin } = await importThemeWithEnv({ TERM_PROGRAM: 'Apple_Terminal' })

    const theme = fromSkin(
      {
        banner_accent: '#FFBF00',
        banner_border: '#CD7F32',
        banner_dim: '#B8860B',
        banner_text: '#FFF8DC',
        banner_title: '#FFD700',
        prompt: '#FFF8DC'
      },
      {}
    )

    expect(theme.color.primary).toBe('#FFD700')
    expect(theme.color.accent).toBe('#FFBF00')
    expect(theme.color.border).toBe('#CD7F32')
    expect(theme.color.muted).toBe('ansi256(245)')
    expect(theme.color.text).toBe('ansi256(136)')
    expect(theme.color.prompt).toBe('ansi256(136)')
  })

  it('does not normalize light Apple Terminal when truecolor is advertised', async () => {
    const { fromSkin } = await importThemeWithEnv({ COLORTERM: 'truecolor', TERM_PROGRAM: 'Apple_Terminal' })
    const theme = fromSkin({ banner_text: '#FFF8DC' }, {})

    expect(theme.color.text).toBe('#FFF8DC')
  })

  it('normalizes Apple Terminal names before matching', async () => {
    const { fromSkin } = await importThemeWithEnv({ TERM_PROGRAM: ' Apple_Terminal ' })
    const theme = fromSkin({ banner_text: '#FFF8DC' }, {})

    expect(theme.color.text).toBe('ansi256(136)')
  })

  it('passes banner logo/hero', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()

    expect(fromSkin({}, {}, 'LOGO', 'HERO').bannerLogo).toBe('LOGO')
    expect(fromSkin({}, {}, 'LOGO', 'HERO').bannerHero).toBe('HERO')
  })

  it('maps ui_ color keys + cascades to status', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()
    const { color } = fromSkin({ ui_ok: '#008000' }, {})

    expect(color.ok).toBe('#008000')
    expect(color.statusGood).toBe('#008000')
  })
})

describe('dark-terminal contrast floor', () => {
  // Minimal WCAG contrast against a near-black terminal background.
  const cl = (v: number) => (v / 255 <= 0.03928 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4)

  const lum = (hex: string) => {
    const n = parseInt(hex.replace('#', ''), 16)

    return 0.2126 * cl((n >> 16) & 255) + 0.7152 * cl((n >> 8) & 255) + 0.0722 * cl(n & 255)
  }

  const contrast = (hex: string, bg = 0) => {
    const L = lum(hex)

    return (Math.max(L, bg) + 0.05) / (Math.min(L, bg) + 0.05)
  }

  it('lifts a near-invisible muted color to at least AA (4.5:1) in dark mode', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()
    // poseidon-style deep navy dim — ~1.9:1 on black before the floor.
    const { color } = fromSkin({ banner_dim: '#153C73' }, {})
    expect(contrast(color.muted)).toBeGreaterThanOrEqual(4.5)
  })

  it('preserves hue while lifting — a crimson muted stays reddish, not gray/white', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()
    const { color } = fromSkin({ banner_dim: '#6B1717' }, {})
    const n = parseInt(color.muted.replace('#', ''), 16)
    const r = (n >> 16) & 255
    const g = (n >> 8) & 255
    const b = n & 255
    expect(contrast(color.muted)).toBeGreaterThanOrEqual(4.5)
    expect(r).toBeGreaterThan(g) // still red-dominant
    expect(r).toBeGreaterThan(b)
  })

  it('leaves already-readable colors untouched', async () => {
    const { fromSkin } = await importThemeWithCleanEnv()
    // #c9d1d9 is ~13:1 on black — well above the floor, must not change.
    const { color } = fromSkin({ ui_text: '#c9d1d9' }, {})
    expect(color.text).toBe('#c9d1d9')
  })

  it('does NOT lift colors in light mode (dark text is correct on light bg)', async () => {
    const { fromSkin } = await importThemeWithEnv({ FORECAST_TUI_LIGHT: '1' })
    const { color } = fromSkin({ banner_dim: '#153C73' }, {})
    // Light mode: the dark dim is intended; the dark-floor must be a no-op.
    expect(color.muted).toBe('#153C73')
  })
})
