import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    // The FastAPI backend from tasks 1-2. Proxied so the browser sees one origin
    // and no CORS configuration is needed for the demo.
    proxy: { '/api': { target: 'http://localhost:8001', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
});
