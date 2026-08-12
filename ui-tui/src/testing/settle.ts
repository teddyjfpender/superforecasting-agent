// ── Awaiting a SETTLED frame, not a lucky one ────────────────────────────────
//
// Ink component tests read a cumulative stdout buffer while the component is
// still resolving its data. The old pattern — `await tick(80)` then assert —
// asserts against whatever happened to be painted at 80ms, which under parallel
// vitest load is routinely the loading frame. That produced a moving set of
// "flaky" failures across deskView / obsidianView / modelPickerEffort.
//
// Quiescence-waiting ("return once the output stops changing") does NOT fix it:
// a component waiting on an unresolved promise is perfectly quiet, so a quiet
// window can and does open BEFORE the data lands. The only sound condition is
// the CONTENT the test is actually about.
//
// THE DEBUGGING TRAP THIS ALSO DEFUSES: the buffer is cumulative
// (`output += chunk`), so a failure caused by content never arriving *displays*
// as a stuck loading frame — vitest truncates the received string to roughly the
// first frame. That sends you hunting a phantom render bug. `waitForText` throws
// with the TAIL of the buffer (what is on screen now) plus the head, so the
// message describes the real state.

export type Read = () => string
export type Match = RegExp | string | ((text: string) => boolean)

export interface WaitOptions {
  /** Poll interval. Small enough to stay fast when the machine is idle. */
  interval?: number
  /** What we were waiting for, used in the failure message. */
  label?: string
  /**
   * Upper bound. Generous on purpose: it is a FAILURE deadline, not a sleep —
   * a passing test returns as soon as the content appears, so a large value
   * costs nothing on a healthy run and absorbs contention on a loaded one.
   */
  timeout?: number
}

const DEFAULT_TIMEOUT = 8000
const DEFAULT_INTERVAL = 5

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const describeMatch = (match: Match, label?: string): string => {
  if (label) {
    return label
  }

  if (typeof match === 'function') {
    return 'predicate'
  }

  return typeof match === 'string' ? JSON.stringify(match) : String(match)
}

const matches = (text: string, match: Match): boolean => {
  if (typeof match === 'function') {
    return match(text)
  }

  return typeof match === 'string' ? text.includes(match) : match.test(text)
}

/**
 * Poll until an arbitrary condition holds. Throws on timeout.
 *
 * For conditions that are not about rendered text — "the RPC has been
 * recorded", "the callback fired". Same principle: a keypress handler running
 * is an ASYNC event, so waiting a fixed number of milliseconds for it is the
 * same bug in a different costume.
 */
export const waitUntil = async (
  predicate: () => boolean,
  { interval = DEFAULT_INTERVAL, label = 'condition', timeout = DEFAULT_TIMEOUT }: WaitOptions = {}
): Promise<void> => {
  const deadline = Date.now() + timeout

  for (;;) {
    if (predicate()) {
      return
    }

    if (Date.now() >= deadline) {
      throw new Error(`waitUntil timed out after ${timeout}ms waiting for ${label}`)
    }

    await sleep(interval)
  }
}

/**
 * Poll until `match` holds against `read()`, then return the text.
 *
 * Throws a diagnostic error on timeout — never returns a half-rendered frame
 * for the caller to assert against, because a silent early return is exactly
 * what turned these into intermittent failures instead of loud ones.
 */
export const waitForText = async (read: Read, match: Match, options: WaitOptions = {}): Promise<string> => {
  const { interval = DEFAULT_INTERVAL, label, timeout = DEFAULT_TIMEOUT } = options
  const deadline = Date.now() + timeout

  for (;;) {
    const text = read()

    if (matches(text, match)) {
      return text
    }

    if (Date.now() >= deadline) {
      const head = text.slice(0, 400)
      const tail = text.slice(-1200)

      throw new Error(
        `waitForText timed out after ${timeout}ms waiting for ${describeMatch(match, label)}.\n` +
          `--- buffer head (the FIRST frame; what vitest would have shown you) ---\n${head}\n` +
          `--- buffer tail (what is actually on screen now) ---\n${tail}`
      )
    }

    await sleep(interval)
  }
}

/**
 * Wait until the output has been unchanged for `quietFor` ms.
 *
 * ONLY sound for "nothing more should happen" checks (negative assertions,
 * render-budget captures). It cannot prove that awaited data has arrived — use
 * `waitForText` for that. Kept explicit so the distinction is visible at the
 * call site rather than buried in a helper named "settle".
 */
export const waitForQuiet = async (
  read: Read,
  { interval = DEFAULT_INTERVAL, quietFor = 40, timeout = DEFAULT_TIMEOUT }: { interval?: number; quietFor?: number; timeout?: number } = {}
): Promise<string> => {
  const start = Date.now()
  let previous = read()
  let lastChange = Date.now()

  for (;;) {
    await sleep(interval)

    const current = read()

    if (current !== previous) {
      previous = current
      lastChange = Date.now()
    }

    if (Date.now() - lastChange >= quietFor || Date.now() - start >= timeout) {
      return current
    }
  }
}

/**
 * Wrap a mocked `gw.request` so a test can wait for the view's DATA rather than
 * guessing at a marker string.
 *
 * This is the sound version of "has it loaded yet": a component blocked on an
 * unresolved promise is exactly what `drain()` waits for, and unlike a quiet
 * window it cannot be satisfied by the component simply not having started yet.
 * `drain()` also handles CHAINED requests (status → note): after everything
 * settles it watches for a further request during a short grace window and
 * keeps draining while new ones appear.
 */
export const trackRequests = <A extends unknown[], R>(request: (...args: A) => R) => {
  let inFlight = 0
  let issued = 0

  const tracked = (...args: A): R => {
    const result = request(...args)

    issued += 1

    if (result && typeof (result as { then?: unknown }).then === 'function') {
      inFlight += 1
      void (result as unknown as Promise<unknown>).then(
        () => {
          inFlight -= 1
        },
        () => {
          inFlight -= 1
        }
      )
    }

    return result
  }

  const drain = async ({ grace = 30, timeout = DEFAULT_TIMEOUT }: { grace?: number; timeout?: number } = {}) => {
    const deadline = Date.now() + timeout

    for (;;) {
      await waitUntil(() => inFlight === 0, { label: 'in-flight requests to settle', timeout })

      const seen = issued

      await sleep(grace)

      // A follow-up request started during the grace window — keep draining.
      if (issued === seen) {
        return
      }

      if (Date.now() >= deadline) {
        throw new Error(`trackRequests.drain timed out after ${timeout}ms with requests still starting`)
      }
    }
  }

  return { drain, inFlight: () => inFlight, issued: () => issued, request: tracked }
}

/**
 * Wait for the content, THEN let the frame settle.
 *
 * The common shape for "the data landed and the view finished repainting":
 * correctness comes from the content check, and the short quiet window after it
 * absorbs the follow-up render without ever being load-bearing on its own.
 */
export const waitForSettled = async (read: Read, match: Match, options: WaitOptions & { quietFor?: number } = {}) => {
  const { quietFor = 24, ...rest } = options

  await waitForText(read, match, rest)

  return waitForQuiet(read, { quietFor, timeout: Math.max(200, quietFor * 8) })
}
