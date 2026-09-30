import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

// Frontend tests (roadmap item 20): jsdom + Testing Library. Reuses the Vite
// config so `.js` files are compiled as JSX exactly as in the real build.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.js'],
      include: ['src/**/*.test.{js,jsx,ts,tsx}'],
      css: false,
    },
  }),
);
