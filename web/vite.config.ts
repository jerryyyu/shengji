import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin /api in dev: the session cookie is set and read on one
    // host, so no CORS and nothing differs from the served build. The
    // websocket still goes straight to :8000 (ws.ts); cookies are per host,
    // not per port, so it carries the same cookie.
    proxy: { "/api": "http://localhost:8000" },
  },
})
