import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: Number(process.env.TEXA_WEB_PORT ?? 15173), strictPort: true, proxy: { '/api': process.env.TEXA_API_TARGET ?? 'http://localhost:18000' } },
  preview: { port: 15173, strictPort: true },
})
