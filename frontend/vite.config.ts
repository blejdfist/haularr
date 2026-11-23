import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { enhancedImages } from '@sveltejs/enhanced-img';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [tailwindcss(), enhancedImages(), sveltekit()],
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
  test: {
    passWithNoTests: true,
    include: ['tests/**/*.{test,spec}.{js,ts}'],
  },
});
