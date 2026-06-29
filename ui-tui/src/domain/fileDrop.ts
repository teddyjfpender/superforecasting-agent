// Cheap, side-effect-free mirror of the gateway's `starts_like_path` prefilter
// (hermes_cli/file_drop.py :: _detect_file_drop). Used purely to decide whether
// a submission *could* be a dragged/pasted file path.
//
// When it could NOT (the overwhelmingly common case — ordinary prose / a
// question / a slash-free message), the composer renders the user's own bubble
// OPTIMISTICALLY and skips waiting on the input.detect_drop round-trip, so the
// echo is always instant and never serializes behind an in-flight inline RPC.
//
// When it COULD be a path we keep the existing gated behavior (await
// detect_drop, then substitute the resolved/notice text) so the file-drop
// display semantics are byte-for-byte unchanged. Over-matching here only costs
// one extra (already-cheap) RPC wait on path-shaped input; it never changes
// behavior. The gateway remains the single source of truth for a real match.
export function couldBeFileDrop(text: string): boolean {
  const s = (text ?? '').trim()

  if (!s) {
    return false
  }

  const driveAt = (i: number): boolean =>
    s.length >= i + 3 && s[i + 1] === ':' && (s[i + 2] === '\\' || s[i + 2] === '/') && /[a-zA-Z]/.test(s[i]!)

  return (
    s.startsWith('/') ||
    s.startsWith('~') ||
    s.startsWith('./') ||
    s.startsWith('../') ||
    s.startsWith('file://') ||
    driveAt(0) ||
    s.startsWith('"/') ||
    s.startsWith('"~') ||
    s.startsWith("'/") ||
    s.startsWith("'~") ||
    s.startsWith('"./') ||
    s.startsWith('"../') ||
    s.startsWith("'./") ||
    s.startsWith("'../") ||
    ((s[0] === "'" || s[0] === '"') && driveAt(1))
  )
}
