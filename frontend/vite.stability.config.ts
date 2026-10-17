import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist-stability',
    emptyOutDir: true,
    rollupOptions: { input: new URL('./stability.html', import.meta.url).pathname },
  },
});
