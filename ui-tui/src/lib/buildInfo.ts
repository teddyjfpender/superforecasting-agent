import type { BuildInfoPayload } from '../gatewayTypes.js'

// ── Which build am I actually running? ────────────────────────────────────────
//
// The gateway ships a `BuildInfoPayload` on `gateway.ready` (immediately, from
// the already-cached background update check) and again on `session.info` (by
// which point that check has usually landed). These are the PURE formatters the
// two surfaces share, so the wording can be pinned by unit tests and can never
// drift between them.
//
// Why this exists at all: a pipx-installed build freezes its own TUI bundle
// inside its venv (`superforecasting_agent/runtime/tui_dist/entry.js`), so repo-side rebuilds never
// reach it. Without a version on screen an operator can run a months-old binary
// while watching fixes land in git — which is exactly what happened.
//
// STALENESS IS NEVER RECOMPUTED HERE. `stale` is the server's verdict; the TUI
// only renders it. When the box is offline (or the cache is cold) every remote
// field is simply absent and every helper below degrades to the version alone —
// no error state, no "checking…" spinner, nothing to hang on.

/** `"v0.19.0"`, or `"v0.19.0 (2026.7.4)"` when the build stamped a date. */
export const buildVersionLabel = (build?: BuildInfoPayload | null): string => {
  if (!build?.version) {
    return ''
  }

  return build.release_date ? `v${build.version} (${build.release_date})` : `v${build.version}`
}

/** True only when the SERVER says this build is behind a published release. */
export const isBuildStale = (build?: BuildInfoPayload | null): boolean => Boolean(build?.stale)

/**
 * The headline for a stale build — names both versions when the newer one is
 * known, and stays honest ("update available") when only the verdict arrived.
 */
export const staleHeadline = (build?: BuildInfoPayload | null): string => {
  if (!isBuildStale(build) || !build?.version) {
    return ''
  }

  if (build.latest_version) {
    return `Update available — running v${build.version}, latest is v${build.latest_version}`
  }

  const behind = build.behind

  if (typeof behind === 'number' && behind > 0) {
    return `Update available — running v${build.version}, ${behind} commit${behind === 1 ? '' : 's'} behind`
  }

  return `Update available — running v${build.version}`
}

/**
 * The concrete command that REPLACES this build, resolved server-side per
 * install lane (a checkout rebuilds + reinstalls; a wheel re-runs the one-line
 * installer). Empty when the gateway could not name one.
 */
export const staleRemedy = (build?: BuildInfoPayload | null): string =>
  isBuildStale(build) ? (build?.remedy ?? '') : ''

/**
 * One line for a dense surface (the help overlay's header): the version, plus a
 * trailing update flag when stale. Never empty-pads — callers drop it when ''.
 */
export const buildSummaryLine = (build?: BuildInfoPayload | null): string => {
  const label = buildVersionLabel(build)

  if (!label) {
    return ''
  }

  if (!isBuildStale(build)) {
    return label
  }

  return build?.latest_version ? `${label} · update available: v${build.latest_version}` : `${label} · update available`
}
