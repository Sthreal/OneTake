import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

// Scope vitest's root-level discovery to project tests only.
// `data/` holds the user's agent scratch workspaces (gitignored) which can
// contain nested projects with their own test suites; vitest does not respect
// .gitignore, so we must exclude explicitly.
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./web-miniclaw/src', import.meta.url)),
      '@onetake/editor': fileURLToPath(
        new URL('./packages/onetake-editor/src/index.ts', import.meta.url),
      ),
      react: fileURLToPath(
        new URL('./web-miniclaw/node_modules/react', import.meta.url),
      ),
      'react-dom': fileURLToPath(
        new URL('./web-miniclaw/node_modules/react-dom', import.meta.url),
      ),
      'lucide-react': fileURLToPath(
        new URL('./web-miniclaw/node_modules/lucide-react', import.meta.url),
      ),
      'react-router-dom': fileURLToPath(
        new URL('./web-miniclaw/node_modules/react-router-dom', import.meta.url),
      ),
    },
  },
  test: {
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      'data/**',
      '.claude/**',
      'web-miniclaw/tests/e2e/**',
    ],
  },
});
