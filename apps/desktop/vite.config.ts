import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fixed port: tauri.conf.json points devUrl at it, so it must not drift.
const DEV_PORT = 1420;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: DEV_PORT,
    strictPort: true,
  },
  build: {
    // Tauri ships a current WebKit; no need to down-level for old browsers.
    target: "safari15",
    sourcemap: true,
  },
});
