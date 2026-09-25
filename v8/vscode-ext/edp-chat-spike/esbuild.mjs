// Throwaway C1 spike bundle; reuses edp-code's esbuild so the spike adds no node_modules.
import { createRequire } from 'node:module';
const esbuild = createRequire(import.meta.url)('../edp-code/node_modules/esbuild');
await esbuild.build({
  entryPoints: ['src/extension.ts'], bundle: true, format: 'cjs',
  platform: 'node', target: 'node24', external: ['vscode'],
  outfile: 'dist/extension.js', logLevel: 'warning',
});
