import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const termdTarget = env.TERMD_API_BASE_URL || env.VITE_TERMD_API_PROXY_TARGET;
  const termdToken = env.TERMD_API_TOKEN;
  const proxyHeaders = termdToken ? { authorization: `Bearer ${termdToken}` } : undefined;

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: termdTarget
        ? {
            "/termd-api": {
              target: termdTarget,
              changeOrigin: true,
              ws: true,
              headers: proxyHeaders,
              rewrite: (path: string) => path.replace(/^\/termd-api/, ""),
            },
          }
        : undefined,
    },
  };
});
