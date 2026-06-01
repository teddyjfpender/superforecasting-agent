# superforecaster-terminal

A high-contrast, dark-mode, 90s-terminal-style **Bloomberg-terminal** web UI. This
is the extracted `term` POC (Vite + React 19 + TypeScript + Tailwind 4), brought in
to become the web surface for the Superforecasting Agent. It is fully isolated from
the repo's other web targets:

- `web/` — the existing hermes-agent webapp (left untouched).
- `website/` — the Docusaurus docs site.
- `ui-tui/` — the Ink terminal UI.

## What's here vs. not

Extracted **webapp only** (frontend + serverless proxy + config). The Rust `termd`
data-plane backend is **not** vendored here — it stays deployed, and this app points
at it. Source: the standalone `term` repo.

```
src/            the terminal UI (screens F1-F12 + MSG/MOST/ERN/CORR/GIP, watchlist,
                portfolio, news, chat, prediction markets, command palette, themes)
src/termdApi.ts the typed client for the deployed termd data plane
api/termd.js    Vercel serverless proxy: forwards /api/termd/* -> TERMD_API_BASE_URL,
                injecting the auth token server-side (token never reaches the browser)
vite.config.ts  dev proxy: /termd-api -> TERMD_API_BASE_URL with Authorization header
vercel.json     deploy config (build with bun, output dist/)
.env.example    the wiring template
```

## Wiring (kept intact)

The UI talks to the deployed termd backend through a proxy that injects auth
server-side, so the JWT is never exposed to browser code:

- **dev:** Vite proxies `/termd-api/*` to `TERMD_API_BASE_URL` (set in `.env.local`).
- **prod (Vercel):** the `api/termd.js` function proxies `/api/termd/*` to
  `TERMD_API_BASE_URL`, using `TERMD_API_TOKEN` as a Vercel env var, with
  `VITE_TERMD_API_BASE_URL=/api/termd`.

Copy `.env.example` to `.env.local` and set `TERMD_API_BASE_URL` / `TERMD_API_TOKEN`
to the deployed backend. (`.env.local` is gitignored — secrets stay local.)

## Run

```sh
cd superforecaster-terminal
bun install
bun run dev        # http://localhost:5173
bun run typecheck
bun run build      # -> dist/
bun run test:frontend
```

## Roadmap: wiring in the Superforecasting Agent

Next phase (not done yet): surface the same features as the `forecast` TUI — and
more — inside this terminal. The agent's data is served by the Python gateway
(`tui_gateway/server.py`) over the `forecast.*` JSON-RPC methods
(`forecast.dashboard`, `forecast.workspace`, `forecast.question`,
`forecast.command`). The plan is to add a Superforecaster screen + data provider
(mirroring `termdApi.ts` / `providers.tsx`) that reads the forecast ledger
(desk, distributions, analyst write-ups, related forecasts, calibration) through a
proxy to the gateway, alongside the existing financial data plane.
