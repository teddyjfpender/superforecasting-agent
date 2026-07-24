/**
 * A tiny terminal "audiogram" — a row of block bars whose heights advance each frame,
 * giving a visual signal that the agent is speaking (TTS playback). The bars are
 * synthetic (an external audio player exposes no live amplitude), but the on/off is tied
 * to real playback start/stop, so it accurately reflects WHEN the agent is talking.
 */

const BARS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'] as const

/**
 * Render `width` block bars for the given animation frame. Each bar is phase-shifted on a
 * sine so the row "dances" smoothly and deterministically (same frame → same bars, which
 * keeps it testable and render-stable).
 */
export function audiogramFrame(frame: number, width = 7): string {
  let out = ''

  for (let i = 0; i < width; i++) {
    const v = (Math.sin(frame * 0.6 + i * 0.9) + 1) / 2 // 0..1
    const idx = Math.max(0, Math.min(BARS.length - 1, Math.round(v * (BARS.length - 1))))
    out += BARS[idx]
  }

  return out
}

/** The status-bar label shown while the agent is speaking, e.g. "🔊 Speaking ▅▇▃▁▂". */
export function speakingLabel(frame: number, width = 5): string {
  return `🔊 Speaking ${audiogramFrame(frame, width)}`
}
