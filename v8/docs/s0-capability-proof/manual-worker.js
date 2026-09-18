// Isolated synthetic-identity click proof. No board auth/feed/cache/push integration.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
let serial = Promise.resolve();
const valid = data => data && ['A', 'B'].includes(data.actor) &&
  /^[a-f0-9-]{36}$/.test(data.trial) && data.destination === `request-s0-${data.trial}`;
const windows = () => self.clients.matchAll({type: 'window', includeUncontrolled: true});
async function identify(client) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); resolve({client, actor: null}); }, 2000);
    channel.port1.onmessage = event => {
      clearTimeout(timer); channel.port1.close();
      resolve({client, actor: event.data.actor});
    };
    try { client.postMessage({type: 'who'}, [channel.port2]); }
    catch { clearTimeout(timer); channel.port1.close(); resolve({client, actor: null}); }
  });
}
async function report(data) {
  for (const client of await windows()) client.postMessage({type: 'outcome', ...data});
}
async function route(data, synthetic = false) {
  if (!valid(data)) return;
  const before = await windows();
  let identities = await Promise.all(before.map(identify));
  let selected = identities.find(item => item.actor === data.actor);
  if (!selected) {
    // Recheck immediately before any openWindow; unknown clients fail closed.
    identities = await Promise.all((await windows()).map(identify));
    selected = identities.find(item => item.actor === data.actor);
  }
  let outcome;
  if (selected) {
    try {
      await selected.client.focus();
      selected.client.postMessage({type: 'destination', actor: data.actor,
                                  trial: data.trial, destination: data.destination});
      outcome = 'reused';
    } catch { outcome = 'focus_failed_no_new_tab'; }
  } else if (identities.some(item => item.actor === null)) {
    outcome = 'unknown_client_no_new_tab';
  } else {
    try {
      // Synthetic actor/destination only; never live credentials or board selectors.
      const url = new URL('/', self.location.origin);
      url.searchParams.set('actor', data.actor);
      url.searchParams.set('destination', data.destination);
      await self.clients.openWindow(url.href);
      outcome = 'opened_no_eligible_client';
    } catch { outcome = 'open_failed'; }
  }
  await report({trial: data.trial, group: data.group, actor: data.actor,
                destination: data.destination, synthetic, outcome,
                clientsBefore: before.length, clientsAfter: (await windows()).length});
}
self.addEventListener('notificationclick', event => {
  const data = event.notification.data;
  event.notification.close();
  serial = serial.catch(() => {}).then(() => route(data));
  event.waitUntil(serial);
});
// Test seam is explicitly synthetic and reports as such; cannot count as native clicks.
self.addEventListener('message', event => {
  if (event.data?.type !== 'synthetic-route' || !event.source?.url?.startsWith(self.location.origin + '/')) return;
  serial = serial.catch(() => {}).then(() => route(event.data.data, true));
  event.waitUntil(serial);
});
