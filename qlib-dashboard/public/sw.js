const CACHE_NAME = 'alpha-engine-shell-v3';
const APP_ROOT = new URL('./', self.location.href);
const FORMAL_BACKTEST_ROOT = new URL('./data/formal-backtests/', APP_ROOT);
const SHELL_URLS = [
  new URL('./', APP_ROOT).toString(),
  new URL('./index.html', APP_ROOT).toString(),
  new URL('./manifest.webmanifest', APP_ROOT).toString(),
  new URL('./icons/alpha-engine.svg', APP_ROOT).toString(),
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, { cache: 'no-store' })
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(new URL('./index.html', APP_ROOT), copy));
          return response;
        })
        .catch(() => caches.match(new URL('./index.html', APP_ROOT))),
    );
    return;
  }

  if (url.pathname.startsWith(FORMAL_BACKTEST_ROOT.pathname)) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        try {
          const response = await fetch(request, { cache: 'no-store' });
          if (response.ok) await cache.put(request, response.clone());
          return response;
        } catch {
          return cache.match(request);
        }
      }),
    );
    return;
  }

  if (SHELL_URLS.includes(url.toString())) {
    event.respondWith(
      fetch(request, { cache: 'no-store' })
        .then((response) => {
          if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(request, response.clone()));
          return response;
        })
        .catch(() => caches.match(request)),
    );
  }
});
