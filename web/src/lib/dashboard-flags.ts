declare global {
  interface Window {
    /** Set true by the server only when the dashboard embeds the TUI chat. */
    __SUPERFORECASTING_AGENT_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    __FORECAST_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __HERMES_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __HERMES_DASHBOARD_TUI__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat. */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__SUPERFORECASTING_AGENT_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  if (window.__FORECAST_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  if (window.__HERMES_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  return window.__HERMES_DASHBOARD_TUI__ === true;
}
