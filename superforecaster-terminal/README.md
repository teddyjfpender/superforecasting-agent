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
src/                 the terminal UI (screens F1-F12 + MSG/MOST/ERN/CORR/GIP/SF,
                     watchlist, portfolio, news, chat, prediction markets,
                     command palette, themes)
src/termdApi.ts      the typed client for the deployed termd data plane
src/forecastApi.ts   the typed client for the local Superforecaster bridge (SF screen)
src/forecastProvider.tsx  SF data provider — a sibling to the finance provider
                     (own context + poll loop; never touches the finance plane)
src/forecastScreen.tsx    the SF desk: forecast book + distribution / analyst read
src/forecastFormat.ts + src/forecastTypes.ts  pure render helpers + wire types,
                     ported verbatim from the `forecast` TUI (no ui-tui dependency)
api/termd.js         Vercel serverless proxy: forwards /api/termd/* -> TERMD_API_BASE_URL,
                     injecting the auth token server-side (token never reaches the browser)
vite.config.ts       dev proxy: /termd-api -> TERMD_API_BASE_URL (Authorization header);
                     /forecast-api -> the local forecast bridge (127.0.0.1:8787)
vercel.json          deploy config (build with bun, output dist/)
.env.example         the wiring template
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
bun run dev        # finance plane only — http://localhost:5173
bun run dev:sf     # one command: forecast bridge + Vite (SF screen enabled)
bun run typecheck
bun run build      # -> dist/
bun run test:frontend
```

## Superforecaster desk (SF screen)

The **SF** screen surfaces the `forecast` TUI's `/desk` workspace inside the
terminal: the forecast book, headline + distribution intervals, the analyst
QUICK READ (how it feels / how it thinks / watching for / be aware), a
time-series trend with a confidence band, the outcome distribution, related
(cross-pollinated) forecasts with shared-source warnings, reasoning, and recent
evidence — all from one round trip. Reach it via the command line (`SF`), the
command palette (⌘K → SF), or the F1 help menu.

Because the forecast ledger is **local** (SQLite at
`~/.superforecasting-agent/forecasting/forecasting.db`), the data path is
dev-only and runs through a small read-only bridge rather than the deployed
backend:

```
forecasting.db
  → forecasting/webbridge.py   (stdlib HTTP, read-only, 127.0.0.1:8787)
  → Vite /forecast-api proxy
  → src/forecastApi.ts → src/forecastProvider.tsx → SF screen
```

The bridge (`forecasting/webbridge.py`, in the repo's `forecasting` package)
exposes `GET /forecast/{health,workspace,dashboard,question/<id>}` — the same
data the gateway serves the Ink TUI. It is **isolated from the termd finance
plane**: a separate provider, context, proxy path, and env flag. To run it:

```sh
# one command — starts the bridge AND Vite (SF enabled), tears both down on Ctrl-C
bun run dev:sf
```

`dev:sf` (`scripts/dev.ts`) runs `python3 -m forecasting.webbridge` from the repo
root and `vite` with `VITE_FORECAST_API_ENABLED=1`, prefixes the bridge's output,
and kills both when either exits or on Ctrl-C. Overrides: `FORECAST_BRIDGE_PORT`
(default 8787), `PYTHON` (default `python3`), `FORECAST_API_BASE_URL` (proxy
target). The same thing by hand, in two terminals:

```sh
python3 -m forecasting.webbridge                       # terminal 1
echo "VITE_FORECAST_API_ENABLED=1" >> .env.local && bun run dev   # terminal 2
```

Deployed builds leave `VITE_FORECAST_API_ENABLED` unset, so SF shows a "bridge
offline" notice instead of polling a dead endpoint. See `.env.example` for the
`FORECAST_*` / `VITE_FORECAST_*` knobs.

Later increments ("and more", all backed by the existing payload): a desk-wide
calibration / reliability view, multi-forecast overlay/compare, and a PIT /
distribution-quality histogram for resolved distribution forecasts.
