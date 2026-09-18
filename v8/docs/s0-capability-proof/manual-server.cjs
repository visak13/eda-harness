// Serves ONLY two synthetic fixture files on loopback; never the repository tree.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
function createServer() {
  return http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
    const file = pathname === '/' ? 'manual.html' : pathname === '/manual-worker.js' ? 'manual-worker.js' : null;
    if (!file || request.method !== 'GET') { response.writeHead(404); response.end(); return; }
    fs.readFile(path.join(__dirname, file), (error, bytes) => {
      if (error) { response.writeHead(500); response.end('Fixture read failed'); return; }
      response.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'text/javascript' : 'text/html',
                              'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'});
      response.end(bytes);
    });
  });
}
module.exports = { createServer };
if (require.main === module) {
  const server = createServer();
  server.on('error', error => { console.error('S0 fixture server failed:', error.code); process.exitCode = 1; });
  server.listen(0, '127.0.0.1', () => console.log(`S0 fixture ready http://127.0.0.1:${server.address().port}/ owned_pid=${process.pid} (Ctrl+C stops only this server)`));
}
