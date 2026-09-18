/* Open-tab notifications only. Deliberately no fetch, push or cache handlers. */
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
const protocol = 'edp8-notifications-v1';
let serial = Promise.resolve();
const recentClicks = new Map();
const valid = data => data && typeof data.actor === 'string' && data.actor.length <= 200 &&
  /^ev-[a-zA-Z0-9-]+$/.test(data.request) && typeof data.url === 'string' &&
  /^\/ui\/(epic|ticket)\/[a-zA-Z0-9.-]+\?request=ev-[a-zA-Z0-9-]+(#m-[a-zA-Z0-9-]+)?$/.test(data.url) &&
  new URL(data.url, self.location.origin).searchParams.get('request') === data.request;
const windows = async () => (await self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
  .filter(client => { const url = new URL(client.url); return url.origin === self.location.origin && /^\/ui(\/|$)/.test(url.pathname); });
function ask(client, type, data) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); resolve(null); }, 2500);
    channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); resolve(event.data); };
    try { client.postMessage({ protocol, type, ...data }, [channel.port2]); }
    catch { clearTimeout(timer); channel.port1.close(); resolve(null); }
  });
}
function ledger(key, remove = false) {
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open(protocol, 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore('seen');
    opening.onerror = () => reject(new Error('Notification storage unavailable'));
    opening.onsuccess = () => {
      const db = opening.result;
      const tx = db.transaction('seen', 'readwrite');
      const store = tx.objectStore('seen');
      let claimed = false;
      if (remove) store.delete(key);
      else {
        const read = store.get(key);
        read.onsuccess = () => {
          if (read.result === undefined) { store.put(Date.now(), key); claimed = true; }
        };
        // A bounded atomic ledger across tabs and worker restarts. Oldest entries expire.
        const all = store.openCursor();
        const entries = [];
        all.onsuccess = () => {
          const cursor = all.result;
          if (cursor) { entries.push([cursor.key, cursor.value]); cursor.continue(); }
          else {
            entries.sort((a, b) => b[1] - a[1]);
            entries.forEach(([id, at], index) => {
              if (id !== key && (index >= 999 || at < Date.now() - 7 * 86400000)) store.delete(id);
            });
          }
        };
      }
      tx.oncomplete = () => { db.close(); resolve(claimed); };
      tx.onerror = tx.onabort = () => { db.close(); reject(new Error('Notification storage unavailable')); };
    };
  });
}
async function show(source, data, test) {
  if (!source || !valid(data)) return { error: 'Invalid notification request' };
  const eligible = (await windows()).some(client => client.id === source.id);
  if (!eligible) return { error: 'Not a board tab' };
  const answer = await ask(source, 'authorize', { request: data.request, test });
  if (!answer || answer.actor !== data.actor || (!test && answer.url !== data.url)) return { error: 'Request unavailable' };
  const key = JSON.stringify([data.actor, data.request]);
  if (!test && !(await ledger(key))) return { shown: false };
  try {
    await self.registration.showNotification(test ? 'Board notification test' : 'Board needs your attention', {
      body: test ? 'Notifications work while a board tab stays open.' : 'Open the board to view your request.',
      tag: key, data: { actor: data.actor, request: data.request, url: data.url, test },
    });
    return { shown: true };
  } catch {
    if (!test) await ledger(key, true);
    return { error: 'Could not show notification. Check browser permission.' };
  }
}
async function route(data) {
  if (!valid(data)) return;
  const key = JSON.stringify([data.actor, data.request]);
  if ((recentClicks.get(key) || 0) > Date.now() - 5000) return;
  recentClicks.set(key, Date.now());
  for (const [id, at] of recentClicks) if (at < Date.now() - 5000) recentClicks.delete(id);
  const identify = async () => Promise.all((await windows()).map(async client => ({
    client, answer: await ask(client, 'identify', {}),
  })));
  let candidates = await identify();
  let selected = candidates.find(item => item.answer?.actor === data.actor);
  if (!selected) {
    candidates = await identify(); // client disappearance / new tab race: recheck before open
    selected = candidates.find(item => item.answer?.actor === data.actor);
  }
  if (selected) {
    try {
      await selected.client.focus();
      // Page reauthorizes and holds navigation when dirty; never WindowClient.navigate.
      selected.client.postMessage({ protocol, type: 'destination', ...data });
    } catch {
      // A focus refusal must never create duplicate tabs. A later click can retry.
      selected.client.postMessage({ protocol, type: 'focus-failed' });
    }
  } else if (!candidates.some(item => typeof item.answer?.actor !== 'string' ||
      !/^[a-zA-Z0-9_.@-]{1,200}$/.test(item.answer.actor))) {
    const url = new URL(data.test ? '/ui/me' : data.url, self.location.origin);
    url.searchParams.set('as', data.actor); // selector only, never credentials
    await self.clients.openWindow(url.href);
  }
}
self.addEventListener('notificationclick', event => {
  event.notification.close();
  serial = serial.catch(() => {}).then(() => route(event.notification.data));
  event.waitUntil(serial);
});
self.addEventListener('message', event => {
  if (event.data?.protocol !== protocol || event.data.type !== 'show') return;
  serial = serial.catch(() => {}).then(async () => {
    try { event.ports[0]?.postMessage(await show(event.source, event.data, event.data.test === true)); }
    catch { event.ports[0]?.postMessage({ error: 'Notification unavailable. Use Needs you.' }); }
  });
  event.waitUntil(serial);
});
