// Tier-B: pixel/image protocol encoders (Kitty, Sixel, iTerm2). PURE — RGBA
// bytes in, terminal escape string out. These are OPT-IN (HERMES_PIXEL_IMAGES)
// and intentionally NOT auto-wired into the ScrollBox render flow: the DECSTBM
// hardware-scroll fast-path can't track image escapes, so live in-flow image
// mounting remains a separate guarded spike (see the design doc). Use these for
// a pinned/non-scrolling region or an explicit "export image" action.

import { deflateSync } from 'node:zlib'

import { parseHex } from './color.js'
import type { ImageProtocol, TerminalCaps } from './types.js'

export const pickImageProtocol = (caps: TerminalCaps): ImageProtocol => caps.imageProtocol

export interface Raster {
  height: number
  rgba: Uint8Array // length = width*height*4, row-major
  width: number
}

const b64 = (bytes: Uint8Array): string => Buffer.from(bytes).toString('base64')

// ── Kitty graphics protocol (raw RGBA, f=32) — chunked base64, m=1 until last.
export const encodeKitty = (r: Raster, opts: { id?: number } = {}): string => {
  const payload = b64(r.rgba)
  const CHUNK = 4096
  const id = opts.id ?? 1
  const parts: string[] = []

  for (let i = 0; i < payload.length; i += CHUNK) {
    const slice = payload.slice(i, i + CHUNK)
    const more = i + CHUNK < payload.length ? 1 : 0
    const keys = i === 0 ? `a=T,f=32,s=${r.width},v=${r.height},i=${id},m=${more}` : `m=${more}`
    parts.push(`\x1b_G${keys};${slice}\x1b\\`)
  }

  return parts.join('')
}

// ── Sixel (DCS) — fixed 6×6×6 color cube; emits per-color sixel bands with RLE.
const cubeIndex = (r: number, g: number, b: number): number => {
  const q = (c: number): number => Math.round((c / 255) * 5)

  return q(r) * 36 + q(g) * 6 + q(b)
}

const cubeRGB = (idx: number): [number, number, number] => {
  const r = Math.floor(idx / 36)
  const g = Math.floor((idx % 36) / 6)
  const b = idx % 6
  const s = (c: number): number => Math.round((c / 5) * 100) // sixel 0..100 percent

  return [s(r), s(g), s(b)]
}

export const encodeSixel = (r: Raster): string => {
  const { height, rgba, width } = r

  const idxAt = (x: number, y: number): number => {
    const o = (y * width + x) * 4

    if ((rgba[o + 3] ?? 0) === 0) {
      return -1 // transparent
    }

    return cubeIndex(rgba[o] ?? 0, rgba[o + 1] ?? 0, rgba[o + 2] ?? 0)
  }

  let out = `\x1bP0;1;0q"1;1;${width};${height}`
  const used = new Set<number>()

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = idxAt(x, y)

      if (i >= 0) {
        used.add(i)
      }
    }
  }

  for (const i of used) {
    const [pr, pg, pb] = cubeRGB(i)
    out += `#${i};2;${pr};${pg};${pb}`
  }

  for (let band = 0; band < height; band += 6) {
    let first = true

    for (const color of used) {
      out += first ? `#${color}` : `$#${color}`
      first = false
      // Build the sixel char per column for this color in this 6-row band.
      const chars: number[] = []

      for (let x = 0; x < width; x++) {
        let bits = 0

        for (let row = 0; row < 6 && band + row < height; row++) {
          if (idxAt(x, band + row) === color) {
            bits |= 1 << row
          }
        }

        chars.push(bits)
      }

      // RLE-compress runs of identical sixel chars.
      for (let x = 0; x < width; ) {
        let run = 1

        while (x + run < width && chars[x + run] === chars[x]) {
          run++
        }

        const ch = String.fromCharCode(0x3f + chars[x]!)
        out += run >= 3 ? `!${run}${ch}` : ch.repeat(run)
        x += run
      }
    }

    out += '-' // next band
  }

  out += '\x1b\\'

  return out
}

// ── Minimal PNG (RGBA, filter 0) for iTerm2 OSC 1337 inline images.
const CRC_TABLE = (() => {
  const t = new Uint32Array(256)

  for (let n = 0; n < 256; n++) {
    let c = n

    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }

    t[n] = c >>> 0
  }

  return t
})()

const crc32 = (buf: Uint8Array): number => {
  let c = 0xffffffff

  for (let i = 0; i < buf.length; i++) {
    c = CRC_TABLE[(c ^ buf[i]!) & 0xff]! ^ (c >>> 8)
  }

  return (c ^ 0xffffffff) >>> 0
}

const u32 = (n: number): Uint8Array => Uint8Array.from([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255])

const chunk = (type: string, data: Uint8Array): Uint8Array => {
  const typeBytes = Uint8Array.from([...type].map(c => c.charCodeAt(0)))
  const body = new Uint8Array(typeBytes.length + data.length)
  body.set(typeBytes)
  body.set(data, typeBytes.length)

  return new Uint8Array([...u32(data.length), ...body, ...u32(crc32(body))])
}

export const encodePng = (r: Raster): Uint8Array => {
  const { height, rgba, width } = r
  const ihdr = new Uint8Array([...u32(width), ...u32(height), 8, 6, 0, 0, 0]) // 8-bit, RGBA, no interlace
  // Filtered scanlines: filter byte 0 (None) + row RGBA.
  const raw = new Uint8Array(height * (1 + width * 4))

  for (let y = 0; y < height; y++) {
    raw[y * (1 + width * 4)] = 0
    raw.set(rgba.subarray(y * width * 4, (y + 1) * width * 4), y * (1 + width * 4) + 1)
  }

  const idat = new Uint8Array(deflateSync(raw))
  const sig = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10])

  return new Uint8Array([...sig, ...chunk('IHDR', ihdr), ...chunk('IDAT', idat), ...chunk('IEND', new Uint8Array(0))])
}

export const encodeITerm2 = (r: Raster): string => {
  const png = encodePng(r)

  return `\x1b]1337;File=inline=1;width=auto;height=auto;size=${png.length}:${b64(png)}\x07`
}

// Dispatch to the active protocol; '' when none (caller falls back to cell-glyph).
export const encodeImage = (r: Raster, protocol: ImageProtocol): string => {
  switch (protocol) {
    case 'kitty':
      return encodeKitty(r)

    case 'sixel':
      return encodeSixel(r)

    case 'iterm2':
      return encodeITerm2(r)

    default:
      return ''
  }
}

// A producer so the image tier is demonstrable end-to-end: rasterize a heatmap
// matrix to RGBA (cellPx square pixels per matrix cell) using a colormap.
export const rasterizeHeatmap = (
  matrix: number[][],
  colormap: (t: number) => string,
  opts: { cellPx?: number; diverging?: boolean } = {}
): Raster => {
  const rows = matrix.filter(Array.isArray)
  const h = rows.length
  const w = h ? Math.max(...rows.map(r => r.length)) : 0
  const cellPx = Math.max(1, opts.cellPx ?? 8)
  let lo = Infinity
  let hi = -Infinity

  for (const row of rows) {
    for (const v of row) {
      if (Number.isFinite(v)) {
        lo = Math.min(lo, v)
        hi = Math.max(hi, v)
      }
    }
  }

  if (opts.diverging) {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1
    lo = -m
    hi = m
  }

  const span = hi - lo || 1
  const W = w * cellPx
  const H = h * cellPx
  const rgba = new Uint8Array(W * H * 4)

  for (let cy = 0; cy < h; cy++) {
    for (let cx = 0; cx < w; cx++) {
      const v = rows[cy]![cx]
      const t = Number.isFinite(v) ? Math.max(0, Math.min(1, ((v as number) - lo) / span)) : 0
      const [pr, pg, pb] = parseHex(colormap(t))

      for (let py = 0; py < cellPx; py++) {
        for (let px = 0; px < cellPx; px++) {
          const o = ((cy * cellPx + py) * W + (cx * cellPx + px)) * 4
          rgba[o] = pr
          rgba[o + 1] = pg
          rgba[o + 2] = pb
          rgba[o + 3] = 255
        }
      }
    }
  }

  return { height: H, rgba, width: W }
}
