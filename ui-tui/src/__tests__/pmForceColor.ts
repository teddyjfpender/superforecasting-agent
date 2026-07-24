// Force truecolor so the ink render emits theme-token SGR under the non-TTY test
// stream (chalk reads FORCE_COLOR at import time; this side-effect module MUST be
// imported before chalk / @hermes/ink so supports-color picks it up). The prior
// value is captured so the test file can restore it and not leak colour into
// sibling suites (which would enlarge frame buffers and worsen keypress-timing
// flakes elsewhere).
export const PRIOR_FORCE_COLOR = process.env.FORCE_COLOR
export const PRIOR_NO_COLOR = process.env.NO_COLOR

delete process.env.NO_COLOR
process.env.FORCE_COLOR = '3'
