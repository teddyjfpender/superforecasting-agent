import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const termdTarget = env.TERMD_API_BASE_URL || env.VITE_TERMD_API_PROXY_TARGET;
  const termdToken = env.TERMD_API_TOKEN;
  const proxyHeaders = termdToken ? { authorization: `Bearer ${termdToken}` } : undefined;

  // Local Superforecaster bridge (read-only; serves the forecast ledger). Default
  // matches `forecasting/webbridge.py` (127.0.0.1:8787). Independent of termd.
  const forecastTarget = env.FORECAST_API_BASE_URL || "http://127.0.0.1:8787";

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        // Financial data plane — unchanged. Only mounted when a target is set.
        ...(termdTarget
          ? {
              "/termd-api": {
                target: termdTarget,
                changeOrigin: true,
                ws: true,
                headers: proxyHeaders,
                rewrite: (path: string) => path.replace(/^\/termd-api/, ""),
              },
            }
          : {}),
        // Superforecaster bridge — always mounted so SF works standalone.
        "/forecast-api": {
          target: forecastTarget,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/forecast-api/, ""),
        },
      },
    },
  };
});
