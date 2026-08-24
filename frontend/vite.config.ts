import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    // Keeps cookies first-party in development so the session cookie works.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
  test: { environment: "jsdom", globals: true },
});
