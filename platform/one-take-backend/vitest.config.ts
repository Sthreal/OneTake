import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

// Scope vitest's root-level discovery to project tests only.
// `data/` holds the user's agent scratch workspaces (gitignored) which can
// contain nested projects with their own test suites; vitest does not respect
// .gitignore, so we must exclude explicitly.
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./web/src', import.meta.url))
    },
  },
  test: {
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      'data/**',
      '.claude/**',
    ],
  },
});
