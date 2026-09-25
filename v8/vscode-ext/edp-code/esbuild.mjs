// One cjs bundle for code-server's Node extension host (strategyll-51e4dae0bc §4).
import * as esbuild from 'esbuild';

const production = process.argv.includes('--production');
await esbuild.build({
  entryPoints: ['src/vscode/extension.ts'], bundle: true, format: 'cjs',
  platform: 'node', target: 'node24',           // code-server's .node-version is 24.x
  external: ['vscode'],                          // provided by the host, never bundled
  outfile: 'dist/extension.js', sourcemap: !production, sourcesContent: false,
  minify: production, logLevel: 'warning',
});
