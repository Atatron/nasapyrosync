import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const API = process.env.PYROSYNC_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '127.0.0.1', port: 5173, proxy: { '/api': API } },
  preview: { host: '127.0.0.1', port: 4173, proxy: { '/api': API } },
  build: { chunkSizeWarningLimit: 1500 },
})
