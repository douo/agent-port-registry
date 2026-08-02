import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The bundle is committed into the Python package so end users never need Node.
const PY_STATIC_DIR = '../src/apr/webui/static'

// Dev server proxies the API to a locally running `svcctl serve --web`.
const API_TARGET = process.env.APR_API ?? 'http://127.0.0.1:17989'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: PY_STATIC_DIR,
    emptyOutDir: true,
    // No sourcemaps: the bundle is committed, and a 1.7 MB .map churning on
    // every UI tweak is not worth it. Use `npm run dev` for debugging.
    sourcemap: false,
  },
  server: {
    port: 5273,
    proxy: {
      '/v1': API_TARGET,
      '/healthz': API_TARGET,
    },
  },
})
