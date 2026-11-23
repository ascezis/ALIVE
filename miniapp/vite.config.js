import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const apiPort = process.env.ALIVE_API_PORT ?? '4174';
const proxy = { '/api': `http://127.0.0.1:${apiPort}` };

export default defineConfig({
  server: {
    proxy,
    fs: {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../src/lfk-spec.json', import.meta.url)),
      ],
    },
  },
  preview: { proxy },
});
