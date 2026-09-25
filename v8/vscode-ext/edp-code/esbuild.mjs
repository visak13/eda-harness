// Two bundles (strategyll-51e4dae0bc §4, strategyll-5e3ecdb625 §1): the extension as one cjs file for
// code-server's Node host, and the chat webview as one IIFE + one CSS file that the provider INLINES
// into the view's HTML (no code splitting, no dynamic import, no import.meta.url assets).
import * as esbuild from 'esbuild';

const production = process.argv.includes('--production');
await esbuild.build({
  entryPoints: ['src/vscode/extension.ts'], bundle: true, format: 'cjs',
  platform: 'node', target: 'node24',           // code-server's .node-version is 24.x
  external: ['vscode'],                          // provided by the host, never bundled
  outfile: 'dist/extension.js', sourcemap: !production, sourcesContent: false,
  minify: production, logLevel: 'warning',
});
await esbuild.build({
  entryPoints: { webview: 'webview/main.ts', 'webview-css': 'webview/chat.css' }, bundle: true,
  format: 'iife', platform: 'browser', target: ['es2022'], outdir: 'dist', splitting: false,
  minify: production, sourcemap: false, legalComments: 'none', logLevel: 'warning',
});
