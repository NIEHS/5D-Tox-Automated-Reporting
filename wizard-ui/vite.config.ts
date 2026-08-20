import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The wizard is served by the FastAPI app under /wizard, so assets must resolve
// relative to that base. The build lands in ../web_wizard, which background_server
// mounts at /wizard. The dev server proxies /api to the running backend on :9000.
export default defineConfig({
  plugins: [react()],
  base: "/wizard/",
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
