import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 15173, strictPort: true, proxy: { '/api': 'http://localhost:18000' } },
  preview: { port: 15173, strictPort: true },
})
