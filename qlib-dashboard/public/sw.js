const CACHE_NAME = 'alpha-engine-shell-v1';
const APP_ROOT = new URL('./', self.location.href);
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

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Research bundles can be large and user-selected. Cache only the application shell.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(new URL('./index.html', APP_ROOT), copy));
          return response;
        })
        .catch(() => caches.match(new URL('./index.html', APP_ROOT))),
    );
    return;
  }

  if (SHELL_URLS.includes(url.toString())) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});
