// Minimal service worker: lets phones install Crochet Studio as an app, and keeps the app's own
// scripts and styles cached so pages open fast. Pages and data always come fresh from the laptop.
const CACHE = 'crochet-static-v3';
const STATIC = ['/static/style.css', '/static/app.js', '/static/vendor/htmx.min.js', '/static/vendor/alpine.min.js',
  '/static/yarn.svg', '/static/icon-192.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/static/')) return;
  // Static files: use the network when possible (so updates show up), fall back to the cache.
  event.respondWith(
    fetch(event.request)
      .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(event.request, copy)); return res; })
      .catch(() => caches.match(event.request)),
  );
});
