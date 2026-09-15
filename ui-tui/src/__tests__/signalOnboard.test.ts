import { describe, expect, it } from 'vitest'

import { QR_MARGIN, qrLines, signalQrLayout } from '../lib/qrRender.js'
import { needsCaptcha, parseAccounts, parseLinkUri } from '../lib/signalOnboard.js'

describe('parseLinkUri', () => {
  it('extracts the modern sgnl://linkdevice URI', () => {
    const out = 'Open Signal and scan:\nsgnl://linkdevice?uuid=abc-123&pub_key=Base64%2Bkey%3D\nWaiting…'
    expect(parseLinkUri(out)).toBe('sgnl://linkdevice?uuid=abc-123&pub_key=Base64%2Bkey%3D')
  })

  it('extracts the legacy tsdevice URI', () => {
    expect(parseLinkUri('tsdevice:/?uuid=xyz&pub_key=k')).toBe('tsdevice:/?uuid=xyz&pub_key=k')
  })

  it('returns empty when no link is present', () => {
    expect(parseLinkUri('just some logging output')).toBe('')
  })
})

describe('needsCaptcha', () => {
  it('detects a captcha-required register failure', () => {
    expect(needsCaptcha('Captcha required for verification')).toBe(true)
    expect(needsCaptcha('Invalid captcha given, please provide a new one')).toBe(true)
  })

  it('is false for unrelated output', () => {
    expect(needsCaptcha('Rate limited, try again later')).toBe(false)
    expect(needsCaptcha('Verification code sent')).toBe(false)
  })
})

describe('parseAccounts', () => {
  it('pulls + de-dupes phone numbers from listAccounts output', () => {
    const out = 'Number: +15551112222\nNumber: +15553334444\n+15551112222 (path: ...)'
    expect(parseAccounts(out)).toEqual(['+15551112222', '+15553334444'])
  })
})

describe('qrLines', () => {
  it('renders a square half-block grid with a quiet-zone margin', () => {
    const lines = qrLines('sgnl://linkdevice?uuid=abc&pub_key=def')
    expect(lines.length).toBeGreaterThan(10)
    // every line is the same width (square QR + 2*margin)
    const widths = new Set(lines.map(l => l.length))
    expect(widths.size).toBe(1)
    // only the block/space glyphs are used
    expect(lines.join('')).toMatch(/^[█▀▄ ]+$/u)
    // width accounts for both quiet-zone margins
    expect([...widths][0]).toBeGreaterThan(QR_MARGIN * 2)
  })
})

describe('Signal QR sizing', () => {
  const lines = qrLines('sgnl://linkdevice?uuid=12345678-1234-1234-1234-123456789012&pub_key=' + 'a'.repeat(64))

  it('retains a complete white quiet zone, including top and bottom rows', () => {
    expect(QR_MARGIN).toBe(4)

    for (const line of [...lines.slice(0, 2), ...lines.slice(-2)]) {
      expect(line.trim()).toBe('')
    }

    for (const line of lines) {
      expect(line.slice(0, QR_MARGIN).trim()).toBe('')
      expect(line.slice(-QR_MARGIN).trim()).toBe('')
    }
  })

  it('grows beyond the old 36-row cap and respects both screen dimensions', () => {
    for (const cols of [40, 60, 80, 99, 100, 120, 200]) {
      for (const rows of [20, 24, 40, 50, 80]) {
        const layout = signalQrLayout(lines, cols, rows)
        expect(layout.height).toBeLessThanOrEqual(rows - 2)

        if (layout.fits) {
          expect(lines.length + 8).toBeLessThanOrEqual(layout.height)
          expect(lines[0]!.length + 6).toBeLessThanOrEqual(layout.width)
          expect(layout.width).toBeLessThanOrEqual(cols)
        }
      }
    }

    expect(signalQrLayout(qrLines('x'.repeat(300)), 120, 80).height).toBeGreaterThan(36)
  })

  it('replaces a clipped code with a resize hint and restores it at the required size', () => {
    const small = signalQrLayout(lines, 80, 24)
    expect(small.fits).toBe(false)
    expect(signalQrLayout(lines, small.minCols, small.minRows).fits).toBe(true)
  })
})
