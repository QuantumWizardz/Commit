// dashboard/vite.config.js — build settings for the dashboard.
//
// `npm run build` writes the app to dashboard/dist/, which the Commit app serves at http://127.0.0.1:8765/.
// `npm run dev` (optional, for editing the UI) starts Vite's dev server and forwards /api requests to the
// running Commit app. Because the dev page does not get the pairing token embedded, start it with:
//     COMMIT_TOKEN=<token from Settings> npm run dev
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const COMMIT_APP = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: COMMIT_APP,
        changeOrigin: true, // sends Host: 127.0.0.1:8765, which the Commit app accepts
        headers: { "X-Commit-Token": process.env.COMMIT_TOKEN || "" },
      },
    },
  },
});
