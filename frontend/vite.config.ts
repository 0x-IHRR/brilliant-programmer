import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

export default defineConfig({
  build: { outDir: "../backend/app/frontend", emptyOutDir: true },
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 18173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:18080" },
  },
})
