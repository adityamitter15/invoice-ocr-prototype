import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // host: true makes Vite listen on both IPv4 and IPv6, so the email reset
    // link (which uses 127.0.0.1) reaches the dev server even when macOS
    // resolves "localhost" to ::1 by default.
    host: true,
    port: 5173,
    strictPort: true,
  },
})
