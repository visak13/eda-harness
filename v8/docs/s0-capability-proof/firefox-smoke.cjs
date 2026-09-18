// Isolated API smoke only. NOT native Windows toast click/focus acceptance.
// Run: node docs/s0-capability-proof/firefox-smoke.cjs
const { firefox } = require('../../web/node_modules/playwright');
const http = require('node:http');
const assert = require('node:assert/strict');

const worker = `
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('message', event => {
  if (event.data === 'count-clients') event.waitUntil((async () => {
    const clients = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    event.ports[0].postMessage({count: clients.length});
  })());
});
`;
const server = http.createServer((request, response) => {
  if (request.url === '/sw.js') {
    response.writeHead(200, {'Content-Type': 'text/javascript', 'Cache-Control': 'no-store'});
    response.end(worker);
  } else if (request.url === '/') {
    response.writeHead(200, {'Content-Type': 'text/html', 'Cache-Control': 'no-store'});
    response.end('<!doctype html><title>S0 isolated API smoke</title><p>Synthetic page, no board credentials.</p>');
  } else {
    response.writeHead(404); response.end();
  }
});

(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    browser = await firefox.launch({headless: true});
    const context = await browser.newContext(); // disposable profile, never owner's
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    await page.goto(origin);
    const initial = await page.evaluate(async () => {
      await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      return {secure: isSecureContext, permission: Notification.permission,
              userAgent: navigator.userAgent};
    });
    assert.equal(initial.secure, true);
    await context.grantPermissions(['notifications'], {origin});
    const granted = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      await registration.showNotification('S0 synthetic API smoke', {tag: 's0-smoke'});
      const notices = await registration.getNotifications({tag: 's0-smoke'});
      const count = notices.length;
      notices.forEach(notice => notice.close());
      return {permission: Notification.permission, notificationCount: count};
    });
    assert.equal(granted.permission, 'granted');
    assert.equal(granted.notificationCount, 1);
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
    const second = await context.newPage();
    await second.goto(origin);
    const clients = await page.evaluate(() => new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      const timer = setTimeout(() => { channel.port1.close(); reject(new Error('worker timeout')); }, 5000);
      channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); resolve(event.data); };
      navigator.serviceWorker.controller.postMessage('count-clients', [channel.port2]);
    }));
    assert.equal(clients.count, 2);
    await context.clearPermissions();
    const cleared = await page.evaluate(() => Notification.permission);
    assert.notEqual(cleared, 'granted');
    console.log(JSON.stringify({status: 'api_smoke_pass', executable: firefox.executablePath(),
      version: browser.version(), origin, initial, granted, clients, cleared,
      native_clicks: 0, owner_installed_firefox_proven: false}, null, 2));
    await context.close();
  } catch (error) {
    console.error(JSON.stringify({status: 'api_smoke_failed', reason: error.message}));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})();
