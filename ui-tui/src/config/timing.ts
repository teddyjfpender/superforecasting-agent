export const STREAM_BATCH_MS = 16
export const STREAM_IDLE_BATCH_MS = 16
export const STREAM_SCROLL_BATCH_MS = 96
export const STREAM_TYPING_BATCH_MS = 80
export const TYPING_IDLE_MS = 250
export const REASONING_PULSE_MS = 700
// Gateway stderr is a pure diagnostic-noise channel: under a free-tier failure
// storm (e.g. a run that fails every alert loudly) it can emit hundreds of lines
// a second, and each one used to drive its own TUI re-render — a runaway repaint.
// Coalesce the channel to at most a leading + one trailing flush per window so a
// burst costs a bounded number of renders (the newest line still wins).
export const GATEWAY_STDERR_COALESCE_MS = 200
