import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    // Vite 6 rejects requests whose Host header it doesn't recognize (DNS
    // rebinding protection). Needed to browse the app through a dev tunnel
    // (ngrok, etc.) for testing OAuth callbacks that must be publicly reachable.
    allowedHosts: true,
    // Keeps cookies first-party in development so the session cookie works.
    // Override when the API runs somewhere else: VITE_API_PROXY=http://localhost:8001
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: { environment: "jsdom", globals: true },
});
