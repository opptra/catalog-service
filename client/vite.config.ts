import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // Prebundling this package breaks the WASM URL in Vite dev.
    exclude: ['@imagemagick/magick-wasm'],
  },
  assetsInclude: ['**/*.wasm'],
  server: {
    // Mirror prod nginx: SPA + /api on the same origin (see client/nginx.conf).
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
