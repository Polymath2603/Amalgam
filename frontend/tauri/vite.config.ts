import { defineConfig } from "vite";
import type { Connect } from "vite";

export default defineConfig({
  root: "../webui",
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/frontend/tauri/**"],
    },
    proxy: {
      "/api": {
        target: "http:
        changeOrigin: true,
      },
      "/ws": {
        target: "ws:
        ws: true,
      },
    },
  },
  plugins: [
    {
      name: "static-rewrite",
      configureServer(server) {
        const handler: Connect.NextHandleFunction = (req, _res, next) => {
          if (req.url?.startsWith("/static/")) {
            req.url = req.url.slice(7);
          }
          next();
        };
        server.middlewares.use(handler);
      },
    },
  ],
});
