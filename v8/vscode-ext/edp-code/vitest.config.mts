import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';

// `vscode` exists only inside the extension host; the units test src/core, which never imports it.
export default defineConfig({ test: {
  environment: 'node', include: ['test/**/*.test.ts'],
  alias: { vscode: resolve(import.meta.dirname, 'test/vscode-stub.ts') },
} });
