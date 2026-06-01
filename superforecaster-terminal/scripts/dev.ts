/**
 * One-command dev for the Superforecaster web terminal.
 *
 *   bun run dev:sf
 *
 * Brings up BOTH halves of the SF data path and tears them down together:
 *   1. the read-only forecast bridge — `python3 -m forecasting.webbridge`, run
 *      from the repo root so the `forecasting` package resolves.
 *   2. the Vite dev server, with VITE_FORECAST_API_ENABLED=1 so the SF screen is
 *      live and `/forecast-api` is proxied to the bridge.
 *
 * It replaces the two-terminal dance:
 *   python3 -m forecasting.webbridge
 *   VITE_FORECAST_API_ENABLED=1 vite
 *
 * Ctrl-C — or either process exiting — stops both. The plain `bun run dev` is
 * unchanged: finance plane only, no Python required.
 *
 * Env overrides: FORECAST_BRIDGE_PORT (default 8787), PYTHON (default python3),
 * FORECAST_API_BASE_URL (proxy target; default http://127.0.0.1:<port>).
 */
import { resolve } from "node:path";

const webRoot = resolve(import.meta.dir, "..");
const repoRoot = resolve(webRoot, "..");

const port = (process.env.FORECAST_BRIDGE_PORT ?? "").trim() || "8787";
const python = (process.env.PYTHON ?? "").trim() || "python3";
const proxyTarget = process.env.FORECAST_API_BASE_URL || `http://127.0.0.1:${port}`;

const BRIDGE = "\x1b[34m[bridge]\x1b[0m";
const WEB = "\x1b[32m[web]\x1b[0m";

const children: ReturnType<typeof Bun.spawn>[] = [];
let shuttingDown = false;

function shutdown(code: number): void {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    try {
      child.kill();
    } catch {
      /* already gone */
    }
  }
  // give SIGTERM a beat to land, then exit this orchestrator.
  setTimeout(() => process.exit(code), 250);
}

// 1 ── the read-only forecast bridge (from the repo root) ─────────────────────
const bridge = Bun.spawn({
  cmd: [python, "-m", "forecasting.webbridge"],
  cwd: repoRoot,
  env: { ...process.env, FORECAST_BRIDGE_PORT: port, PYTHONUNBUFFERED: "1" },
  stdout: "pipe",
  stderr: "pipe",
  onExit(_proc, exitCode) {
    if (shuttingDown) return;
    console.error(
      `\n${BRIDGE} exited (code ${exitCode ?? "?"}). Is \`${python}\` on PATH and the ` +
        `forecasting package importable from ${repoRoot}?`,
    );
    shutdown(exitCode ?? 1);
  },
});
children.push(bridge);
void pipePrefixed(bridge.stdout, BRIDGE);
void pipePrefixed(bridge.stderr, BRIDGE);

// 2 ── Vite, with the SF screen enabled + proxy pointed at the bridge ─────────
const web = Bun.spawn({
  cmd: ["bun", "run", "dev"],
  cwd: webRoot,
  env: {
    ...process.env,
    VITE_FORECAST_API_ENABLED: "1",
    FORECAST_API_BASE_URL: proxyTarget,
  },
  stdin: "inherit",
  stdout: "inherit",
  stderr: "inherit",
  onExit(_proc, exitCode) {
    if (!shuttingDown) shutdown(exitCode ?? 0);
  },
});
children.push(web);

for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.on(sig, () => shutdown(0));
}

console.log(
  `${BRIDGE} http://127.0.0.1:${port}   ${WEB} starting Vite (SF screen enabled) — URL below.  Ctrl-C stops both.`,
);
void probeBridge();

// ── helpers ──────────────────────────────────────────────────────────────────

/** Forward a child stream line-by-line with a colored tag prefix. */
async function pipePrefixed(
  stream: ReadableStream<Uint8Array> | undefined,
  tag: string,
): Promise<void> {
  if (!stream) return;
  const decoder = new TextDecoder();
  let buffered = "";
  for await (const chunk of stream) {
    buffered += decoder.decode(chunk, { stream: true });
    const lines = buffered.split("\n");
    buffered = lines.pop() ?? "";
    for (const line of lines) console.log(`${tag} ${line}`);
  }
  if (buffered.trim()) console.log(`${tag} ${buffered}`);
}

/** Poll the bridge health endpoint and log once it answers (non-blocking). */
async function probeBridge(): Promise<void> {
  const url = `http://127.0.0.1:${port}/forecast/health`;
  for (let attempt = 0; attempt < 40 && !shuttingDown; attempt += 1) {
    try {
      const res = await fetch(url);
      if (res.ok) {
        console.log(`${BRIDGE} health ok — forecast desk wired`);
        return;
      }
    } catch {
      /* bridge not up yet */
    }
    await Bun.sleep(250);
  }
}
