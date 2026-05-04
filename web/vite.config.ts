import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: {
    outDir: process.env.VITE_OUT_DIR ?? "../src/gcp_local/ui/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/_emulator": "http://localhost:4510",
    },
  },
});
