import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (err: any) => {
            if (err.code === 'EPIPE' || err.code === 'ECONNRESET') return;
          });
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            const originalEmit = socket.emit;
            socket.emit = function (event: string | symbol, ...args: any[]) {
              if (event === 'error') {
                const err = args[0] as any;
                if (err && (err.code === 'EPIPE' || err.code === 'ECONNRESET')) {
                  return false;
                }
              }
              return originalEmit.apply(this, [event, ...args]);
            };
          });
        },
      },
    },
  },
});
