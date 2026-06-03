import type { PanelSection } from '../types.js'

export const AUTH_EXPIRED_TITLE = 'Sign-in Required'

// Matches the auth-expiry / 401 signatures that arrive (as a stringified
// provider error) from the gateway when the model provider's credential has
// expired or been revoked — e.g. "...'code': 'token_expired'... 'status': 401".
export const AUTH_EXPIRED_RE =
  /token_expired|invalid_token|invalid_grant|authentication token is expired|sign(?:ing)? in again|\b401\b[\s\S]*(?:unauthorized|auth|expired|api[\s_-]?key)/i

// Shown instead of dumping the raw provider error dict. Provider-agnostic on
// purpose: `/model` reveals which provider is current and its sign-in state,
// and `auth add <provider>` re-runs the sign-in for OAuth/subscription
// providers (e.g. openai-codex, anthropic, nous, xai-oauth).
export const buildAuthExpiredSections = (): PanelSection[] => [
  {
    text:
      "Your model provider's sign-in token has expired, so the agent can't reach the " +
      'model right now. Nothing was lost — you just need to sign in again.'
  },
  {
    rows: [
      ['/model', 'see your current provider and sign in again, in-place'],
      ['terminal', 'superforecasting-agent auth add <provider>  (re-runs the sign-in)'],
      ['/api-key', 'if your provider uses an API key, set a fresh one']
    ],
    title: 'Re-authenticate (any one)'
  },
  {
    text: 'Then send your request again. Unsure which provider? `/model` shows the current one.'
  }
]
