import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The console talks to the FastAPI gateway only through /api, so the browser needs no CORS
// in development and the same relative URLs work behind a reverse proxy in production.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: true,
    port: Number(process.env.HACFEW_CONSOLE_PORT ?? 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: (process.env.HACFEW_API_URL && process.env.HACFEW_API_URL !== 'http://127.0.0.1:8010')
          ? process.env.HACFEW_API_URL
          : 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
