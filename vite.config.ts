import { defineConfig, transformWithEsbuild } from 'vite';
import react from '@vitejs/plugin-react';

// Code that only the admin area uses goes to assets/admin/, which nginx hands
// out only to a signed-in admin (deployment/nginx/site.conf), so a visitor
// never downloads the admin screens.
const ADMIN_SOURCE = /[\\/]src[\\/]pages[\\/](?:Admin[\\/]|AdminPanel\.)/;

// A lazy chunk whose entry is an admin page holds only what that page alone
// needs (anything the public site also uses lands in a shared chunk), so it
// is admin-only even when it pulls in a component from src/components.
function isAdminOnlyChunk(chunk: { facadeModuleId?: string | null; moduleIds?: readonly string[] }): boolean {
  if (chunk.facadeModuleId && ADMIN_SOURCE.test(chunk.facadeModuleId)) return true;
  const own = (chunk.moduleIds || []).filter((id) => !id.includes('node_modules') && !id.startsWith('\0'));
  return own.length > 0 && own.every((id) => ADMIN_SOURCE.test(id));
}

export default defineConfig({
  plugins: [
    {
      name: 'treat-js-files-as-jsx',
      async transform(code, id) {
        if (!id.match(/src\/.*\.js$/)) return null;
        return transformWithEsbuild(code, id, {
          loader: 'jsx',
          jsx: 'automatic',
        });
      },
    },
    react(),
  ],
  optimizeDeps: {
    esbuildOptions: {
      loader: { '.js': 'jsx' },
    },
  },
  worker: {
    format: 'es',
  },
  define: {
    'process.env': {},
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
  },
  build: {
    outDir: 'dist',
    // Source maps carry the original source; only build them when asked to.
    sourcemap: process.env.GENERATE_SOURCEMAP === 'true',
    rollupOptions: {
      output: {
        chunkFileNames: (chunk) =>
          isAdminOnlyChunk(chunk) ? 'assets/admin/[name]-[hash].js' : 'assets/[name]-[hash].js',
      },
    },
  },
});
