import { defineConfig } from 'vite';

export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:7860', '/health': 'http://127.0.0.1:7860' } },
  build: {
    rollupOptions: {
      input: {
        review: new URL('./index.html', import.meta.url).pathname,
        workspace: new URL('./workspace.html', import.meta.url).pathname,
        stability: new URL('./stability.html', import.meta.url).pathname,
      },
    },
  },
});
