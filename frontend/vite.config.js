import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // LicenseModal imports the LICENSE file at the repo root, outside this folder.
    fs: { allow: ['..'] },
    proxy: {
      // The backend refuses any request not addressed to 127.0.0.1:8100 (see
      // reject_foreign_requests in backend/app.py), so the proxy rewrites Host
      // and Origin to look like the app's own page.
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            // Only the dev page itself (a localhost origin) gets its Origin
            // rewritten. Any other Origin, such as a website posting to the dev
            // server, is passed through unchanged and the backend refuses it.
            const origin = req.headers.origin
            if (origin !== undefined && /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(origin)) {
              proxyReq.setHeader('Origin', 'http://127.0.0.1:8100')
            }
          })
        },
      },
    },
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
})
