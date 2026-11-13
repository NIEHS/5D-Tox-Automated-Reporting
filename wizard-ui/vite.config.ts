import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA is served by the FastAPI app: the landing at /, the two workflows under
// /workflow. Assets resolve against base="/workflow/" (absolute), so the index
// served at any surface (/, /workflow/report) still loads its hashed assets via
// the /workflow static mount. Build lands in ../web_wizard. Dev server proxies
// /api to the running backend on :9000.
export default defineConfig({
  plugins: [react()],
  base: "/workflow/",
  build: {
    outDir: "../web_wizard",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:9000",
    },
  },
});
