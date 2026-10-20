import { defineConfig } from 'vite';

export default defineConfig({
  define: { 'import.meta.env.VITE_PUBLIC_REPLAY': JSON.stringify('true') },
  build: {
    outDir: 'dist-stability',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        review: new URL('./index.html', import.meta.url).pathname,
        stability: new URL('./stability.html', import.meta.url).pathname,
      },
    },
  },
});
