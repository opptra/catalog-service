import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In production nginx serves the app and proxies /api to the server on the
    // same origin (see client/nginx.conf). Mirroring that here keeps dev and
    // prod on one code path — the client always calls a relative /api, so
    // cross-origin behaviour never differs between the two.
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
