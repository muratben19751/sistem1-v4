import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const DEFAULT_API_TARGET = 'http://localhost:3500';

function resolveApiTarget(raw: string): string {
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new Error('Unsupported protocol');
    }
    return parsed.origin;
  } catch {
    return DEFAULT_API_TARGET;
  }
}

function resolveWsTarget(raw: string): string {
  try {
    const parsed = new URL(raw);
    if (parsed.protocol === 'http:') parsed.protocol = 'ws:';
    else if (parsed.protocol === 'https:') parsed.protocol = 'wss:';
    else if (parsed.protocol !== 'ws:' && parsed.protocol !== 'wss:') throw new Error('Unsupported protocol');
    return parsed.origin;
  } catch {
    return 'ws://localhost:3500';
  }
}

const apiTarget = resolveApiTarget(process.env.VITE_API_TARGET || DEFAULT_API_TARGET);
const wsTarget = resolveWsTarget(process.env.VITE_API_TARGET || DEFAULT_API_TARGET);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: Number(process.env.VITE_PORT) || 5200,
    allowedHosts: true,
    proxy: {
      '/api': apiTarget,
      '/ws': {
        target: wsTarget,
        ws: true,
      },
    },
  },
});
